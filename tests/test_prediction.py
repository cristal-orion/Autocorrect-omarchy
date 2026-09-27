import contextlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from autocorrect_core import AutocorrectEngine
from autocorrect_core.cli import main as cli
from autocorrect_core.interactive import load_base, run, run_session
from autocorrect_core.personal import PersonalMemory
from autocorrect_core.prediction import (
    ContextPredictor, END, NgramModel, START, apply_suggestion, history_for,
    sentences_from,
)


WORDS = """ci 10000000
vediamo 1000000
domani 1000000
dopo 1000000
mattina 1000000
sera 1000000
carlo 10000000
caglio 1000
questo 10000000
progetto 10000000
"""
BASE = "ci vediamo domani mattina\nci vediamo domani sera\nho comprato il caglio\nho parlato con carlo\n"


class PredictionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dictionary = self.root / "frequency.txt"
        self.dictionary.write_text(WORDS, encoding="utf-8")
        self.engine = AutocorrectEngine(self.dictionary)
        self.base = NgramModel()
        self.base.learn(BASE)
        self.predictor = ContextPredictor(self.engine, self.base)

    def words(self, text, predictor=None):
        return [item.word for item in (predictor or self.predictor).suggest(text).items]

    def test_next_word_completion_and_sentence_end(self):
        self.assertEqual(self.words("ci vediamo ")[0], "domani")
        self.assertEqual(self.words("ci vediamo do")[0], "domani")
        self.assertEqual(self.words("ci vediamo domani ")[:2], ["mattina", "sera"])
        self.assertEqual(self.words("ci vediamo domani mattina ")[0], ".")
        self.assertNotIn(".", self.words(""))
        self.assertEqual(self.words("Ci vediamo Do")[0], "Domani")

    def test_context_reranks_a_typo_without_mutating_the_core(self):
        self.assertEqual(self.engine.evaluate("caglo").output, "carlo")
        result = self.predictor.suggest("ho comprato il caglo")
        self.assertEqual(result.items[0].word, "caglio")
        self.assertEqual(result.items[0].kind, "correzione")
        self.assertEqual(result.items[0].order, 3)
        self.assertEqual(self.engine.evaluate("caglo").output, "carlo")

    def test_apply_and_continue_with_three_suggestions(self):
        text = "ci vediamo "
        for expected in ("ci vediamo domani ", "ci vediamo domani mattina ", "ci vediamo domani mattina. "):
            text, cursor = apply_suggestion(text, self.predictor.suggest(text), 0)
            self.assertEqual(text, expected)
            self.assertEqual(cursor, len(text))
        self.assertEqual(self.words(text), self.words(""))

    def test_cursor_edits_preserve_text_to_the_right(self):
        text = "ci vediamo do più tardi"
        result = self.predictor.suggest(text, len("ci vediamo do"))
        updated, cursor = apply_suggestion(text, result, 0)
        self.assertEqual(updated, "ci vediamo domani più tardi")
        self.assertEqual(updated[:cursor], "ci vediamo domani ")
        self.assertEqual(self.predictor.suggest("domani", 3).items, ())
        with self.assertRaises(ValueError):
            self.predictor.suggest("abc", 99)

    def test_structured_and_oversize_prefixes_are_not_corrected(self):
        for text in ("user@quesot", "/tmp/quesot", "quesot42", "quesot_foo", "x" * 65):
            self.assertEqual(self.predictor.suggest(text).items, (), text)
        self.assertEqual(self.predictor.suggest("a " * 9000).items, ())

    def test_sentence_boundaries_unicode_and_structured_tokens(self):
        self.assertEqual(sentences_from("Caffe\u0300 e l’acqua. Ci vediamo!"),
                         [["caffè", "e", "l'acqua"], ["ci", "vediamo"]])
        self.assertEqual(sentences_from("prima https://example.com dopo\npoi"),
                         [["prima"], ["dopo"], ["poi"]])
        model = NgramModel()
        model.learn("ci vediamo. domani mattina")
        self.assertNotIn("domani", model.rows[("ci", "vediamo")])
        self.assertEqual(model.rows[("ci", "vediamo")][END], 1)
        self.assertEqual(model.rows[(START, START)]["domani"], 1)

    def test_personal_learning_changes_ranking_and_survives_restart(self):
        path = self.root / "memory.sqlite3"
        with PersonalMemory(path) as memory:
            predictor = ContextPredictor(self.engine, self.base, memory.model)
            self.assertEqual(self.words("ci vediamo ", predictor)[0], "domani")
            self.assertEqual(memory.learn("ci vediamo venerdì pomeriggio"), 1)
            self.assertEqual(self.words("ci vediamo ", predictor)[0], "venerdì")
            self.assertEqual(predictor.suggest("ci vediamo ").items[0].source, "personale")
            memory.learn("ci vediamo venerdì pomeriggio")
            self.assertEqual(memory.sentence_count, 2)
        with PersonalMemory(path) as memory:
            predictor = ContextPredictor(self.engine, self.base, memory.model)
            self.assertEqual(self.words("ci vediamo ", predictor)[0], "venerdì")
            self.assertEqual(memory.model.rows[("ci", "vediamo")]["venerdì"], 2)
            self.assertEqual(memory.sentence_count, 2)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_suggestions_and_selection_do_not_train(self):
        with PersonalMemory(self.root / "memory.sqlite3") as memory:
            predictor = ContextPredictor(self.engine, self.base, memory.model)
            result = predictor.suggest("ci vediamo ")
            apply_suggestion("ci vediamo ", result, 0)
            self.assertEqual(memory.sentence_count, 0)
            self.assertEqual(memory.model.rows, {})

    def test_failed_transaction_does_not_update_in_memory_model(self):
        memory = PersonalMemory(self.root / "memory.sqlite3")
        memory.connection.execute("CREATE TRIGGER reject_learning BEFORE INSERT ON ngrams BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            memory.learn("ci vediamo")
        self.assertEqual(memory.sentence_count, 0)
        self.assertEqual(memory.model.rows, {})
        self.assertEqual(memory.connection.execute("SELECT count(*) FROM ngrams").fetchone()[0], 0)
        memory.close()

    def test_corpus_replaces_demo_and_empty_corpus_is_rejected(self):
        path = self.root / "corpus.txt"
        path.write_text("# commento\npartiamo lunedì mattina\n", encoding="utf-8")
        model, label, count = load_base([path])
        self.assertEqual((label, count), ("corpus", 1))
        self.assertNotIn("vediamo", model.rows[()])
        path.write_text("# commento\n")
        with self.assertRaises(ValueError):
            load_base([path])

    def test_native_terminal_session_selects_and_learns_only_confirmation(self):
        with PersonalMemory(self.root / "memory.sqlite3") as memory:
            predictor = ContextPredictor(self.engine, self.base, memory.model)
            with create_pipe_input() as pipe, contextlib.redirect_stdout(io.StringIO()):
                # Tab selects next word; Ctrl+Z undoes it. Confirm a different word.
                # Ctrl+C abandons the next line; commands must not be learned.
                pipe.send_text("ci vediamo \t\x1avenerdì\nscartami\x03/stats\n/exit\n")
                self.assertEqual(run_session(predictor, memory, input=pipe, output=DummyOutput()), 0)
            self.assertEqual(memory.sentence_count, 1)
            self.assertEqual(memory.model.rows[("ci", "vediamo")]["venerdì"], 1)
            self.assertNotIn("domani", memory.model.rows[()])
            self.assertNotIn("scartami", memory.model.rows[()])
            self.assertNotIn("stats", memory.model.rows[()])

    def test_no_learning_mode_does_not_open_a_memory(self):
        with (contextlib.redirect_stdout(io.StringIO()),
              patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True),
              patch("autocorrect_core.interactive.PersonalMemory") as memory,
              patch("autocorrect_core.interactive.run_session", return_value=0) as session):
            self.assertEqual(run(self.engine, memory_path=self.root / "absent", learn=False), 0)
        memory.assert_not_called()
        self.assertIsNone(session.call_args.args[1])

    def test_cli_rejects_incompatible_modes(self):
        for args in (["--interactive", "quesot"], ["--interactive", "--json"],
                     ["--interactive", "--context", "password"], ["--no-learn", "quesot"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                cli(args)
            self.assertEqual(raised.exception.code, 2)

    def test_non_terminal_run_fails_before_creating_memory(self):
        with patch("sys.stdin.isatty", return_value=False), self.assertRaisesRegex(ValueError, "terminale"):
            run(self.engine, memory_path=self.root / "not-created")
        self.assertFalse((self.root / "not-created").exists())


if __name__ == "__main__":
    unittest.main()
