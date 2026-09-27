import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from autocorrect_core import AutocorrectEngine
from autocorrect_core.benchmark import main as benchmark
from autocorrect_core.cli import main as cli
from autocorrect_core.hunspell import HunspellValidator, library_name


class ValidatorPolicyTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dictionary = self.root / "frequency.txt"
        self.dictionary.write_text("progetto 10000000\nquesto 10000000\n", encoding="utf-8")

    def test_validator_vetoes_a_change_without_adding_correction_targets(self):
        validator = Mock()
        validator.spell.side_effect = lambda word: word == "progetti"
        baseline = AutocorrectEngine(self.dictionary)
        engine = AutocorrectEngine(self.dictionary, word_validator=validator)
        self.assertEqual(baseline.evaluate("progetti").output, "progetto")
        result = engine.evaluate("progetti")
        self.assertEqual((result.output, result.reason), ("progetti", "valid_word"))
        self.assertEqual(result.candidates, ())
        self.assertNotIn("progetti", engine.symspell.words)
        self.assertEqual(engine.evaluate("quesot").output, "questo")

    def test_sensitive_and_structured_inputs_do_not_reach_validator(self):
        validator = Mock()
        engine = AutocorrectEngine(self.dictionary, word_validator=validator,
                                   protected_words={"mybrand"})
        for context in ("password", "terminal", "code", "url", "email"):
            self.assertEqual(engine.evaluate("quesot", context=context).reason, "disabled_context")
        for token in ("", "x" * 1000, "mybrand", "progetto", "l’acqua", "user@host", "a\0b", "abc42"):
            self.assertEqual(engine.evaluate(token).output, token)
        validator.spell.assert_not_called()

    def test_validator_receives_normalized_word_but_keeps_original(self):
        validator = Mock()
        validator.spell.return_value = True
        engine = AutocorrectEngine(self.dictionary, word_validator=validator)
        original = "Caffe\u0300"
        self.assertEqual(engine.evaluate(original).output, original)
        validator.spell.assert_called_once_with("caffè")

    def test_missing_library_is_an_explicit_error(self):
        with patch("autocorrect_core.hunspell.find_library", return_value=None):
            with self.assertRaisesRegex(ValueError, "Libreria Hunspell non trovata"):
                library_name()

    def test_requested_missing_dictionary_does_not_silently_disable_filter(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli(["quesot", "--dictionary", str(self.dictionary),
                 "--hunspell-dictionary", str(self.root / "missing")])
        self.assertEqual(raised.exception.code, 2)


class NativeHunspellTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            library_name()
        except ValueError as error:
            raise unittest.SkipTest(str(error))

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.prefix = self.root / "mini.v1"
        self.write_dictionary("UTF-8", "utf-8")

    def write_dictionary(self, declared, encoding):
        Path(str(self.prefix) + ".aff").write_text(
            f"SET {declared}\nSFX A Y 1\nSFX A o i o\n", encoding=encoding)
        Path(str(self.prefix) + ".dic").write_text("2\nprogetto/A\ncaffè\n", encoding=encoding)

    def test_real_affix_rules_and_encoding(self):
        for declared, encoding in (("UTF-8", "utf-8"), ("ISO8859-1", "iso8859-1")):
            with self.subTest(encoding=encoding):
                self.write_dictionary(declared, encoding)
                with HunspellValidator(self.prefix) as validator:
                    for word in ("progetto", "progetti", "caffè"):
                        self.assertTrue(validator.spell(word), word)
                    for word in ("progeti", "caffe", "", "progetto\0garbage", "漢字"):
                        self.assertFalse(validator.spell(word), word)
                    self.assertEqual(len(validator.metadata["aff_sha256"]), 64)
                validator.close()  # Idempotent; never call native code after destruction.
                with self.assertRaisesRegex(ValueError, "chiuso"):
                    validator.spell("progetto")

    def test_cli_and_benchmark_with_real_morphology(self):
        frequency = self.root / "frequency.txt"
        frequency.write_text("progetto 10000000\nquesto 10000000\n", encoding="utf-8")
        options = ["--dictionary", str(frequency), "--hunspell-dictionary", str(self.prefix)]
        output = io.StringIO()
        with (patch("autocorrect_core.cli.default_personal_words", return_value=self.root / "absent"),
              contextlib.redirect_stdout(output)):
            self.assertEqual(cli(["progetti", "quesot", "--json", *options]), 0)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row["output"] for row in rows], ["progetti", "questo"])
        dataset = self.root / "cases.json"
        dataset.write_text(json.dumps([
            {"input": "progetti", "expected": "progetti", "category": "valid"},
            {"input": "quesot", "expected": "questo", "category": "typo"},
            {"input": "questo", "expected": "questo", "category": "known"},
        ]))
        report = self.root / "report.json"
        with (patch("autocorrect_core.cli.default_personal_words", return_value=self.root / "absent"),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(benchmark([str(dataset), "--iterations", "1", "--output", str(report), *options]), 0)
        payload = json.loads(report.read_text())
        self.assertEqual(payload["word_validator"]["backend"], "hunspell")
        self.assertEqual(payload["quality"]["wrong_changes"], 0)
        self.assertEqual(payload["quality"]["correct_changes"], 1)
        self.assertEqual(payload["by_lexicon_membership"]["unknown"]["cases"], 2)

    def test_invalid_dictionary_headers_are_rejected(self):
        Path(str(self.prefix) + ".aff").write_text("# no SET\n")
        with self.assertRaisesRegex(ValueError, "SET"):
            HunspellValidator(self.prefix)
        self.write_dictionary("UTF-8", "utf-8")
        Path(str(self.prefix) + ".dic").write_text("")
        with self.assertRaisesRegex(ValueError, "intestazione"):
            HunspellValidator(self.prefix)


if __name__ == "__main__":
    unittest.main()
