"""Data-only ablations: lexical membership, compressed weights and ranked bigrams."""

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import time

from .aosp_data import ADAPTER, load_wordlist, write_once
from .benchmark import load_dataset, quality, ratio, timings
from .dictionary import SHA256, default_dictionary
from .engine import AutocorrectEngine, normalize, parse_lexicon
from .hunspell import HunspellValidator
from .prediction import ContextPredictor, NgramModel, is_word


def load_context_cases(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata"), dict):
        raise ValueError("I casi contestuali richiedono metadata e cases.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Casi contestuali assenti.")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(k), str)
                                               for k in ("previous", "input", "expected", "task")):
            raise ValueError("Ogni caso richiede previous, input, expected e task testuali.")
        if case["task"] not in ("correction", "next_word") or not is_word(case["expected"]):
            raise ValueError("Task o parola attesa non validi.")
        if (case["task"] == "next_word") != (case["input"] == ""):
            raise ValueError("Solo next_word richiede input vuoto.")
        if case["input"] and not is_word(case["input"]):
            raise ValueError("Il token da correggere deve essere una parola.")
        if case["previous"] and not case["previous"][-1].isspace():
            raise ValueError("previous deve terminare con uno spazio.")
        key = (case["previous"], case["input"])
        if key in seen or len("".join(key)) > 16384:
            raise ValueError("Caso contestuale duplicato o troppo lungo.")
        seen.add(key)
    return cases, payload["metadata"]


def measure_suggestions(engine, model, cases, *, base_label="aosp-pesi"):
    predictor = ContextPredictor(engine, model, base_label=base_label)
    results, samples = [], []
    for case in cases:
        started = time.perf_counter_ns()
        suggested = predictor.suggest(case["previous"] + case["input"])
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
        words = [normalize(item.word) for item in suggested.items]
        expected = normalize(case["expected"])
        results.append({**case, "suggestions": [asdict(item) for item in suggested.items],
                        "target_rank": words.index(expected) + 1 if expected in words else None})
    by_task = {}
    for task in sorted({case["task"] for case in cases}):
        rows = [row for row in results if row["task"] == task]
        by_task[task] = {
            "cases": len(rows), "target_top1": sum(row["target_rank"] == 1 for row in rows),
            "target_top3": sum(row["target_rank"] is not None for row in rows),
        }
    # The decorator caches instances too; release them before the next arm.
    predictor._suggest.cache_clear()
    predictor.completions.cache_clear()
    return {"by_task": by_task, "uncached_suggestion_latency": timings(samples), "cases": results}


