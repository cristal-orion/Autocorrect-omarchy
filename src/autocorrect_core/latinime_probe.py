"""Experimental Linux LatinIME client; independent of the installed Fcitx bridge."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time

from .aosp_data import SHA256 as AOSP_SHA256, load_wordlist
from .dictionary import default_dictionary
from .engine import AutocorrectEngine, Decision, latin_word, normalize
from .hunspell import HunspellValidator
from .prediction import scan_text


DEFAULT_BINARY = Path("build/latinime-probe/latinime-probe")
DEFAULT_DATA = Path("benchmark-data/latinime-it")
POLICY = {
    "name": "latinime-probe-v1", "normalized_score_threshold": 0.185,
    "min_auto_length": 5,
    "description": "Native appropriate flag + AOSP modest threshold, with baseline lexical/Hunspell/elision/protected guards. Not the complete Android Java policy.",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode_probability(probability):
    """AOSP ProbabilityUtils encoding; input here is a surrogate, not calibrated."""
    if not 0 < probability <= 1:
        raise ValueError("Probabilità fuori da (0, 1].")
    return max(0, min(255, int(255 + math.log2(probability) * 8.58923700372 + 0.5)))


def export_tables(data):
    scores = {word: score for word, score in data.scores.items() if len(word) < 48}
    unigrams = "".join(f"1\t{score}\t{word}\n" for word, score in sorted(scores.items()))
    rows = defaultdict(dict)
    for (previous, target), rank in data.bigrams.items():
        if previous in scores and target in scores:
            rows[previous][target] = 1 / rank
    bigrams = []
    for previous, targets in sorted(rows.items()):
        total = sum(targets.values())
        for target, weight in sorted(targets.items()):
            code = encode_probability(weight / total)
            bigrams.append(f"2\t{code}\t{previous}\t{target}\n")
    return {"unigrams": unigrams, "rank-bigrams": unigrams + "".join(bigrams)}, {
        "words": len(scores), "bigrams": len(bigrams), "excluded_long_words": len(data.scores) - len(scores),
    }


def prepare(source, binary, destination):
    if destination.exists():
        raise ValueError("La cartella di destinazione deve essere nuova.")
    if sha256(source) != AOSP_SHA256:
        raise ValueError("Serve la wordlist italiana della revisione AOSP fissata.")
    data = load_wordlist(source)
    tables, counts = export_tables(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".latinime-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        compiled = {}
        for name, table in tables.items():
            table_path = stage / f"{name}.tsv"
            table_path.write_text(table, encoding="utf-8")
            result = subprocess.run([str(binary.resolve()), "--compile", str(table_path), str(stage / name)],
                                    check=True, text=True, capture_output=True, timeout=180)
            compiled[name] = json.loads(result.stdout)
            expected = {"words": counts["words"], "bigrams": counts["bigrams"] if name == "rank-bigrams" else 0}
            if compiled[name] != expected:
                raise ValueError("Conteggi nativi diversi dall'esportazione.")
        manifest = {
            "format_version": 1, "source_sha256": AOSP_SHA256, "source_metadata": data.metadata,
            "binary_sha256": sha256(binary), "counts": counts, "compiled_counts": compiled,
            "unigram_mapping": "Original normalized AOSP compressed codes, unchanged (not counts).",
            "bigram_mapping": "EXPERIMENTAL: normalize 1/rank within each truncated row, then encode with AOSP 255 + log2(p)*8.58923700372. Not original Android bigram decoding or calibrated probabilities; assigns all mass to retained continuations.",
            "native_format": 403, "history": False, "normalization": "Existing aosp_data parser; additionally exclude words with >=48 code points.",
            "files_sha256": {str(p.relative_to(stage)): sha256(p) for p in sorted(stage.rglob("*")) if p.is_file()},
            "source_code_sha256": sha256(__file__),
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.rename(destination)
    return manifest


def context_words(previous):
    # Only the open sentence is sent: punctuation, numbers and structured tokens
    # are boundaries, just as in the existing predictor.
    _, current = scan_text(previous)
    return current[-3:] if all(len(word) < 48 for word in current[-3:]) else []


class NativeClient:
    def __init__(self, binary, dictionary, *, timeout=10):
        self.timeout = timeout
        self.buffer = b""
        self.closed = False
        started = time.perf_counter()
        self.process = subprocess.Popen([str(Path(binary).resolve()), str(Path(dictionary).resolve())],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            self.ready = self._read(timeout=30)
            if self.ready.get("ready") is not True:
                raise ValueError("Il processo nativo non è pronto.")
        except BaseException:
            self.close()
            raise
        self.startup_wall_ms = (time.perf_counter() - started) * 1000

    def _read(self, *, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("Timeout del laboratorio LatinIME.")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(f"Processo LatinIME terminato (exit={self.process.poll()}).")
            self.buffer += chunk
            if len(self.buffer) > 1024 * 1024:
                raise ValueError("Risposta nativa troppo grande.")
        line, self.buffer = self.buffer.split(b"\n", 1)
        response = json.loads(line)
        if "error" in response:
            raise ValueError(response["error"])
        return response

    def query(self, token, previous=""):
        if self.closed:
            raise RuntimeError("Il client LatinIME è chiuso.")
        if len(normalize(token)) >= 48:
            raise ValueError("LatinIME richiede meno di 48 code point per token.")
        request = {"input": normalize(token), "previous": context_words(previous)}
        raw = (json.dumps(request, ensure_ascii=False) + "\n").encode()
        if len(raw) > 16384:
            raise ValueError("Richiesta troppo grande.")
        started = time.perf_counter()
        try:
            self.process.stdin.write(raw)
            response = self._read()
        except (OSError, RuntimeError):
            # A late reply must never be mistaken for the next word's response.
            self.close()
            raise
        response["roundtrip_ms"] = (time.perf_counter() - started) * 1000
        response["previous_words"] = request["previous"]
        # Android also removes duplicate strings after native traversal. Keep
        # the highest-ranked occurrence without promoting another spelling.
        response["raw_candidate_count"] = len(response["candidates"])
        seen = set()
        unique = []
        for candidate in response["candidates"]:
            if candidate["term"] not in seen:
                unique.append(candidate)
                seen.add(candidate["term"])
        response["candidates"] = unique
        return response

    def memory(self):
        values = {}
        for line in Path(f"/proc/{self.process.pid}/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value, _ = line.split()
                values[key.rstrip(":")] = round(int(value) / 1024, 2)
        return values

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()
        self.selector.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@dataclass(frozen=True)
class NativeCandidate:
    term: str
    score: int
    normalized_score: float | None
    appropriate_for_autocorrection: bool
    type: int


def decide(token, native, baseline, *, threshold=0.185, context="text"):
    """Probe policy, not an Android policy port; keep ranking separate from it."""
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("La soglia deve essere positiva e finita.")
    candidates = tuple(NativeCandidate(**item) for item in native["candidates"])
    word = normalize(token)
    # Reuse the baseline's recognition gates, not its frequency/margin/distance.
    guard = baseline.evaluate(token, context=context)
    reasons = {"disabled_context", "too_long", "empty", "protected_word", "known_word",
               "apostrophe_requires_context", "non_word", "valid_word", "possible_elision"}
    reason = "native_threshold"
    if guard.reason in reasons:
        reason = guard.reason
    elif native["input_probability_code"] >= 0:
        reason = "native_known_word"
    elif token != token.lower():
        reason = "capitalized_or_mixed_case"
    elif len(word) < POLICY["min_auto_length"]:
        reason = "short_word"
    elif not candidates:
        reason = "no_candidate"
    else:
        best = candidates[0]
        if best.term in baseline.protected:
            reason = "protected_candidate"
        elif not latin_word(best.term) or best.term != best.term.lower():
            reason = "unsupported_candidate_form"
        elif best.term == word:
            reason = "native_keeps_input"
        elif not best.appropriate_for_autocorrection:
            reason = "native_not_appropriate"
        elif best.normalized_score is None or best.normalized_score < threshold:
            reason = "native_low_score"
    corrected = reason == "native_threshold"
    return Decision(token, candidates[0].term if corrected else token,
                    "correct" if corrected else "keep", reason, candidates, len(candidates))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--aosp-wordlist", type=Path, default=Path("benchmark-data/aosp-it/main_it.combined"))
    prep.add_argument("--output-dir", type=Path, default=DEFAULT_DATA)
    prep.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    query = sub.add_parser("query")
    query.add_argument("token")
    query.add_argument("--previous", default="")
    query.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    query.add_argument("--native-dictionary", type=Path, default=DEFAULT_DATA / "unigrams")
    query.add_argument("--threshold", type=float, default=0.185)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.aosp_wordlist, args.binary, args.output_dir)
            print(json.dumps(result["compiled_counts"], indent=2))
        else:
            with HunspellValidator() as validator, NativeClient(args.binary, args.native_dictionary) as native:
                baseline = AutocorrectEngine(default_dictionary(), word_validator=validator)
                response = native.query(args.token, args.previous)
                decision = decide(args.token, response, baseline, threshold=args.threshold)
                print(json.dumps({"policy": {**POLICY, "normalized_score_threshold": args.threshold},
                                  "decision": decision.to_dict(), "native": response,
                                  "startup": native.ready, "memory_mib": native.memory()},
                                 ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
