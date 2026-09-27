import contextlib
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from symspellpy.editdistance import DistanceAlgorithm, EditDistance

from autocorrect_core.benchmark import load_cases, load_dataset, quality
from autocorrect_core.engine import Decision
from autocorrect_core.generate_typos import (
    GenerationConfig, NEIGHBORS, encoded, generate_suite, main, mutations,
    split_for, stratified_sample, write_suite,
)


WORDS = """carta carto cara casa cassa gatto gatti gatta caffè perché libro libri
penna penne palla pelle domani quando questo progetto scrivere telefono
albero strada quartiere pianeta stazione binario armadio finestra luce
lampada quadro pavimento bicchiere tavolo cuore zaino mattina sera""".split()
LEXICON = {word: (2_000_000, 200_000, 20_000)[index % 3] for index, word in enumerate(WORDS)}


class TypoGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.config = GenerationConfig(words=25, extra_clean_words=10, typos_per_word=4)

    def test_all_mutations_are_single_edits_including_accents(self):
        distance = EditDistance(DistanceAlgorithm.DAMERAU_OSA)
        for word in ("progetto", "caffè", "perché", "lettera", "a", "aa"):
            for operation, variants in mutations(word).items():
                for typo in variants:
                    with self.subTest(word=word, typo=typo, operation=operation):
                        self.assertEqual(distance.compare(word, typo, 2), 1)

    def test_each_error_family_has_concrete_examples(self):
        variants = mutations("progetto")
        self.assertIn("progetot", variants["transposition"])
        self.assertIn("progtto", variants["missing_letter"])
        self.assertIn("progeetto", variants["extra_letter"])
        self.assertEqual(variants["double_letter_missing"], {"progeto"})
        self.assertIn("progettp", variants["nearby_key"])

    def test_keyboard_neighbors_are_physical_and_symmetric(self):
        self.assertTrue({"e", "t", "d", "f"}.issubset(NEIGHBORS["r"]))
        self.assertNotIn("p", NEIGHBORS["q"])
        for key, neighbors in NEIGHBORS.items():
            self.assertNotIn(key, neighbors)
            for neighbor in neighbors:
                self.assertIn(key, NEIGHBORS[neighbor])

    def test_generation_is_independent_of_dictionary_insertion_order(self):
        first = generate_suite(LEXICON, self.config)
        reordered = dict(reversed(list(LEXICON.items())))
        second = generate_suite(reordered, self.config)
        self.assertEqual(encoded(first), encoded(second))
        different = generate_suite(LEXICON, replace(self.config, seed=99))
        self.assertNotEqual(encoded(first), encoded(different))

    def test_splits_are_disjoint_by_input_and_source_with_clean_cases(self):
        suites, stats = generate_suite(LEXICON, self.config)
        inputs, sources = {}, {}
        for name, cases in suites.items():
            self.assertTrue(cases)
            inputs[name] = {c["input"] for c in cases}
            sources[name] = {c["source_word"] for c in cases}
            self.assertEqual(len(inputs[name]), len(cases))
            self.assertEqual(sources[name], {c["input"] for c in cases if c["input"] == c["expected"]})
            per_word = {}
            for case in cases:
                self.assertEqual(split_for(case["source_word"], self.config), name)
                self.assertEqual(case["expected"], case["source_word"])
                if case["input"] != case["expected"]:
                    self.assertNotIn(case["input"], LEXICON)
                    per_word[case["source_word"]] = per_word.get(case["source_word"], 0) + 1
            self.assertTrue(all(count <= self.config.typos_per_word for count in per_word.values()))
        self.assertFalse(inputs["development"] & inputs["evaluation"])
        self.assertFalse(sources["development"] & sources["evaluation"])
        self.assertEqual(sum(s["clean_cases"] for s in stats["splits"].values()), 35)

    def test_known_words_and_conflicting_labels_are_rejected(self):
        lexicon = {"carta": 100, "carto": 100, "cara": 100}
        suites, stats = generate_suite(lexicon, GenerationConfig(words=3, extra_clean_words=0, typos_per_word=20))
        typos = [c for rows in suites.values() for c in rows if c["input"] != c["expected"]]
        self.assertFalse(any(c["input"] == "cart" for c in typos))
        self.assertFalse(any(c["input"] == "cara" for c in typos))
        self.assertGreater(stats["rejected_proposals"]["multiple_sampled_sources"], 0)
        self.assertIn({"source": "carta", "variant": "cara"}, stats["rejected_examples"]["known_dictionary_word"])

    def test_protected_and_smoke_words_are_excluded_from_both_roles(self):
        excluded = {"progetto", "quadro", "quesot"}
        protected = {"telefono", "progetot"}
        suites, _ = generate_suite(LEXICON, self.config, excluded=excluded, protected=protected)
        for cases in suites.values():
            for case in cases:
                self.assertNotIn(case["input"], excluded | protected)
                self.assertNotIn(case["expected"], excluded | protected)

    def test_stratification_includes_frequency_bands(self):
        sample = stratified_sample(LEXICON, 15, 42, "test")
        self.assertEqual({LEXICON[word] for word in sample}, {2_000_000, 200_000, 20_000})
        with self.assertRaises(ValueError):
            stratified_sample(LEXICON, len(LEXICON) + 1, 42, "test")

    def test_split_assignment_stable_when_sample_size_changes(self):
        small, _ = generate_suite(LEXICON, replace(self.config, words=15, extra_clean_words=0))
        large, _ = generate_suite(LEXICON, self.config)
        assignments = {c["source_word"]: name for name, cases in large.items() for c in cases}
        for name, cases in small.items():
            for case in cases:
                self.assertEqual(assignments[case["source_word"]], name)

    def test_export_is_repeatable_hashed_and_loadable(self):
        suites, stats = generate_suite(LEXICON, self.config)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in (root / "one", root / "two"):
                manifest = write_suite(folder, suites, {"format_version": 1}, stats)
                for split, info in manifest["datasets"].items():
                    path = folder / info["file"]
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), info["sha256"])
                    cases, metadata = load_dataset(path)
                    self.assertEqual(metadata["split"], split)
                    self.assertEqual(cases, suites[split])
            for file in ("development.json", "evaluation.json", "manifest.json"):
                self.assertEqual((root / "one" / file).read_bytes(), (root / "two" / file).read_bytes())
            with self.assertRaises(ValueError):
                write_suite(root / "one", suites, {"format_version": 1}, stats)

    def test_invalid_config_and_insufficient_words_fail(self):
        for kwargs in ({"words": 0}, {"extra_clean_words": -1}, {"evaluation_percent": 100},
                       {"typos_per_word": 0}, {"min_length": 20, "max_length": 10}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GenerationConfig(**kwargs)
        with self.assertRaises(ValueError):
            generate_suite(LEXICON, GenerationConfig(words=100, extra_clean_words=0))

    def test_cli_generates_without_calling_correction_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dictionary = root / "words.txt"
            dictionary.write_text("\n".join(f"{word} {count}" for word, count in LEXICON.items()), encoding="utf-8")
            excluded = root / "smoke.json"
            excluded.write_text(json.dumps([{"input": "quesot", "expected": "questo", "category": "typo"}]))
            with (patch("autocorrect_core.generate_typos.load_personal_words", return_value=set()),
                  patch("autocorrect_core.engine.AutocorrectEngine.evaluate", side_effect=AssertionError("No predictions during generation")),
                  contextlib.redirect_stdout(io.StringIO())):
                code = main(["--dictionary", str(dictionary), "--words", "20", "--extra-clean-words", "5",
                             "--exclude-cases", str(excluded), "--output-dir", str(root / "suite")])
            self.assertEqual(code, 0)
            for split in ("development", "evaluation"):
                cases = load_cases(root / "suite" / f"{split}.json")
                self.assertFalse(any(c["expected"] == "questo" for c in cases))

    def test_generator_does_not_accept_a_silently_ignored_validator_option(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--hunspell"])
        self.assertEqual(raised.exception.code, 2)

    def test_benchmark_detail_filter_does_not_hide_error_counts(self):
        cases = [{"input": "x", "expected": "y"}, {"input": "z", "expected": "z"}]
        decisions = [Decision("x", "x", "keep", "test"), Decision("z", "q", "correct", "test")]
        detailed = quality(cases, decisions)
        compact = quality(cases, decisions, details="none")
        for key in detailed.keys() - {"errors", "abstentions"}:
            self.assertEqual(detailed[key], compact[key])
        self.assertEqual(compact["wrong_changes"], 1)
        self.assertEqual(compact["typo_abstentions"], 1)
        self.assertEqual(compact["errors"], [])


if __name__ == "__main__":
    unittest.main()
