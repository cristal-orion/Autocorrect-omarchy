"""Pinned Italian AOSP-compatible wordlist: scores and ranks, not corpus counts."""

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request

from .engine import normalize
from .prediction import NgramModel, is_word


REVISION = "55e6d1c64ad72481d5615113b1c94f0716617016"
BASE_URL = f"https://codeberg.org/Helium314/aosp-dictionaries/raw/commit/{REVISION}"
URL = f"{BASE_URL}/wordlists_experimental/main_it.combined"
SHA256 = "50e0c819848e5d7b527dfcb0d21ca85fef3e90d99bd0f5f1d2435cacfa48301d"
MAX_BYTES = 16 * 1024 * 1024
ADAPTER = {
    "unigram_weights": "compressed f codes, linear, normalized by their sum; NOT recovered counts",
    "bigram_weights": "1 / source rank, normalized within each previous-word row",
    "normalization": "NFC, lowercase, normalized apostrophes; collisions use max code / min rank",
    "interpolation": "existing NgramModel weights, no fitting; truncated rows are not a full language model",
}


@dataclass
class Wordlist:
    scores: dict[str, int]
    bigrams: dict[tuple[str, str], int]
    metadata: dict

    def model(self, *, with_bigrams=True) -> NgramModel:
        """Experimental relative weights, deliberately not a reconstructed corpus."""
        model = NgramModel()
        model.add_counts({((), word): score for word, score in self.scores.items()})
        if with_bigrams:
            model.add_counts({((previous,), word): 1.0 / rank
                              for (previous, word), rank in self.bigrams.items()})
        return model

    def lexicon_bytes(self) -> bytes:
        header = "# AOSP compressed scores, NOT frequency counts. Default automatic thresholds are incompatible.\n"
        return (header + "".join(f"{word} {score}\n" for word, score in sorted(self.scores.items()))).encode("utf-8")


def parse_combined(raw: bytes) -> Wordlist:
    """Strict subset used by the pinned Italian source; reject unknown semantics."""
    scores, edges, seen_words = {}, {}, set()
    stats = Counter()
    header = None
    current = None
    seen_targets = set()
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        parts = [part.strip().split("=", 1) for part in line.strip().split(",")]
        if any(len(part) != 2 for part in parts):
            raise ValueError(f"AOSP riga {number}: attributo non valido.")
        attrs = dict(parts)
        if len(attrs) != len(parts):
            raise ValueError(f"AOSP riga {number}: attributo duplicato.")
        kind = parts[0][0]
        if kind == "dictionary":
            if header is not None or seen_words or attrs.get("locale") != "it":
                raise ValueError("Intestazione AOSP italiana assente o ripetuta.")
            header = attrs
            continue
        if header is None or kind not in ("word", "bigram"):
            raise ValueError(f"AOSP riga {number}: tipo non supportato {kind}.")
        allowed = {kind, "f"} | ({"not_a_word", "possibly_offensive"} if kind == "word" else set())
        if not set(attrs) <= allowed or "f" not in attrs or not attrs["f"].isdigit():
            raise ValueError(f"AOSP riga {number}: attributi o punteggio non supportati.")
        value = int(attrs["f"])
        original = attrs[kind]
        word = normalize(original)
        usable = is_word(word) and len(word) <= 64
        if kind == "word":
            if not 1 <= value <= 255 or not original or original in seen_words:
                raise ValueError(f"AOSP riga {number}: parola duplicata o codice fuori da 1..255.")
            seen_words.add(original)
            seen_targets = set()
            stats["source_words"] += 1
            stats["case_normalized_words"] += original != original.lower()
            for flag in ("not_a_word", "possibly_offensive"):
                if flag in attrs and attrs[flag] not in ("true", "false"):
                    raise ValueError(f"AOSP riga {number}: flag non valido.")
                if attrs.get(flag) == "true":
                    usable = False
                    stats[flag] += 1
            current = word if usable else None
            if usable:
                stats["normalization_collisions"] += word in scores
                scores[word] = max(scores.get(word, 0), value)
            else:
                stats["excluded_words"] += 1
        else:
            if not seen_words or value < 1 or value > 3 or original in seen_targets:
                raise ValueError(f"AOSP riga {number}: bigramma orfano, duplicato o rango fuori da 1..3.")
            seen_targets.add(original)
            stats["source_bigrams"] += 1
            if current is not None and usable:
                key = (current, word)
                edges[key] = min(edges.get(key, value), value)
            else:
                stats["excluded_bigrams"] += 1
    if header is None or not scores:
        raise ValueError("Wordlist AOSP vuota.")
    bigrams = {key: rank for key, rank in edges.items() if key[1] in scores}
    stats["bigrams_with_missing_target"] = len(edges) - len(bigrams)
    stats["normalized_words"] = len(scores)
    stats["normalized_bigrams"] = len(bigrams)
    stats["previous_words_with_bigrams"] = len({previous for previous, _ in bigrams})
    return Wordlist(scores, bigrams, {
        "header": header, "statistics": dict(sorted(stats.items())),
        "score_range": [min(scores.values()), max(scores.values())],
        "bigram_rank_histogram": dict(sorted(Counter(bigrams.values()).items())),
        "sha256": hashlib.sha256(raw).hexdigest(), "adapter": ADAPTER,
    })


def load_wordlist(path: Path) -> Wordlist:
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Wordlist oltre la dimensione massima prevista.")
    return parse_combined(raw)


def write_once(path: Path, raw: bytes):
    """Repeatable import without replacing existing files with different content."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError(f"File esistente diverso dai dati attesi: {path}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_wordlist(destination: Path, source: Path | None = None) -> dict:
    cached = destination / "main_it.combined"
    if source is not None or cached.exists():
        with (source or cached).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Wordlist italiana: dimensione o checksum diversi dalla revisione fissata.")
    data = parse_combined(raw)
    lexicon = data.lexicon_bytes()
    metadata = {
        "format_version": 1, "revision": REVISION, "url": URL,
        "source_notice_url": f"{BASE_URL}/wordlists_experimental/main_it.source",
        "source_license_notice": "source lists under CC BY 4.0; see THIRD_PARTY.md",
        **data.metadata,
        "lexicon_scores_sha256": hashlib.sha256(lexicon).hexdigest(),
    }
    destination.mkdir(parents=True, exist_ok=True)
    write_once(cached, raw)
    write_once(destination / "lexicon-scores.txt", lexicon)
    write_once(destination / "manifest.json", (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode())
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="Copia locale della stessa revisione, verificata tramite SHA-256")
    args = parser.parse_args(argv)
    try:
        metadata = import_wordlist(args.output_dir, args.source)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
