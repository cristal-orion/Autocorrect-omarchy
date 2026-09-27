from pathlib import Path
import json
import tempfile
import unittest

from autocorrect_core import AutocorrectEngine
from autocorrect_core.vocabulary_audit import compare, read_labels, vocabulary_entries


class Validator:
    metadata = {"backend": "fixture"}

    def spell(self, word):
        return word == "progetti"


class VocabularyAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        dictionary = self.root / "words.txt"
        dictionary.write_text("progetto 10000000\nquesto 10000000\n")
        self.baseline = AutocorrectEngine(dictionary)
        self.filtered = AutocorrectEngine(dictionary, word_validator=Validator())

    def test_read_export_keeps_hash_and_structured_entries_without_inventing_frequencies(self):
        self.assertEqual(vocabulary_entries("# Titolo\n# \n#\nprogetti\nprogetti\n123\nabc def\n"),
                         ["#", "progetti", "123", "abc def"])

    def test_recognition_is_not_ground_truth_and_vocabulary_is_not_protected(self):
        summary, rows = compare(["progetti", "quesot", "questo"], self.baseline, self.filtered)
        metrics = summary["unknown_normalized_lexical_entries"]
        self.assertEqual(metrics["baseline_changes"], 2)
        self.assertEqual(metrics["hunspell_changes"], 1)
        self.assertEqual(metrics["reviewed_valid_cases"], 0)
        self.assertIsNone(metrics["baseline_false_changes_on_reviewed_valid"])
        self.assertNotIn("progetti", self.baseline.protected)
        self.assertTrue(all(row["label"] == "unreviewed" for row in rows))

    def test_only_reviewed_valid_inputs_define_false_changes(self):
        summary, _ = compare(["progetti", "quesot"], self.baseline, self.filtered,
                             {"progetti": "valid", "quesot": "typo"})
        metrics = summary["unknown_normalized_lexical_entries"]
        self.assertEqual(metrics["reviewed_valid_cases"], 1)
        self.assertEqual(metrics["baseline_false_changes_on_reviewed_valid"], 1)
        self.assertEqual(metrics["hunspell_false_changes_on_reviewed_valid"], 0)

    def test_original_case_and_normalized_results_are_distinct(self):
        summary, rows = compare(["Quesot", "QUESOT"], self.baseline, self.filtered)
        self.assertEqual(summary["raw_entries"]["baseline_changes"], 0)
        self.assertEqual(summary["unknown_normalized_lexical_entries"]["baseline_changes"], 1)
        self.assertEqual(rows[0]["variants"], ["Quesot", "QUESOT"])

    def test_unknown_duplicate_or_automatic_labels_are_rejected(self):
        path = self.root / "labels.json"
        for rows in ([{"input": "absent", "label": "valid"}],
                     [{"input": "progetti", "label": "hunspell"}],
                     [{"input": "progetti", "label": "valid"}] * 2):
            path.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                read_labels(path, {"progetti"})


if __name__ == "__main__":
    unittest.main()
