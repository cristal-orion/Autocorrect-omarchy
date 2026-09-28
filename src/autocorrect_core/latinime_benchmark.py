"""Development-only comparison of the native probe, baseline and shared lexical ranking."""

import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import platform
import tempfile
import time

from symspellpy import Verbosity

from .benchmark import load_dataset, quality, timings
from .data_ablation import load_context_cases
from .dictionary import SHA256, default_dictionary
from .engine import AutocorrectEngine, Decision, normalize
from .hunspell import HunspellValidator
from .latinime_probe import DEFAULT_BINARY, DEFAULT_DATA, POLICY, NativeClient, decide, sha256


def rank_quality(rows):
    return {"cases": len(rows), "target_top1": sum(row[0] == 1 for row in rows),
            "target_top3": sum(row[0] is not None and row[0] <= 3 for row in rows),
            "target_top5": sum(row[0] is not None and row[0] <= 5 for row in rows)}


def rank(words, target):
    return words.index(target) + 1 if target in words else None


def compare(args):
    if args.output.exists():
        raise ValueError("Il report di destinazione deve essere nuovo.")
    dataset_paths = {"development": args.dataset,
                     "valid_words": Path("data/it_valid_words_development.json"),
                     "package_names": Path("data/it_valid_package_names_development.json")}
    datasets, provenance = {}, {}
    for name, path in dataset_paths.items():
        cases, metadata = load_dataset(path)
        if metadata.get("split") == "evaluation":
            raise ValueError("La prova usa lo sviluppo, non lo split evaluation.")
        datasets[name] = cases
        provenance[name] = {"sha256": sha256(path), "metadata": metadata}
    context_cases, context_metadata = load_context_cases(args.context_dataset)
    if context_metadata.get("split") == "evaluation":
        raise ValueError("Usare casi contestuali di sviluppo, non evaluation.")
    dictionary = default_dictionary()
    if sha256(dictionary) != SHA256:
        raise ValueError("Checksum baseline non valido.")
    data_manifest = json.loads((args.data_dir / "manifest.json").read_text())
    for name, digest in data_manifest["files_sha256"].items():
        if sha256(args.data_dir / name) != digest:
            raise ValueError(f"Dati nativi modificati: {name}")
    build_manifest = json.loads((args.binary.parent / "build-manifest.json").read_text())
    if sha256(args.binary) != build_manifest["binary_sha256"]:
        raise ValueError("Binario diverso dal manifest di build.")
    report = {
        "scope": "Development only. Native engine + explicit probe policy, not Android/FUTO product quality. No personal data.",
        "platform": platform.platform(), "python": platform.python_version(), "datasets": provenance,
        "baseline_dictionary_sha256": SHA256, "native_build": build_manifest,
        "native_data": data_manifest, "probe_policy": POLICY,
        "source_sha256": {name: sha256(Path(__file__).with_name(name)) for name in
                          ("latinime_probe.py", "latinime_benchmark.py", "engine.py", "benchmark.py")},
        "arms": {}, "context": {"metadata": context_metadata, "sha256": sha256(args.context_dataset), "arms": {}},
    }
    with HunspellValidator() as validator:
        baseline = AutocorrectEngine(dictionary, word_validator=validator)
        report["hunspell"] = validator.metadata
        report["protected_words"] = sorted(baseline.protected)
        for frequency in (100000, 5000):
            baseline.policy = replace(baseline.policy, min_frequency=frequency)
            arm = {"policy": asdict(baseline.policy), "datasets": {}}
            for name, cases in datasets.items():
                samples, decisions = [], []
                for case in cases:
                    start = time.perf_counter()
                    decisions.append(baseline.evaluate(case["input"], context=case.get("context", "text")))
                    samples.append((time.perf_counter() - start) * 1000)
                arm["datasets"][name] = {"quality": quality(cases, decisions, details="errors"), "latency": timings(samples)}
            report["arms"][f"symspell_{frequency}"] = arm
        baseline.policy = replace(baseline.policy, min_frequency=100000)
        # Same normalized lexicon/codes, without the baseline count-based gate.
        # This arm is ranking-only: compressed scores aren't baseline counts.
        with NativeClient(args.binary, args.data_dir / "unigrams") as client:
            native_arm = {"startup_native": client.ready, "startup_wall_ms": client.startup_wall_ms, "datasets": {}}
            native_typo_ranks = []
            native_shared_ranks = []
            native_words = {}
            for line in (args.data_dir / "unigrams.tsv").read_text().splitlines():
                _, code, word = line.split("\t")
                native_words[word] = int(code)
            for name, cases in datasets.items():
                print(f"LatinIME: {name}, {len(cases)} richieste...", flush=True)
                decisions, native_samples, ipc_samples, end_to_end, typo_samples = [], [], [], [], []
                for case in cases:
                    start = time.perf_counter()
                    if len(normalize(case["input"])) >= 48:
                        decisions.append(Decision(case["input"], case["input"], "keep", "native_too_long"))
                        continue
                    response = client.query(case["input"])
                    decision = decide(case["input"], response, baseline, context=case.get("context", "text"))
                    end_to_end.append((time.perf_counter() - start) * 1000)
                    decisions.append(decision)
                    native_samples.append(response["native_ms"])
                    ipc_samples.append(response["roundtrip_ms"])
                    if case["input"] != case["expected"]:
                        typo_samples.append(response["native_ms"])
                        if name == "development":
                            terms = [c["term"] for c in response["candidates"]]
                            item = (rank(terms, case["expected"]),)
                            native_typo_ranks.append(item)
                            if normalize(case["expected"]) in native_words:
                                native_shared_ranks.append(item)
                native_arm["datasets"][name] = {
                    "quality": quality(cases, decisions, details="errors"),
                    "native_all": timings(native_samples), "native_typos": timings(typo_samples),
                    "json_pipe_roundtrip": timings(ipc_samples), "including_probe_policy": timings(end_to_end),
                }
            native_arm["memory_mib"] = client.memory()
            report["arms"]["latinime_unigrams"] = native_arm
        # Generate a temporary lexicon with identical codes; it isn't an automatic
        # correction policy and its integer scores are not labelled frequencies.
        with tempfile.TemporaryDirectory() as directory_name:
            lexical_path = Path(directory_name) / "scores.txt"
            lexical_path.write_text("".join(f"{word} {score}\n" for word, score in native_words.items()))
            shared_engine = AutocorrectEngine(lexical_path)
        symspell_ranks, symspell_shared_ranks = [], []
        for case in datasets["development"]:
            if case["input"] == case["expected"]:
                continue
            candidates = shared_engine.symspell.lookup(normalize(case["input"]), Verbosity.ALL, 2)
            candidates.sort(key=lambda c: (-(math.log10(c.count + 1) - 2 * c.distance), c.distance, c.term))
            item = (rank([c.term for c in candidates], case["expected"]),)
            symspell_ranks.append(item)
            if normalize(case["expected"]) in native_words:
                symspell_shared_ranks.append(item)
        report["shared_lexicon_ranking"] = {
            "description": "Identical 185k normalized AOSP forms/codes. SymSpell distance<=2 + existing log-code/edit penalty versus native spatial/linguistic scorer; raw candidates before abstention.",
            "all_typos": {"symspell": rank_quality(symspell_ranks), "latinime": rank_quality(native_typo_ranks)},
            "target_in_shared_lexicon": {"symspell": rank_quality(symspell_shared_ranks), "latinime": rank_quality(native_shared_ranks)},
        }
        for name in ("unigrams", "rank-bigrams"):
            with NativeClient(args.binary, args.data_dir / name) as client:
                rows = []
                for case in context_cases:
                    response = client.query(case["input"], case["previous"])
                    terms = [c["term"] for c in response["candidates"]]
                    decision = decide(case["input"], response, baseline)
                    rows.append({**case, "target_rank": rank(terms, case["expected"]),
                                 "output": decision.output, "reason": decision.reason, "native": response})
                report["context"]["arms"][name] = {
                    "by_task": {task: rank_quality([(row["target_rank"],) for row in rows if row["task"] == task])
                                for task in ("correction", "next_word")},
                    "latency": timings([row["native"]["native_ms"] for row in rows]), "cases": rows,
                }
    quality_native = report["arms"]["latinime_unigrams"]["datasets"]["development"]["quality"]
    reference = report["arms"]["symspell_100000"]["datasets"]["development"]["quality"]
    report["preliminary_gate"] = {
        "precision_at_least_reference": (quality_native["autocorrect_precision"] or 0) >= reference["autocorrect_precision"],
        "recall_at_least_5_points_higher": quality_native["typo_recall"] >= reference["typo_recall"] + 0.05,
        "no_more_keep_changes_each_dataset": all(
            report["arms"]["latinime_unigrams"]["datasets"][name]["quality"]["false_changes_on_keep_cases"] <=
            report["arms"]["symspell_100000"]["datasets"][name]["quality"]["false_changes_on_keep_cases"] for name in datasets),
        "native_typo_p95_under_10ms": report["arms"]["latinime_unigrams"]["datasets"]["development"]["native_typos"]["p95_ms"] < 10,
        "natural_text_validation": "not performed; necessary before promotion",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--context-dataset", type=Path, default=Path("data/it_context_diagnostic.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args)
    print(json.dumps({"arms": {name: {key: arm["datasets"]["development"]["quality"][key] for key in
                                      ("correct_changes", "wrong_changes", "autocorrect_precision", "typo_recall")}
                                for name, arm in report["arms"].items()},
                      "shared_lexicon_ranking": report["shared_lexicon_ranking"],
                      "context": {name: arm["by_task"] for name, arm in report["context"]["arms"].items()},
                      "gate": report["preliminary_gate"]}, indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
