import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autocorrect_core import AutocorrectEngine, Decision, Policy
from autocorrect_core.benchmark import load_cases, quality
from autocorrect_core.cli import main as cli
from autocorrect_core.dictionary import fetch_dictionary


# Deliberately small and unambiguous fixtures, independent of the downloaded
# corpus. Quality against real Italian is measured by the separate benchmark.
WORDS = """questo 10000000
questa 10000
progetto 2000000
domani 1500000
quando 3000000
interessante 4000000
banco 1000000
bando 950000
casa 2000000
zucchero 500
acqua 1000000
altro 1000000
amica 1000000
caffè 1000000
perché 2000000
e 100000000
è 10000000
"""


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dictionary = self.root / "words.txt"
        self.dictionary.write_text(WORDS, encoding="utf-8")
        self.engine = AutocorrectEngine(self.dictionary)

    def test_transposition_is_one_edit_and_can_autocorrect(self):
        result = self.engine.evaluate("quesot")
        self.assertEqual(result.output, "questo")
        self.assertEqual(result.candidates[0].distance, 1)
        self.assertIsNone(result.confidence)

    def test_missing_and_extra_letter(self):
        for typo in ("progeto", "progettoo"):
            with self.subTest(typo=typo):
                self.assertEqual(self.engine.evaluate(typo).output, "progetto")

    def test_two_edits_are_suggestions_only_by_default(self):
        result = self.engine.evaluate("proggeto")
        self.assertEqual(result.output, "proggeto")
        self.assertEqual(result.reason, "edit_distance")
        self.assertEqual(result.candidates[0].term, "progetto")

    def test_competing_candidates_cause_abstention_even_with_limit_one(self):
        result = self.engine.evaluate("banso", limit=1)
        self.assertEqual(result.reason, "ambiguous")
        self.assertEqual(result.output, "banso")
        self.assertGreaterEqual(result.candidate_count, 2)
        self.assertEqual(len(result.candidates), 1)

    def test_valid_word_is_never_replaced_by_more_frequent_neighbor(self):
        for word in ("questa", "è", "e", "bando"):
            self.assertEqual(self.engine.evaluate(word).output, word)
            self.assertEqual(self.engine.evaluate(word).reason, "known_word")

    def test_personal_words_are_protected_but_not_added_as_targets(self):
        engine = AutocorrectEngine(self.dictionary, protected_words=["quesot", "mybrand"])
        self.assertEqual(engine.evaluate("quesot").reason, "protected_word")
        self.assertNotIn("mybrand", engine.symspell.words)

    def test_protected_candidate_does_not_inflate_other_candidates_margin(self):
        engine = AutocorrectEngine(self.dictionary, protected_words=["banco"])
        self.assertEqual(engine.evaluate("banso").reason, "protected_candidate")
        self.assertEqual(engine.evaluate("banso").output, "banso")

    def test_case_is_preserved_without_automatic_name_correction(self):
        for word in ("Quesot", "QUESOT", "queSot"):
            result = self.engine.evaluate(word)
            self.assertEqual(result.output, word)
            self.assertEqual(result.reason, "capitalized_or_mixed_case")

    def test_normalization_does_not_change_preserved_original(self):
        original = "caffe\u0300"
        result = self.engine.evaluate(original)
        self.assertEqual(result.reason, "known_word")
        self.assertEqual(result.output, original)

    def test_existing_and_missing_apostrophes_are_preserved(self):
        for token in ("l’acqua", "l'acqua", "lacqua", "laltro", "unamica", "un amico"):
            self.assertEqual(self.engine.evaluate(token).output, token)

    def test_disabled_contexts_always_preserve_input(self):
        for context in ("password", "terminal", "code", "url", "email"):
            result = self.engine.evaluate("quesot", context=context)
            self.assertEqual(result.reason, "disabled_context")
            self.assertEqual(result.output, "quesot")

    def test_structured_tokens_not_split_into_correctable_parts(self):
        for token in ("a@quesot.it", "https://quesot.it", "/tmp/quesot", "quesot_foo", "quesot42", "🙂", "привет", "quesot!"):
            self.assertEqual(self.engine.evaluate(token).output, token)

    def test_length_and_frequency_guards(self):
        self.assertEqual(self.engine.evaluate("csa").reason, "short_word")
        self.assertEqual(self.engine.evaluate("zucchreo").reason, "low_frequency")
        self.assertEqual(self.engine.evaluate("x" * 10000).reason, "too_long")
        self.assertEqual(self.engine.evaluate("").reason, "empty")

    def test_malformed_dictionary_is_rejected(self):
        for contents in ("", "questo nonsense", "questo -1", "questo 0", "questo 1 trailing"):
            self.dictionary.write_text(contents)
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                AutocorrectEngine(self.dictionary)

    def test_invalid_policy_context_and_limit(self):
        for kwargs in ({"min_score_margin": float("nan")}, {"max_auto_distance": 3}, {"min_auto_length": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Policy(**kwargs)
        with self.assertRaises(ValueError):
            self.engine.evaluate("quesot", context="unknown")
        with self.assertRaises(ValueError):
            self.engine.evaluate("quesot", limit=0)

    def test_cli_json_and_streaming(self):
        output = io.StringIO()
        with (patch("sys.stdin", io.StringIO("quesot\nprogetto\n")),
              patch("autocorrect_core.cli.default_personal_words", return_value=self.root / "absent"),
              contextlib.redirect_stdout(output)):
            code = cli(["--stdin", "--json", "--dictionary", str(self.dictionary)])
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([row["output"] for row in rows], ["questo", "progetto"])
        self.assertIsNone(rows[0]["confidence"])

    def test_explicit_missing_personal_file_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli(["quesot", "--dictionary", str(self.dictionary),
                 "--protected-words", str(self.root / "missing")])
        self.assertEqual(raised.exception.code, 2)

    def test_existing_changed_download_is_not_overwritten(self):
        self.dictionary.write_text("local changes")
        with patch("urllib.request.urlopen") as network, self.assertRaises(ValueError):
            fetch_dictionary(self.dictionary)
        network.assert_not_called()
        self.assertEqual(self.dictionary.read_text(), "local changes")

    def test_bad_download_never_publishes_destination(self):
        target = self.root / "download/it.txt"
        with patch("urllib.request.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = b"wrong data"
            with self.assertRaises(ValueError):
                fetch_dictionary(target)
        self.assertFalse(target.exists())

    def test_benchmark_counts_harmful_changes_in_precision(self):
        cases = [
            {"input": "quesot", "expected": "questo"},
            {"input": "banso", "expected": "banco"},
            {"input": "brand", "expected": "brand"},
            {"input": "progetto", "expected": "progetto"},
        ]
        decisions = [
            Decision("quesot", "questo", "correct", "test"),
            Decision("banso", "banso", "keep", "test"),
            Decision("brand", "bando", "correct", "test"),
            Decision("progetto", "progetto", "keep", "test"),
        ]
        metrics = quality(cases, decisions)
        self.assertEqual(metrics["autocorrect_precision"], 0.5)
        self.assertEqual(metrics["typo_recall"], 0.5)
        self.assertEqual(metrics["false_changes_on_keep_cases"], 1)
        self.assertEqual(metrics["keep_preservation"], 0.5)
        self.assertEqual(len(metrics["abstentions"]), 1)
        self.assertIsNone(quality([], [])["autocorrect_precision"])

    def test_benchmark_rejects_duplicate_cases(self):
        path = self.root / "cases.json"
        case = {"input": "x", "expected": "x", "category": "keep"}
        path.write_text(json.dumps([case, case]))
        with self.assertRaises(ValueError):
            load_cases(path)


if __name__ == "__main__":
    unittest.main()
