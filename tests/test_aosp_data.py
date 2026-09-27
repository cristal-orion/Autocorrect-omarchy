import contextlib
import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autocorrect_core.aosp_data import import_wordlist, parse_combined, write_once
from autocorrect_core.data_ablation import load_context_cases, run_ablation
from autocorrect_core.engine import AutocorrectEngine
from autocorrect_core.interactive import run
from autocorrect_core.cli import main as cli


SAMPLE = """dictionary=main:it,locale=it,version=18
 word=buona,f=170
  bigram=sera,f=1
  bigram=notte,f=2
 word=sera,f=120
 word=notte,f=140
 word=Caffè,f=80
  bigram=sera,f=3
 word=caffè,f=100
  bigram=sera,f=1
 word=l’acqua,f=90
 word=non-parola,f=10
  bigram=sera,f=1
 word=falsa,f=10,not_a_word=true
 word=segreta,f=10,possibly_offensive=true
"""


class AospDataTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_scores_ranks_normalization_and_filtering(self):
        data = parse_combined(SAMPLE.encode())
        self.assertEqual(data.scores["caffè"], 100)
        self.assertEqual(data.bigrams["caffè", "sera"], 1)
        self.assertIn("l'acqua", data.scores)
        self.assertNotIn("non-parola", data.scores)
        self.assertNotIn("falsa", data.scores)
        self.assertNotIn("segreta", data.scores)
        self.assertEqual(data.metadata["statistics"]["normalization_collisions"], 1)
        unigram = data.model(with_bigrams=False)
        full = data.model()
        self.assertEqual(unigram.rows[()], full.rows[()])
        self.assertEqual(full.rows[("buona",)]["sera"], 1)
        self.assertEqual(full.rows[("buona",)]["notte"], .5)
        self.assertGreater(full.probability("sera", ("una", "buona")), full.probability("notte", ("una", "buona")))
        self.assertGreater(unigram.probability("notte", ("una", "buona")), unigram.probability("sera", ("una", "buona")))
        self.assertFalse(unigram.has_context(("una", "buona")))

    def test_malformed_or_unsupported_data_is_rejected(self):
        for text in ("", "word=ciao,f=3", SAMPLE + "word=buona,f=100\n",
                     SAMPLE.replace("f=170", "f=256"), SAMPLE.replace("f=170", "f=-1"),
                     SAMPLE.replace("bigram=sera,f=1", "bigram=sera,f=4", 1),
                     SAMPLE.replace("word=buona,f=170", "word=buona,f=170,f=100"),
                     SAMPLE.replace("locale=it", "locale=en"), SAMPLE + "shortcut=ciao,f=1\n",
                     SAMPLE + "dictionary=main:it,locale=it\n"):
            with self.subTest(text=text[-80:]), self.assertRaises(ValueError):
                parse_combined(text.encode())

    def test_import_is_pinned_and_does_not_replace_unrelated_files(self):
        source = self.root / "source"
        source.write_text(SAMPLE)
        destination = self.root / "imported"
        with self.assertRaisesRegex(ValueError, "checksum"):
            import_wordlist(destination, source)
        self.assertFalse(destination.exists())
        write_once(source, SAMPLE.encode())
        with self.assertRaisesRegex(ValueError, "esistente"):
            write_once(source, b"different")
        self.assertEqual(source.read_text(), SAMPLE)

    def test_verified_import_is_repeatable_offline_and_detects_cache_corruption(self):
        source = self.root / "source"
        source.write_text(SAMPLE)
        destination = self.root / "imported"
        with patch("autocorrect_core.aosp_data.SHA256", hashlib.sha256(SAMPLE.encode()).hexdigest()):
            first = import_wordlist(destination, source)
            with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
                self.assertEqual(import_wordlist(destination), first)
            self.assertEqual((destination / "main_it.combined").read_text(), SAMPLE)
            self.assertEqual(first["lexicon_scores_sha256"], hashlib.sha256((destination / "lexicon-scores.txt").read_bytes()).hexdigest())
            (destination / "main_it.combined").write_text("damaged")
            with self.assertRaisesRegex(ValueError, "checksum"):
                import_wordlist(destination)

    def test_small_ablation_isolates_data_and_does_not_learn(self):
        source = self.root / "aosp.combined"
        source.write_text(SAMPLE)
        dictionary = self.root / "baseline.txt"
        dictionary.write_text("buona 1000000\nsera 100000\nnotte 200000\n")
        dataset = self.root / "cases.json"
        dataset.write_text(json.dumps([{"input": "buoan", "expected": "buona", "category": "typo"},
                                       {"input": "buona", "expected": "buona", "category": "keep"}]))
        context = self.root / "context.json"
        context.write_text(json.dumps({"metadata": {"scope": "test"}, "cases": [
            {"previous": "una buona ", "input": "", "expected": "sera", "task": "next_word"}]}))
        with contextlib.redirect_stdout(io.StringIO()):
            report = run_ablation(dataset, source, dictionary, self.root / "output", context_dataset=context)
        arms = report["token_arms"]
        self.assertEqual(arms["baseline"]["quality"]["correct_changes"], 1)
        self.assertEqual(arms["compressed_scores_control"]["quality"]["automatic_changes"], 0)
        self.assertEqual(arms["baseline"]["policy"], arms["compressed_scores_control"]["policy"])
        suggestions = report["suggestion_arms"]
        self.assertNotEqual(suggestions["baseline_aosp_unigrams"]["cases"][0]["target_rank"], 1)
        self.assertEqual(suggestions["baseline_aosp_bigrams"]["cases"][0]["target_rank"], 1)
        with (contextlib.redirect_stdout(io.StringIO()),
              patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True),
              patch("autocorrect_core.interactive.PersonalMemory") as memory,
              patch("autocorrect_core.interactive.run_session", return_value=0) as session):
            run(AutocorrectEngine(dictionary), aosp_wordlist=source, learn=False)
        memory.assert_not_called()
        self.assertEqual(session.call_args.args[0].base_label, "aosp-pesi")

    def test_context_dataset_validation_and_cli_modes(self):
        path = self.root / "context.json"
        for case in ({"previous": "ciao", "input": "", "expected": "amico", "task": "next_word"},
                     {"previous": "ciao ", "input": "am", "expected": "amico", "task": "next_word"}):
            path.write_text(json.dumps({"metadata": {}, "cases": [case]}))
            with self.assertRaises(ValueError):
                load_context_cases(path)
        for args in (["--aosp-wordlist", "unused", "quesot"],
                     ["--interactive", "--corpus", "unused", "--aosp-wordlist", "unused"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                cli(args)
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
