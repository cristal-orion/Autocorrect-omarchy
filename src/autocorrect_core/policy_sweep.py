"""Development-only frequency sweep, with a fixed margin and Hunspell veto."""

import argparse
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

from .benchmark import load_dataset, quality, ratio
from .dictionary import SHA256, default_dictionary
from .engine import AutocorrectEngine, latin_word, normalize
from .hunspell import HunspellValidator


def recognition(engine, token):
    word = normalize(token)
    if word in engine.symspell.words:
        return "frequency_lexicon"
    if not latin_word(word):
        return "structured_or_non_alphabetic"
    if engine.word_validator.spell(word):
        return "hunspell_only"
    return "unknown_to_both"


def sweep(engine, datasets, *, frequencies=(100000, 20000, 5000, 1000), margin=1.3, probes=()):
    if engine.word_validator is None:
        raise ValueError("Lo sweep richiede Hunspell, per conservare le forme riconosciute.")
    if not frequencies or len(set(frequencies)) != len(frequencies) or any(type(f) is not int or f < 1 for f in frequencies):
        raise ValueError("Le frequenze devono essere interi positivi distinti.")
    if frequencies[0] != max(frequencies):
        raise ValueError("La prima frequenza deve essere la baseline più restrittiva.")
    original_policy = engine.policy
    policy = replace(original_policy, min_score_margin=margin)
    groups = {name: [recognition(engine, case["input"]) for case in cases]
              for name, cases in datasets.items()}
    baseline = {}
    rows = []
    try:
        for frequency in frequencies:
            engine.policy = replace(policy, min_frequency=frequency)
            row = {"policy": asdict(engine.policy), "datasets": {}, "probes": {}}
            for name, cases in datasets.items():
                decisions = [engine.evaluate(case["input"], context=case.get("context", "text")) for case in cases]
                if name not in baseline:
                    baseline[name] = decisions
                additional = []
                for case, old, new, group in zip(cases, baseline[name], decisions, groups[name]):
                    if old.output != new.output:
                        # Frequency can only release a prior abstention; all
                        # other gates, including margin after frequency, remain.
                        if old.output != case["input"] or group != "unknown_to_both":
                            raise AssertionError("Lo sweep ha modificato una decisione fuori dall'insieme previsto.")
                        additional.append({**case, "output": new.output, "correct": new.output == case["expected"],
                                           "previous_reason": old.reason, "score_margin": new.score_margin,
                                           "candidate_frequency": new.candidates[0].frequency})
                correct = sum(item["correct"] for item in additional)
                grouped = {}
                for group in sorted(set(groups[name])):
                    indexes = [i for i, value in enumerate(groups[name]) if value == group]
                    grouped[group] = quality([cases[i] for i in indexes], [decisions[i] for i in indexes], details="errors")
                row["datasets"][name] = {
                    "quality": quality(cases, decisions, details="errors"), "by_recognition": grouped,
                    "additional_vs_baseline": {"correct": correct, "wrong": len(additional) - correct,
                                               "precision": ratio(correct, len(additional)), "cases": additional},
                }
            for token in probes:
                row["probes"][token] = engine.evaluate(token).to_dict()
            rows.append(row)
    finally:
        engine.policy = original_policy
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--keep-dataset", type=Path, default=Path("data/it_valid_words_development.json"))
    parser.add_argument("--extra-keep-dataset", type=Path, help="Ulteriore insieme da conservare, riportato separatamente")
    parser.add_argument("--dictionary", type=Path)
    parser.add_argument("--frequencies", type=int, nargs="+", default=[100000, 20000, 5000, 1000])
    parser.add_argument("--margin", type=float, default=1.3)
    parser.add_argument("--probe", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        datasets, provenance = {}, {}
        sources = [("development", args.dataset), ("valid_words", args.keep_dataset)]
        if args.extra_keep_dataset:
            sources.append(("extra_valid_words", args.extra_keep_dataset))
        for name, path in sources:
            cases, metadata = load_dataset(path)
            if metadata.get("split") == "evaluation":
                raise ValueError("Usare lo sviluppo per esplorare le soglie, non lo split evaluation.")
            if name != "development" and any(case["input"] != case["expected"] for case in cases):
                raise ValueError("Il dataset di conservazione deve contenere solo input da mantenere.")
            datasets[name] = cases
            provenance[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "metadata": metadata}
        dictionary = args.dictionary or default_dictionary()
        with HunspellValidator() as validator:
            engine = AutocorrectEngine(dictionary, word_validator=validator)
            if args.dictionary is None and engine.dictionary_sha256 != SHA256:
                raise ValueError("Checksum del dizionario predefinito non valido.")
            report = {
                "scope": "Frequency-only development sweep; unknown to two lexicons does not imply an actual typo.",
                "dictionary_sha256": engine.dictionary_sha256, "datasets": provenance,
                "protected_words_sha256": hashlib.sha256("\n".join(sorted(engine.protected)).encode()).hexdigest(),
                "personal_data": "No user protected-word list or personal memory loaded.",
                "hunspell": validator.metadata, "python": platform.python_version(), "symspellpy": version("symspellpy"),
                "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                  for name in ("policy_sweep.py", "engine.py", "benchmark.py")},
                "rows": sweep(engine, datasets, frequencies=args.frequencies, margin=args.margin, probes=args.probe),
            }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    for row in report["rows"]:
        development = row["datasets"]["development"]
        print(json.dumps({"min_frequency": row["policy"]["min_frequency"],
                          **{key: development["quality"][key] for key in (
                              "correct_changes", "wrong_changes", "autocorrect_precision", "typo_recall")},
                          "additional": {key: value for key, value in development["additional_vs_baseline"].items() if key != "cases"},
                          "valid_words_changed": row["datasets"]["valid_words"]["quality"]["false_changes_on_keep_cases"],
                          "extra_valid_words_changed": row["datasets"].get("extra_valid_words", {}).get("quality", {}).get("false_changes_on_keep_cases"),
                          "probes": {token: {"output": result["output"], "reason": result["reason"]}
                                     for token, result in row["probes"].items()}}, ensure_ascii=False))
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
