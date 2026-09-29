"""Development-only measurement of joined-word splitting and apostrophe restoration.

Positive cases are built from held-out development segments: two adjacent
words written together, or an elided form without its apostrophe. Controls
are unknown single words from the same segments, manual valid-word probes and
the synthetic single-word typos. Evaluation splits are never read.
"""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict, replace
from functools import lru_cache
import itertools
import json
from pathlib import Path
import time

from .benchmark import load_dataset, timings
from .contextual import DEFAULT_CORPUS
from .dictionary import default_dictionary
from .engine import AutocorrectEngine, Policy, latin_word
from .hunspell import HunspellValidator
from .leipzig_corpus import digest_file
from .segmentation import DEFAULT_COLLOQUIAL_WEIGHT, SegmentationPolicy, Segmenter, load_models


# Written from the user's request and common chat habits before measuring;
# they illustrate the target behaviour and are not a representative sample.
AUTHORED = {"perpiacere": "per piacere", "perfavore": "per favore", "lacqua": "l'acqua", "lho": "l'ho",
            "cè": "c'è", "nonlo": "non lo", "unamica": "un'amica", "unamico": "un amico", "dellacqua": "dell'acqua",
            "allinizio": "all'inizio", "lanno": "l'anno", "quellanno": "quell'anno", "senzaltro": "senz'altro",
            "dovè": "dov'è", "comè": "com'è", "unaltra": "un'altra", "vabene": "va bene", "apposto": "a posto",
            "dasolo": "da solo", "ciaocome": "ciao come"}
POLICY_GRID = {"min_ratio": (2.0, 5.0, 20.0), "word_edit_penalty": (0.0, 1.0, 2.0), "min_evidence": (2.0, 3.0)}


class CachedCounts:
    """Benchmark-only memo around TrainingNgrams.count; the grid repeats lookups."""

    def __init__(self, model):
        self.model = model
        self.count = lru_cache(maxsize=None)(lambda context, word: model.count(context, word))


def development_lines(paths):
    for path in paths:
        if path.name != "development.txt":
            raise ValueError("Il benchmark usa solo development.txt.")
        yield from path.read_text(encoding="utf-8").splitlines()


def joined_cases(lines, recognized):
    """Majority reading per joined surface; an attested alternative stays a competitor."""
    readings = defaultdict(Counter)
    for line in lines:
        words = line.split()
        for left, right in zip(words, words[1:]):
            if latin_word(left) and latin_word(right):
                readings[left + right][f"{left} {right}"] += 1
        for word in words:
            if word.count("'") == 1 and not word.endswith("'") and latin_word(word.replace("'", "")):
                readings[word.replace("'", "")][word] += 1
    cases = {"split": [], "elision": []}
    skipped = Counter()
    for joined, golds in sorted(readings.items()):
        if recognized(joined):
            skipped["joined_form_is_a_word"] += 1
            continue
        (expected, _), = golds.most_common(1)
        kind = "split" if " " in expected else "elision"
        cases[kind].append({"input": joined, "expected": expected, "readings": dict(golds)})
    return cases, dict(skipped)


def unknown_controls(lines, recognized):
    tokens = sorted({word for line in lines for word in line.split()
                     if "'" not in word and latin_word(word) and len(word) >= 2 and not recognized(word)})
    return [{"input": word, "expected": word} for word in tokens]