def run_ablation(dataset: Path, aosp_path: Path, baseline_path: Path, output_dir: Path,
                 *, context_dataset: Path | None = None, hunspell=False):
    cases, metadata = load_dataset(dataset)
    context_cases, context_metadata = load_context_cases(context_dataset) if context_dataset else ([], {})
    raw_baseline = baseline_path.read_bytes()
    original = parse_lexicon(raw_baseline)
    data = load_wordlist(aosp_path)
    # Membership-only control: retain every old count, give new words a floor
    # below the existing auto threshold. This is not estimated frequency.
    extended = {**dict.fromkeys(data.scores, 1), **original}
    extended_raw = "".join(f"{word} {count}\n" for word, count in sorted(extended.items())).encode("utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    extended_path = output_dir / "lexicon-membership-control.txt"
    scores_path = output_dir / "lexicon-compressed-control.txt"
    write_once(extended_path, extended_raw)
    write_once(scores_path, data.lexicon_bytes())
    validator = HunspellValidator() if hunspell else None
    report = {
        "scope": "Data-only development experiment. No policy fitting, no personal memory or user protected list.",
        "dataset_metadata": metadata, "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "aosp": data.metadata, "adapter": ADAPTER,
        "python": platform.python_version(), "platform": platform.platform(), "symspellpy": version("symspellpy"),
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("aosp_data.py", "data_ablation.py", "engine.py", "prediction.py")},
        "baseline_dictionary_sha256": hashlib.sha256(raw_baseline).hexdigest(),
        "word_validator": validator.metadata if validator else None,
        "lexicon_overlap": {"baseline_words": len(original), "aosp_words": len(data.scores),
                            "shared": len(original.keys() & data.scores.keys()),
                            "aosp_only": len(data.scores.keys() - original.keys()),
                            "baseline_only": len(original.keys() - data.scores.keys())},
        "token_arms": {}, "suggestion_arms": {},
        "context_dataset_metadata": context_metadata,
        "context_dataset_sha256": hashlib.sha256(context_dataset.read_bytes()).hexdigest() if context_dataset else None,
        "caveats": [
            "Generated typo sources were selected from the baseline lexicon, so novel target coverage is not measured.",
            "Compressed codes are NOT counts: the unchanged frequency gate prevents automatic changes in that arm.",
            "Suggestion target hits are NOT automatic-correction precision; next words can have many valid continuations.",
            "The 1/rank adapter is a heuristic, not LatinIME decoding or recovery of missing corpus statistics.",
        ],
    }
    try:
        for name, path in (("baseline", baseline_path), ("membership_only", extended_path),
                           ("compressed_scores_control", scores_path)):
            print(f"Valutazione {name}...", flush=True)
            engine = AutocorrectEngine(path, word_validator=validator)
            decisions, samples = [], []
            for case in cases:
                started = time.perf_counter_ns()
                decisions.append(engine.evaluate(case["input"], context=case.get("context", "text")))
                samples.append((time.perf_counter_ns() - started) / 1_000_000)
            typo_cases = [case for case in cases if case["input"] != case["expected"]]
            target_membership = sum(normalize(case["expected"]) in engine.symspell.words for case in typo_cases)
            report["token_arms"][name] = {
                "dictionary_sha256": engine.dictionary_sha256, "words": engine.word_count,
                "policy": asdict(engine.policy), "quality": quality(cases, decisions, details="errors"),
                "target_lexicon_coverage": ratio(target_membership, len(typo_cases)),
                "latency_one_pass": timings(samples),
            }
            if context_cases and name != "membership_only":
                if name == "baseline":
                    frequency_model = NgramModel()
                    frequency_model.add_counts({((), word): count for word, count in original.items() if is_word(word)})
                    report["suggestion_arms"]["baseline_frequency"] = measure_suggestions(
                        engine, frequency_model, context_cases, base_label="frequenza")
                for with_bigrams in (False, True):
                    arm = f"{name}_aosp_{'bigrams' if with_bigrams else 'unigrams'}"
                    report["suggestion_arms"][arm] = measure_suggestions(engine, data.model(with_bigrams=with_bigrams), context_cases)
    finally:
        if validator is not None:
            validator.close()
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--aosp-wordlist", type=Path, required=True)
    parser.add_argument("--baseline-dictionary", type=Path)
    parser.add_argument("--context-dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--hunspell", action="store_true")
    args = parser.parse_args(argv)
    try:
        baseline = args.baseline_dictionary or default_dictionary()
        if args.baseline_dictionary is None and hashlib.sha256(baseline.read_bytes()).hexdigest() != SHA256:
            raise ValueError("Checksum del dizionario baseline predefinito non valido.")
        report = run_ablation(args.dataset, args.aosp_wordlist, baseline, args.output_dir,
                              context_dataset=args.context_dataset, hunspell=args.hunspell)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    print(json.dumps({"lexicon_overlap": report["lexicon_overlap"],
                      "tokens": {name: {key: arm["quality"][key] for key in (
                          "correct_changes", "wrong_changes", "autocorrect_precision", "typo_recall",
                          "top1_candidate_recall", "top5_candidate_recall")}
                                 for name, arm in report["token_arms"].items()},
                      "suggestions": {name: arm["by_task"] for name, arm in report["suggestion_arms"].items()}}, indent=2))
    print(f"Report completo: {args.output_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
