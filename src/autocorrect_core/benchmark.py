"""Evaluate manual or generated datasets, including abstentions and bad changes."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import time

from .cli import add_engine_arguments, load_engine
from .engine import CONTEXTS, normalize


def load_dataset(path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = {}
    if isinstance(payload, dict):
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("format_version") != 1:
            raise ValueError("Dataset strutturato: metadata.format_version deve essere 1.")
        cases = payload.get("cases")
    else:
        cases = payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset atteso: lista JSON non vuota.")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(k), str) for k in ("input", "expected", "category")):
            raise ValueError("Ogni caso richiede input, expected e category testuali.")
        for key in ("source_word", "frequency_band", "length_band"):
            if key in case and not isinstance(case[key], str):
                raise ValueError(f"Il campo opzionale {key} deve essere testuale.")
        context = case.get("context", "text")
        if context not in CONTEXTS:
            raise ValueError(f"Contesto non valido nel dataset: {context}")
        key = (case["input"], context)
        if key in seen:
            raise ValueError(f"Caso duplicato: {key}")
        seen.add(key)
    return cases, metadata


def load_cases(path: Path) -> list[dict]:
    return load_dataset(path)[0]


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def wilson_interval(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def quality(cases, decisions, *, details="all"):
    if len(cases) != len(decisions):
        raise ValueError("Numero di decisioni diverso dal numero di casi.")
    if details not in ("all", "errors", "none"):
        raise ValueError("Dettagli consentiti: all, errors, none.")
    changes = correct_changes = typos = preserved = negatives = top1 = top5 = 0
    wrong_count = missed_count = 0
    wrong = []
    missed = []
    reasons = Counter()
    for case, result in zip(cases, decisions):
        typo = case["input"] != case["expected"]
        changed = result.output != case["input"]
        correct = result.output == case["expected"]
        typos += typo
        negatives += not typo
        changes += changed
        correct_changes += changed and correct
        preserved += not typo and not changed
        top1 += bool(typo and result.candidates and result.candidates[0].term == case["expected"])
        top5 += bool(typo and any(c.term == case["expected"] for c in result.candidates[:5]))
        reasons[result.reason] += 1
        item = {**case, "output": result.output, "reason": result.reason,
                "top_candidate": result.candidates[0].term if result.candidates else None}
        if changed and not correct:
            wrong_count += 1
            if details != "none":
                wrong.append({**item, "score_margin": result.score_margin,
                              "candidates": [asdict(c) for c in result.candidates]})
        elif typo and not changed:
            missed_count += 1
            if details == "all":
                missed.append(item)
    return {
        "cases": len(cases), "typos": typos, "keep_cases": negatives,
        "automatic_changes": changes, "correct_changes": correct_changes,
        "wrong_changes": wrong_count, "false_changes_on_keep_cases": negatives - preserved,
        "wrong_changes_on_typos": wrong_count - (negatives - preserved),
        "typo_abstentions": missed_count,
        "autocorrect_precision": ratio(correct_changes, changes),
        "precision_wilson_95": wilson_interval(correct_changes, changes),
        "typo_recall": ratio(correct_changes, typos),
        "keep_preservation": ratio(preserved, negatives),
        "false_change_rate_on_keep_cases": ratio(negatives - preserved, negatives),
        "top1_candidate_recall": ratio(top1, typos),
        "top5_candidate_recall": ratio(top5, typos),
        "reasons": dict(sorted(reasons.items())), "errors": wrong, "abstentions": missed,
    }


def timings(samples):
    if not samples:
        return None
    ordered = sorted(samples)

    def percentile(p):
        index = (len(ordered) - 1) * p
        low, high = math.floor(index), math.ceil(index)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 6)

    return {"samples": len(samples), "p50_ms": percentile(0.5),
            "p95_ms": percentile(0.95), "p99_ms": percentile(0.99),
            "max_ms": round(ordered[-1], 6)}


def process_memory():
    # getrusage().ru_maxrss may include a larger launching process before exec
    # on Linux. /proc's VmHWM describes this process image instead.
    try:
        values = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmHWM:", "VmRSS:")):
                name, count, unit = line.split()
                if unit == "kB":
                    values[name.rstrip(":")] = round(int(count) / 1024, 2)
        return {"source": "/proc/self/status", "peak_rss_mib": values.get("VmHWM"),
                "current_rss_mib": values.get("VmRSS")}
    except OSError:
        return {"source": "unavailable", "peak_rss_mib": None, "current_rss_mib": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, nargs="?", default=Path("data/it_smoke.json"))
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--details", choices=("all", "errors", "none"), default="all",
                        help="Dettagli per caso nel report; le metriche non cambiano")
    add_engine_arguments(parser)
    args = parser.parse_args(argv)
    if not 1 <= args.iterations <= 1000:
        parser.error("--iterations deve essere tra 1 e 1000.")
    try:
        cases, metadata = load_dataset(args.dataset)
        started = time.perf_counter_ns()
        engine = load_engine(args)
        load_ms = (time.perf_counter_ns() - started) / 1_000_000
        decisions = [engine.evaluate(case["input"], context=case.get("context", "text")) for case in cases]
        all_samples, lookup_samples = [], []
        for _ in range(args.iterations):
            for case in cases:
                started = time.perf_counter_ns()
                decision = engine.evaluate(case["input"], context=case.get("context", "text"))
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                all_samples.append(elapsed)
                if decision.candidate_count:
                    lookup_samples.append(elapsed)
        grouped = defaultdict(lambda: ([], []))
        frequency_groups = defaultdict(lambda: ([], []))
        lexicon_groups = defaultdict(lambda: ([], []))
        for case, decision in zip(cases, decisions):
            grouped[case["category"]][0].append(case)
            grouped[case["category"]][1].append(decision)
            frequency_groups[case.get("frequency_band", "unspecified")][0].append(case)
            frequency_groups[case.get("frequency_band", "unspecified")][1].append(decision)
            membership = "known" if normalize(case["input"]) in engine.symspell.words else "unknown"
            lexicon_groups[membership][0].append(case)
            lexicon_groups[membership][1].append(decision)
        report = {
            "scope": metadata.get("scope", "User-supplied dataset; no representativeness or held-out status assumed."),
            "dataset_metadata": metadata,
            "details": args.details,
            "source_word_count": len({case["source_word"] for case in cases if "source_word" in case}),
            "interval_caveat": "Wilson treats cases as independent; synthetic variants of the same word are correlated.",
            "python": platform.python_version(), "platform": platform.platform(),
            "symspellpy": version("symspellpy"), "policy": asdict(engine.policy),
            "dictionary_sha256": engine.dictionary_sha256, "dictionary_words": engine.word_count,
            "word_validator": engine.word_validator.metadata if engine.word_validator is not None else None,
            "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
            "protected_words_sha256": hashlib.sha256("\n".join(sorted(engine.protected)).encode()).hexdigest(),
            "protected_word_count": len(engine.protected),
            "quality": quality(cases, decisions, details=args.details),
            "by_category": {name: quality(*values, details="none") for name, values in sorted(grouped.items())},
            "by_frequency_band": {name: quality(*values, details="none") for name, values in sorted(frequency_groups.items())},
            "by_lexicon_membership": {name: quality(*values, details="none") for name, values in sorted(lexicon_groups.items())},
            "performance": {"dictionary_load_ms": round(load_ms, 3),
                            "memory": process_memory(),
                            "all_tokens": timings(all_samples),
                            "tokens_with_candidates": timings(lookup_samples)},
        }
        encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
            print(f"Risultati: {args.output}")
            print(json.dumps({k: v for k, v in report["quality"].items()
                              if k not in ("errors", "abstentions", "reasons")}, indent=2))
            print(json.dumps(report["performance"], indent=2))
        else:
            print(encoded, end="")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0
