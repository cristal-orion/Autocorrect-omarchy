from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from autocorrect_core.contextual import ContextualCorrector, TrainingNgrams, missing_internal_vowel
from autocorrect_core.engine import AutocorrectEngine, Policy
from autocorrect_core.prediction import counts_for
from autocorrect_core.probe_server import decide, refresh_policy


class ContextualTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        lexicon = self.root / "words.txt"
        lexicon.write_text("pisa 10000000\npia 9000000\npira 8000000\npila 7000000\npina 6000000\n"
                           "pizza 40000\npipa 70000\nstato 48000000\nsta 6400000\n"
                           "questo 10000000\nquesta 10000\nprogetto 2000000\npersone 7000000\npersona 6000000\n"
                           "cosa 16618014\ncasa 10724853\npane 1383747\npene 1067986\npone 2341696\n"
                           "ne 38489227\npiù 139831889\nfine 14381117\n")
        self.engine = AutocorrectEngine(lexicon, policy=Policy(min_frequency=5000))
        self.model = self.make_model(["una pizza"] * 10 + ["una pipa"] + ["di pisa"] * 15
                                     + ["sono stato"] * 50)
        self.corrector = ContextualCorrector(self.engine, self.model)

    def make_model(self, phrases):
        path = self.root / f"model-{len(list(self.root.glob('*.sqlite3')))}.sqlite3"
        counts = counts_for([phrase.split() for phrase in phrases])
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE ngrams(n INTEGER,c1 TEXT,c2 TEXT,word TEXT,count INTEGER,PRIMARY KEY(n,c1,c2,word)) WITHOUT ROWID")
            db.executemany("INSERT INTO ngrams VALUES(?,?,?,?,?)",
                           [(len(ctx) + 1, *(("", "") + ctx)[-2:], word, count)
                            for (ctx, word), count in counts.items()])
        result = TrainingNgrams(path)
        self.addCleanup(result.close)
        return result

    def test_reranks_beyond_diagnostic_top_three_and_uses_previous_words(self):
        self.assertNotIn("pizza", [c.term for c in self.engine.evaluate("piza", limit=3).candidates])
        decision, info = self.corrector.evaluate("piza", "ieri ho mangiato una ")
        self.assertEqual(decision.output, "pizza")
        self.assertEqual(decision.reason, "context_high_margin")
        self.assertGreater(info["baseline_rank"], 3)
        self.assertEqual(decision.candidates[0].bigram_count, 10)
        self.assertEqual(self.corrector.evaluate("piza", "comune di ")[0].output, "pisa")

    def test_short_words_need_context_and_repeated_evidence(self):
        self.assertEqual(self.corrector.evaluate("stao", "sono ")[0].output, "stato")
        self.assertEqual(self.corrector.evaluate("stao")[0].reason, "short_word")
        weak = ContextualCorrector(self.engine, self.make_model(["una pizza"] * 4))
        result, info = weak.evaluate("piza", "una ")
        self.assertEqual(result.reason, "context_low_evidence")
        self.assertEqual(result.output, "piza")
        self.assertEqual(info["required_evidence"], 5)
        self.assertEqual(self.corrector.evaluate("pz", "una ")[0].reason, "short_word")

    def test_context_boundaries_and_partial_word_do_not_supply_evidence(self):
        for previous in ("", "una", "una. ", "una\n", "una 123 ", "una https://example.org ", "unseen "):
            with self.subTest(previous=previous):
                self.assertEqual(self.corrector.evaluate("piza", previous)[0].output, "piza")

    def test_recognized_words_protections_and_existing_changes_are_preserved(self):
        for token in ("pizza", "pipa", "Piza", "piza/path", "l'piza"):
            self.assertEqual(self.corrector.evaluate(token, "una ")[0].output, token)
        self.assertEqual(self.corrector.evaluate("piza", "una ", context="password")[0].reason, "disabled_context")
        self.engine.protected.add("pizza")
        self.assertEqual(self.corrector.evaluate("piza", "una ")[0].reason, "protected_candidate")
        self.engine.protected.add("piza")
        self.assertEqual(self.corrector.evaluate("piza", "una ")[0].reason, "protected_word")
        self.engine.word_validator = Mock()
        self.engine.word_validator.spell.return_value = True
        self.assertEqual(self.corrector.evaluate("stao", "sono ")[0].reason, "valid_word")
        self.engine.word_validator = None
        baseline = self.engine.evaluate("quesot")
        result, info = self.corrector.evaluate("quesot", "una ")
        self.assertEqual(result, baseline)
        self.assertFalse(info["used"])

    def test_live_frequency_still_blocks_a_contextual_winner(self):
        self.engine.policy = replace(self.engine.policy, min_frequency=100000)
        result, _ = self.corrector.evaluate("piza", "una ")
        self.assertEqual(result.output, "piza")
        self.assertEqual(result.reason, "low_frequency")
        self.engine.policy = replace(self.engine.policy, min_frequency=5000)
        self.assertEqual(self.corrector.evaluate("piza", "una ")[0].output, "pizza")

    def test_ambiguous_context_and_disabled_mode_preserve_input(self):
        tied = ContextualCorrector(self.engine, self.make_model(["una pizza"] * 10 + ["una pipa"] * 10))
        self.assertEqual(tied.evaluate("piza", "una ")[0].reason, "context_ambiguous")
        self.corrector.enabled = False
        self.assertEqual(self.corrector.evaluate("piza", "una ")[0].reason, "short_word")

    def test_read_only_model_and_failure_fallback(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.model.connection.execute("DELETE FROM ngrams")
        self.model.row = Mock(side_effect=sqlite3.OperationalError("unavailable"))
        result, info = self.corrector.evaluate("piza", "una ")
        self.assertEqual(result.output, "piza")
        self.assertTrue(info["model_error"])

    def test_long_word_retarget_requires_trigram_evidence(self):
        weak = ContextualCorrector(self.engine, self.make_model(["la persona"] * 40))
        self.assertEqual(weak.evaluate("persons", "contestando la ")[0].reason, "context_weak_rerank")
        strong = ContextualCorrector(self.engine, self.make_model(["contestando la persona"] * 3 + ["la persona"] * 37))
        self.assertEqual(strong.evaluate("persons", "contestando la ")[0].output, "persona")

    def test_probe_protocol_preserves_suffix_and_discloses_both_margins(self):
        request = json.dumps({"token": "piza.", "previous": "ho mangiato una "}).encode()
        result = decide(self.engine, request, self.corrector)
        self.assertEqual(result["output"], "pizza.")
        self.assertTrue(result["context"]["used"])
        self.assertEqual(result["baseline_required_margin"], 1.3)
        self.assertAlmostEqual(result["required_margin"], self.corrector.policy.margin)
        for previous in (None, [], 12, "a" * 1025, "\0"):
            with self.assertRaises(ValueError):
                decide(self.engine, json.dumps({"token": "piza", "previous": previous}).encode(), self.corrector)

    def test_live_toggle_validates_whole_snapshot(self):
        settings = self.root / "settings.json"
        settings.write_text('{"use_context":false,"min_frequency":5000}')
        self.assertTrue(refresh_policy(self.engine, settings, self.corrector))
        self.assertEqual(self.corrector.evaluate("piza", "una ")[0].reason, "short_word")
        settings.write_text('{"use_context":true,"min_frequency":true}')
        self.assertFalse(refresh_policy(self.engine, settings, self.corrector))
        self.assertFalse(self.corrector.enabled)
        settings.write_text('{"use_context":true}')
        self.assertTrue(refresh_policy(self.engine, settings, self.corrector))
        self.assertEqual(self.corrector.evaluate("piza", "una ")[0].output, "pizza")
        self.assertFalse(refresh_policy(self.engine, settings))

    def test_three_letters_use_a_stricter_margin_and_exact_context(self):
        model = self.make_model(["dire una cosa"] * 3 + ["una cosa"] * 5
                                + ["una casa"] * 2 + ["una alternativa"] * 1000)
        corrector = ContextualCorrector(self.engine, model)
        decision, info = corrector.evaluate("csa", "ti devo dire una ")
        self.assertEqual(decision.output, "cosa")
        self.assertEqual(info["evidence_source"], "exact_trigram")
        self.assertEqual(info["required_margin"], 1.3)
        self.assertEqual(info["edit_penalty"], 3)
        self.assertEqual(corrector.evaluate("csa", "una ")[0].output, "csa")
        for previous in ("", "una. ", "dire una\n", "dire una https://example.org "):
            self.assertEqual(corrector.evaluate("csa", previous)[0].output, "csa")
        for token in ("Csa", "cs", "c"):
            self.assertEqual(corrector.evaluate(token, "dire una ")[0].output, token)

    def test_missing_vowel_uses_article_family_only_when_exact_counts_are_absent(self):
        model = self.make_model(["il pane"] * 8 + ["del pane"] * 2 + ["sul pane"]
                                + ["nel più"] * 16 + ["nel fine"] * 15)
        corrector = ContextualCorrector(self.engine, model)
        decision, info = corrector.evaluate("pne", "prosciutto nel ")
        self.assertEqual(decision.output, "pane")
        self.assertEqual(info["evidence_source"], "article_family")
        self.assertEqual(info["evidence"], 11)
        self.assertEqual(info["required_evidence"], 10)
        self.assertEqual(decision.candidates[0].bigram_count, 0)
        self.assertEqual(decision.candidates[0].article_count, 11)
        self.assertEqual(corrector.evaluate("pne", "prosciutto ")[0].output, "pne")
        self.assertEqual(corrector.evaluate("pne", "la ")[0].output, "pne")
        self.assertEqual(corrector.evaluate("pne", "nel. ")[0].output, "pne")
        # Even one exact observation prevents the grammar aggregate from
        # overriding that different local evidence.
        local = ContextualCorrector(self.engine, self.make_model(["il pane"] * 100 + ["nel pene"]))
        result, detail = local.evaluate("pne", "dolore nel ")
        self.assertEqual(detail["evidence_source"], "exact_trigram")
        self.assertEqual(result.reason, "context_low_evidence")
        self.assertEqual(result.output, "pne")

    def test_article_fallback_needs_repeated_evidence_and_valid_edit(self):
        weak = ContextualCorrector(self.engine, self.make_model(["il pane"] * 9))
        self.assertEqual(weak.evaluate("pne", "nel ")[0].reason, "context_low_evidence")
        strong = ContextualCorrector(self.engine, self.make_model(["il pane"] * 10))
        self.assertEqual(strong.evaluate("pne", "nel ")[0].output, "pane")
        self.assertTrue(missing_internal_vowel("pne", "pane"))
        for candidate in ("ponee", "apne", "pnea", "pen", "pne", "pani"):
            self.assertFalse(missing_internal_vowel("pne", candidate))
        # A consonant insertion is not accepted by the article fallback.
        consonant = ContextualCorrector(self.engine, self.make_model(["il pone"] * 20))
        self.assertEqual(consonant.evaluate("poe", "nel ")[0].output, "poe")

    def test_three_letters_do_not_trust_a_frequent_bigram_alone(self):
        weak = ContextualCorrector(self.engine, self.make_model(["una cosa"] * 500))
        result, info = weak.evaluate("csa", "dire una ")
        self.assertEqual(result.output, "csa")
        self.assertEqual(result.reason, "context_low_evidence")
        self.assertEqual(info["evidence"], 0)
        self.assertEqual(result.candidates[0].bigram_count, 500)

    def test_three_letters_keep_frequency_hunspell_protection_and_two_letter_target_guards(self):
        corrector = ContextualCorrector(self.engine, self.make_model(["il pane"] * 11))
        self.engine.policy = replace(self.engine.policy, min_frequency=2000000)
        self.assertEqual(corrector.evaluate("pne", "nel ")[0].reason, "low_frequency")
        self.engine.policy = replace(self.engine.policy, min_frequency=5000)
        self.engine.protected.add("pne")
        self.assertEqual(corrector.evaluate("pne", "nel ")[0].reason, "protected_word")
        self.engine.protected.remove("pne")
        self.engine.word_validator = Mock()
        self.engine.word_validator.spell.return_value = True
        self.assertEqual(corrector.evaluate("pne", "nel ")[0].reason, "valid_word")
        self.engine.word_validator = None
        short_target = ContextualCorrector(self.engine, self.make_model(["non ne"] * 50))
        self.assertEqual(short_target.evaluate("pne", "non ")[0].reason, "context_short_target")


if __name__ == "__main__":
    unittest.main()