def measure(segmenter, cases, base):
    stats, errors, samples = Counter(), [], []
    for case in cases:
        decision = base[case["input"]]
        if decision.action == "correct":
            stats["engine_changed_" + ("right" if decision.output == case["expected"] else "wrong")] += 1
            continue
        started = time.perf_counter()
        result, _ = segmenter.evaluate(case["input"], decision)
        samples.append((time.perf_counter() - started) * 1000)
        if result.output == case["input"]:
            stats["unchanged" if case["expected"] != case["input"] else "kept"] += 1
        elif result.output == case["expected"]:
            stats["right"] += 1
        else:
            stats["wrong"] += 1
            errors.append({"input": case["input"], "output": result.output, "expected": case["expected"],
                           "reason": result.reason})
    return {"counts": dict(stats), "errors": errors, "latency": timings(samples)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--colloquial-corpus", type=Path)
    parser.add_argument("--colloquial-weight", type=float, default=DEFAULT_COLLOQUIAL_WEIGHT)
    parser.add_argument("--token-dataset", type=Path, default=Path("benchmark-data/it-seed42/development.json"))
    parser.add_argument("--frequency", type=int, default=5000)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("Usare una nuova cartella di output.")
    typos, typo_metadata = load_dataset(args.token_dataset)
    if typo_metadata.get("split") != "development":
        parser.error("Serve lo split development.")
    with ExitStack() as stack:
        validator = stack.enter_context(HunspellValidator())
        engine = AutocorrectEngine(default_dictionary(), policy=Policy(min_frequency=args.frequency), word_validator=validator)
        models = load_models(args.corpus, args.colloquial_corpus, args.colloquial_weight, stack)
        cached = [(CachedCounts(model), weight) for model, weight in models]
        recognized = lru_cache(maxsize=None)(lambda word: word in engine.symspell.words or validator.spell(word))
        sources = [args.corpus / "development.txt"]
        if args.colloquial_corpus is not None:
            sources.append(args.colloquial_corpus / "development.txt")
        lines = list(development_lines(sources))
        positives, skipped = joined_cases(lines, recognized)
        valid_probes = []
        for path in (Path("data/it_valid_words_development.json"), Path("data/it_valid_package_names_development.json")):
            valid_probes.extend(load_dataset(path)[0])
        groups = {"split_development": positives["split"], "elision_development": positives["elision"],
                  "authored_examples": [{"input": k, "expected": v} for k, v in AUTHORED.items()],
                  "unknown_word_controls": unknown_controls(lines, recognized),
                  "valid_word_probes": [{"input": c["input"], "expected": c["input"]} for c in valid_probes],
                  "single_word_typos": [c for c in typos if c["input"] != c["expected"]]}
        print({name: len(cases) for name, cases in groups.items()}, flush=True)
        base = {}
        for case in itertools.chain.from_iterable(groups.values()):
            if case["input"] not in base:
                base[case["input"]] = engine.evaluate(case["input"])
        segmenter = Segmenter(engine, cached)
        segmenter.readings = lru_cache(maxsize=None)(segmenter.readings)
        report = {"scope": "Development experiment. Positives are synthetic joins of adjacent development words, not observed typing.",
                  "engine_policy": asdict(engine.policy), "skipped_positive_surfaces": skipped,
                  "models": [{"metadata": model.metadata, "weight": weight} for model, weight in models],
                  "hunspell": validator.metadata,
                  "datasets": {"development_sha256": {str(p): digest_file(p) for p in sources},
                               "typos_sha256": digest_file(args.token_dataset)},
                  "source_sha256": {name: digest_file(Path(__file__).with_name(name))
                                    for name in ("segmentation.py", "segmentation_benchmark.py", "engine.py")},
                  "group_sizes": {name: len(cases) for name, cases in groups.items()}, "grid": []}
        for values in itertools.product(*POLICY_GRID.values()):
            policy = replace(SegmentationPolicy(), **dict(zip(POLICY_GRID, values)))
            segmenter.policy = policy
            result = {name: measure(segmenter, cases, base) for name, cases in groups.items()}
            report["grid"].append({"policy": asdict(policy), "groups": result})
            summary = {name: {k: v for k, v in arm["counts"].items() if k in ("right", "wrong")} for name, arm in result.items()}
            print(json.dumps({"policy": {k: getattr(policy, k) for k in POLICY_GRID}, **summary}, ensure_ascii=False), flush=True)
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
