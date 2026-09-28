from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from autocorrect_core.engine import AutocorrectEngine, CONTEXTS, Policy
from autocorrect_core.feedback import FeedbackLearner, FeedbackMemory
from autocorrect_core.probe_server import handle_request, refresh_policy


class Validator:
    metadata = {"source": "test fixture"}

    def spell(self, word):
        return word == "compilaste"


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dictionary = self.root / "words.txt"
        dictionary.write_text("pane 1000000\npene 900000\ncane 1000000\nmaglione 44882\nquesto 10000000\nquesta 10000\n")
        self.engine = AutocorrectEngine(dictionary, word_validator=Validator(), policy=Policy(min_frequency=5000))
        self.path = self.root / "feedback.sqlite3"
        self.memory = FeedbackMemory(self.path)
        self.addCleanup(lambda: self.memory.close())
        self.learner = FeedbackLearner(self.engine, self.memory)
        self.serial = 0

    def event(self, original="pne", target="pane", kind="manual", **extra):
        self.serial += 1
        return {"op": "feedback", "id": f"test-{self.serial}", "kind": kind,
                "original": original, "target": target, "previous": "con il ", **extra}

    def query(self, token="pne", previous="vorrei del ", **extra):
        return handle_request(self.engine, json.dumps({"token": token, "previous": previous, **extra}).encode(), learner=self.learner)

    def restart(self):
        self.memory.close()
        self.memory = FeedbackMemory(self.path)
        self.learner = FeedbackLearner(self.engine, self.memory)

    def test_explicit_edit_transfers_across_phrases_and_restart(self):
        self.assertEqual(self.query()["output"], "pne")
        result = self.learner.feedback(self.event())
        self.assertEqual(result["status"], "learned_pair")
        for previous in ("con il ", "oggi compro ", "", "ho mangiato del prosciutto nel "):
            self.assertEqual(self.query(previous=previous)["output"], "pane")
        self.restart()
        self.assertEqual(self.query(previous="una frase nuova ")["reason"], "personal_correction")
        self.assertEqual(self.memory.pairs("pne")["pane"]["confirmations"], 1)

    def test_valid_word_change_records_context_only(self):
        result = self.learner.feedback(self.event("cane", "pane"))
        self.assertEqual(result["status"], "learned_use")
        self.assertEqual(self.memory.pairs("cane"), {})
        self.assertEqual(self.memory.uses(("con", "il"))["pane"], 1)
        self.assertEqual(self.query("cane", "con il ")["output"], "cane")
        self.assertEqual(self.query("pne", "con il ")["output"], "pne")
        self.assertEqual(self.query("pne", "con il ")["candidates"][0]["term"], "pane")
        self.assertEqual(self.query("pne", "con il ")["personal"]["context_uses"], 1)

    def test_validator_and_protected_words_are_not_typo_sources(self):
        self.assertEqual(self.learner.feedback(self.event("compilaste", "pane"))["status"], "learned_use")
        self.engine.protected.add("pne")
        self.assertEqual(self.learner.feedback(self.event())["status"], "learned_use")
        self.assertEqual(self.memory.pairs("pne"), {})
        self.assertEqual(self.query()["output"], "pne")

    def test_automatic_edits_and_predictions_do_not_reinforce(self):
        self.learner.feedback(self.event())
        before = self.memory.status()
        for _ in range(10):
            self.assertEqual(self.query()["output"], "pane")
            self.assertEqual(self.learner.feedback(self.event(kind="automatic"))["status"], "ignored_automatic")
        self.assertEqual(self.memory.status(), before)

    def test_reject_vetoes_a_learned_pair_and_survives_restart(self):
        self.learner.feedback(self.event())
        self.learner.feedback(self.event(kind="reject"))
        self.assertEqual(self.query()["output"], "pne")
        self.restart()
        self.assertEqual(self.query()["output"], "pne")
        # Also veto a base autocorrection, not just a personal one.
        self.assertEqual(self.query("quesot")["output"], "questo")
        self.learner.feedback(self.event("quesot", "questo", kind="reject"))
        self.assertEqual(self.query("quesot")["reason"], "personal_rejected")

    def test_undo_selection_reverses_its_positive_use(self):
        selection = self.event(kind="selection")
        self.learner.feedback(selection)
        self.learner.feedback(self.event(kind="reject", undo_of=selection["id"]))
        self.assertEqual(self.memory.uses(("con", "il")), {})
        self.assertEqual(self.memory.pairs("pne")["pane"], {"confirmations": 0, "rejections": 1, "net": -2})
        self.assertEqual(self.learner.feedback(self.event(kind="reject", undo_of=selection["id"]))["status"], "ignored_already_undone")
        self.assertEqual(self.memory.pairs("pne")["pane"]["rejections"], 1)

    def test_conflicting_confirmations_abstain(self):
        self.learner.feedback(self.event())
        self.learner.feedback(self.event(target="pene"))
        self.assertEqual(self.query()["reason"], "personal_ambiguous")
        self.learner.feedback(self.event(target="pene"))
        self.assertEqual(self.query()["output"], "pene")

    def test_excluded_contexts_neither_apply_nor_record_feedback(self):
        self.learner.feedback(self.event())
        before = self.memory.status()
        for context in CONTEXTS:
            if context == "text":
                continue
            with self.subTest(context=context):
                self.assertEqual(self.query(context=context)["output"], "pne")
                self.assertFalse(self.query(context=context)["suggestions_enabled"])
                self.assertEqual(self.learner.feedback(self.event(context=context))["status"], "ignored_context")
        self.assertEqual(self.memory.status(), before)

    def test_forget_removes_all_contributions_after_restart_and_replay(self):
        event = self.event()
        self.learner.feedback(event)
        self.assertEqual(self.query()["output"], "pane")
        self.assertEqual(self.memory.forget("pne"), 1)
        self.restart()
        self.assertEqual(self.query()["output"], "pne")
        self.assertEqual(self.memory.pairs("pne"), {})
        self.assertEqual(self.memory.uses(("con", "il")), {})
        self.assertEqual(self.learner.feedback(event)["status"], "duplicate")
        self.assertEqual(self.memory.pairs("pne"), {})
        self.assertEqual(self.learner.feedback(self.event(kind="reject", undo_of=event["id"]))["status"], "ignored_missing_event")

    def test_duplicate_is_idempotent_and_collision_does_not_modify_counts(self):
        event = self.event()
        self.learner.feedback(event)
        self.learner.feedback(event)
        self.assertEqual(self.memory.pairs("pne")["pane"]["confirmations"], 1)
        with self.assertRaises(ValueError):
            self.learner.feedback({**event, "target": "pene"})
        self.assertEqual(self.memory.pairs("pne")["pane"]["confirmations"], 1)

    def test_live_settings_validate_before_enabling_memory_or_candidates(self):
        self.learner.feedback(self.event())
        settings = self.root / "settings.json"
        settings.write_text('{"learn_enabled":false,"suggestions_enabled":true}')
        self.assertTrue(refresh_policy(self.engine, settings, learner=self.learner))
        self.assertEqual(self.learner.feedback(self.event())["status"], "ignored_disabled")
        self.assertEqual(self.query()["output"], "pne")
        self.assertEqual(self.memory.pairs("pne")["pane"]["confirmations"], 1)
        settings.write_text('{"learn_enabled":true,"suggestions_enabled":"yes","min_frequency":1000}')
        self.assertFalse(refresh_policy(self.engine, settings, learner=self.learner))
        self.assertFalse(self.learner.enabled)
        self.assertEqual(self.engine.policy.min_frequency, 5000)
        self.assertFalse(refresh_policy(self.engine, settings))

    def test_forget_is_visible_to_another_open_session(self):
        self.learner.feedback(self.event())
        with FeedbackMemory(self.path) as other:
            self.assertEqual(other.pairs("pne")["pane"]["confirmations"], 1)
            other.forget("pne")
        self.assertEqual(self.query()["output"], "pne")

    def test_unrelated_database_is_rejected_without_modification(self):
        other = self.root / "other.sqlite3"
        db = sqlite3.connect(other)
        db.execute("CREATE TABLE unrelated(value TEXT)")
        db.commit()
        db.close()
        before = other.read_bytes()
        with self.assertRaises(ValueError):
            FeedbackMemory(other)
        self.assertEqual(other.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
