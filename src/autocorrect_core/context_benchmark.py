"""Development-only contextual comparison, including deterministic held-out news typos."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from .benchmark import load_dataset, quality, timings, process_memory
from .contextual import ContextualCorrector, DEFAULT_CORPUS, TrainingNgrams
from .data_ablation import load_context_cases
from .dictionary import default_dictionary
from .engine import AutocorrectEngine, Policy, latin_word, normalize
from .generate_typos import mutations, stable_key
from .hunspell import HunspellValidator
from .leipzig_corpus import digest_file


def news_cases(path, engine, count=1000, *, three_letter_only=False):
    """One source/typo pair per segment, chosen without querying corrections."""
    if path.name != "development.txt":
        raise ValueError("Il generatore richiede development.txt, non training/evaluation.")
    lines = path.read_text().splitlines()
    seed = 20260928
    cases = []
    for line in sorted(lines, key=lambda text: stable_key(seed, "sentence", text)):
        words = line.split()
        min_length, max_length = (3, 4) if three_letter_only else (4, 15)
        excluded = {"pizza", "pisa", "stato"} | ({"cosa", "pane"} if three_letter_only else set())
        eligible = [(i, word) for i, word in enumerate(words) if i > 0 and min_length <= len(word) <= max_length
                    and latin_word(word) and word in engine.symspell.words
                    and word not in engine.protected and word not in excluded]
        eligible.sort(key=lambda item: stable_key(seed, "source", line + str(item[0])))
        selected = False
        for index, word in eligible:
            variants = [(operation, typo) for operation, typos in mutations(word).items() for typo in typos
                        if (len(typo) == 3 if three_letter_only else len(typo) >= 3)
                        and typo not in engine.symspell.words and typo not in engine.protected]
            variants.sort(key=lambda item: stable_key(seed, "variant", line + item[0] + item[1]))
            for operation, typo in variants:
                if engine.word_validator.spell(typo):
                    continue
                previous = " ".join(words[max(0, index - 2):index]) + " "
                common = {"previous": previous, "expected": word,
                          "sentence_sha256": hashlib.sha256(line.encode()).hexdigest()}
                cases.extend([{**common, "input": typo, "category": operation},
                              {**common, "input": word, "category": "clean_source"}])
                selected = True
                break
            if selected:
                break
        if len(cases) >= count * 2:
            return cases
    raise ValueError("Segmenti di sviluppo insufficienti.")


def measure(corrector, cases, previous_corrector=None):
    baseline, contextual, previous, rows, new_rows = [], [], [], [], []
    samples, used_samples = [], []
    for case in cases:
        original = corrector.engine.evaluate(case["input"], context=case.get("context", "text"))
        started = time.perf_counter()
        result, info = corrector.evaluate(case["input"], case.get("previous", ""), context=case.get("context", "text"))
        elapsed = (time.perf_counter() - started) * 1000
        samples.append(elapsed)
        if info["used"]:
            used_samples.append(elapsed)
        baseline.append(original)
        contextual.append(result)
        if previous_corrector is not None:
            prior, _ = previous_corrector.evaluate(case["input"], case.get("previous", ""), context=case.get("context", "text"))
            previous.append(prior)
            if prior.output != result.output:
                if len(normalize(case["input"])) != 3:
                    raise AssertionError("Regressione: la nuova politica ha modificato un input di lunghezza diversa da tre.")
                new_rows.append({**case, "previous_output": prior.output, "output": result.output,
                                 "correct": result.output == case["expected"], "context_info": info})
        if original.output != result.output:
            if original.output != case["input"]:
                raise AssertionError("Il contesto ha modificato una decisione già automatica.")
            rows.append({**case, "baseline": original.output, "output": result.output,
                         "correct": result.output == case["expected"], "reason": result.reason,
                         "score_margin": result.score_margin, "context_info": info,
                         "candidates": [asdict(candidate) for candidate in result.candidates]})
    return {"baseline": quality(cases, baseline, details="errors"),
            "contextual": quality(cases, contextual, details="errors"),
            "previous_contextual": quality(cases, previous, details="errors") if previous_corrector else None,
            "three_letter_changes": new_rows,
            "additional_vs_previous": {"correct": sum(row["correct"] for row in new_rows),
                                       "wrong": sum(not row["correct"] for row in new_rows)},
            "additional_correct": sum(row["correct"] for row in rows),
            "additional_wrong": sum(not row["correct"] for row in rows),
            "changed_cases": rows, "latency_all": timings(samples), "latency_context_used": timings(used_samples)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--token-dataset", type=Path, default=Path("benchmark-data/it-seed42/development.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("Usare una nuova cartella di output.")
    tokens, token_metadata = load_dataset(args.token_dataset)
    if token_metadata.get("split") != "development":
        parser.error("Serve lo split development.")
    with HunspellValidator() as validator, TrainingNgrams.from_leipzig(args.corpus) as model:
        corpus_manifest = json.loads((args.corpus / "manifest.json").read_text())
        if digest_file(args.corpus / "development.txt") != corpus_manifest["files_sha256"]["development.txt"]:
            raise ValueError("Lo sviluppo Leipzig non corrisponde al manifest.")
        engine = AutocorrectEngine(default_dictionary(), policy=Policy(min_frequency=5000), word_validator=validator)
        corrector = ContextualCorrector(engine, model)
        previous_corrector = ContextualCorrector(engine, model)
        previous_corrector.policy = replace(corrector.policy, min_length=4)
        news = news_cases(args.corpus / "development.txt", engine)
        short_news = news_cases(args.corpus / "development.txt", engine, count=500, three_letter_only=True)
        user, user_meta = load_context_cases(Path("data/it_context_user_development.json"))
        diagnostic, diagnostic_meta = load_context_cases(Path("data/it_context_diagnostic.json"))
        diagnostic = [{**case, "category": "authored_typo"} for case in diagnostic if case["task"] == "correction"]
        keeps = []
        for path in (Path("data/it_valid_words_development.json"), Path("data/it_valid_package_names_development.json")):
            clean, _ = load_dataset(path)
            for previous in ("uso ", "con ", "ieri ho mangiato una "):
                keeps.extend({**case, "previous": previous} for case in clean)
        short_words_path = Path("data/it_short_words_development.json")
        short_words, short_metadata = load_dataset(short_words_path)
        short_keeps = [{**case, "previous": previous} for previous in
                       ("uso ", "con ", "ti devo dire una ", "oggi ho mangiato del prosciutto nel ")
                       for case in short_words]
        groups = {"token_regression_no_context": tokens, "news_development": news,
                  "three_letter_news_development": short_news, "short_keep_controls": short_keeps,
                  "user_and_authored": user, "existing_diagnostic_typos": diagnostic, "contextual_keep_controls": keeps}
        report = {"scope": "Development experiment, no threshold fitting on evaluation. User examples informed policy choices; news typos are synthetic, not natural typing errors.",
                  "context_policy": asdict(corrector.policy), "baseline_policy": asdict(engine.policy),
                  "previous_context_policy": asdict(previous_corrector.policy),
                  "corpus": model.metadata, "baseline_dictionary_sha256": engine.dictionary_sha256,
                  "hunspell": validator.metadata, "personal_data": "Only supplied user cases; no personal memory or protected-word file loaded.",
                  "datasets": {"tokens": {"sha256": digest_file(args.token_dataset), "metadata": token_metadata},
                               "news_development_sha256": digest_file(args.corpus / "development.txt"),
                               "user_cases_sha256": digest_file(Path("data/it_context_user_development.json")),
                               "diagnostic_cases_sha256": digest_file(Path("data/it_context_diagnostic.json")),
                               "short_words": {"sha256": digest_file(short_words_path), "metadata": short_metadata},
                               "user_metadata": user_meta, "diagnostic_metadata": diagnostic_meta},
                  "source_sha256": {name: digest_file(Path(__file__).with_name(name)) for name in
                                    ("contextual.py", "context_benchmark.py", "engine.py", "prediction.py")},
                  "groups": {}}
        for name, cases in groups.items():
            print(f"Confronto {name}: {len(cases)} casi", flush=True)
            model.row.cache_clear()
            report["groups"][name] = measure(corrector, cases, previous_corrector)
        report["memory"] = process_memory()
        report["row_cache"] = model.row.cache_info()._asdict()
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "news-cases.json").write_text(json.dumps({"metadata": {"format_version": 1, "split": "development",
            "seed": 20260928, "scope": "Synthetic errors in held-out news segments; pizza/pisa/stato sources excluded; clean originals included."}, "cases": news}, ensure_ascii=False, indent=2) + "\n")
        (args.output_dir / "three-letter-news-cases.json").write_text(json.dumps({"metadata": {
            "format_version": 1, "split": "development", "seed": 20260928,
            "scope": "500 synthetic three-letter typos and 500 clean originals. Sources pizza/pisa/stato/cosa/pane excluded; may overlap the general news sample."}, "cases": short_news}, ensure_ascii=False, indent=2) + "\n")
        (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(json.dumps({name: {"baseline_correct": arm["baseline"]["correct_changes"],
                                "baseline_wrong": arm["baseline"]["wrong_changes"],
                                "context_correct": arm["contextual"]["correct_changes"],
                                "context_wrong": arm["contextual"]["wrong_changes"],
                                "added_correct": arm["additional_correct"], "added_wrong": arm["additional_wrong"],
                                "additional_vs_previous": arm["additional_vs_previous"],
                                "latency_context_used": arm["latency_context_used"]} for name, arm in report["groups"].items()}, indent=2))


if __name__ == "__main__":
    main()
