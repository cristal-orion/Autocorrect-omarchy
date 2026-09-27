from pathlib import Path
import tempfile
import unittest

from autocorrect_core.engine import AutocorrectEngine
from autocorrect_core.policy_sweep import recognition, sweep


class Validator:
    def spell(self, word):
        return word == "maglioneri"


class PolicySweepTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "words.txt"
        path.write_text("maglione 44882\nmagione 31130\nbanco 10000\nbando 9000\n")
        self.engine = AutocorrectEngine(path, word_validator=Validator())

    def test_lower_frequency_releases_only_eligible_unknowns_and_restores_policy(self):
        original = self.engine.policy
        cases = [{"input": word, "expected": expected, "category": "fixture"} for word, expected in (
            ("maglioner", "maglione"), ("maglione", "maglione"),
            ("maglioneri", "maglioneri"), ("banso", "banso"), ("Maglioner", "Maglioner"))]
        rows = sweep(self.engine, {"test": cases}, probes=["maglioner", "banso"])
        self.assertEqual(rows[0]["probes"]["maglioner"]["reason"], "low_frequency")
        self.assertEqual(rows[1]["probes"]["maglioner"]["output"], "maglione")
        # Lower frequency must not bypass the subsequent ambiguity gate.
        self.assertEqual(rows[2]["probes"]["banso"]["reason"], "ambiguous")
        self.assertEqual(rows[3]["datasets"]["test"]["additional_vs_baseline"]["correct"], 1)
        self.assertEqual(rows[3]["datasets"]["test"]["quality"]["false_changes_on_keep_cases"], 0)
        self.assertIs(self.engine.policy, original)
        self.assertEqual(recognition(self.engine, "maglioneri"), "hunspell_only")

    def test_unknown_valid_words_count_as_false_changes(self):
        cases = [{"input": "maglioner", "expected": "maglioner", "category": "keep_fixture"}]
        rows = sweep(self.engine, {"test": cases})
        group = rows[1]["datasets"]["test"]["by_recognition"]["unknown_to_both"]
        self.assertEqual(group["false_changes_on_keep_cases"], 1)

    def test_invalid_sweep_is_rejected(self):
        for frequencies in ((), (1000, 100000), (100000, 0), (1000, 1000)):
            with self.assertRaises(ValueError):
                sweep(self.engine, {}, frequencies=frequencies)
        self.engine.word_validator = None
        with self.assertRaises(ValueError):
            sweep(self.engine, {})
