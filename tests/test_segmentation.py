from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from autocorrect_core.colloquial_corpus import filter_lines, load_prepared, prepare
from autocorrect_core.engine import AutocorrectEngine, Policy
from autocorrect_core.contextual import TrainingNgrams
from autocorrect_core.feedback import FeedbackLearner, FeedbackMemory
from autocorrect_core.hunspell import DEFAULT_HUNSPELL_DICTIONARY
from autocorrect_core.prediction import counts_for, sentences_from
from autocorrect_core.probe_server import RuntimeControls, decide, handle_request
from autocorrect_core.segmentation import SegmentationPolicy, Segmenter, segmented_parts


class Validator:
    """Accepts the lexicon plus these elided forms, like Hunspell (not un'altro)."""
    metadata = {"source": "test fixture"}
    valid = {"l'acqua", "l'agente", "c'è", "l'ho", "un'amica", "n'è", "all'inizio"}

    def spell(self, word):
        return word in self.valid


def make_model(root, phrases):
    path = root / f"model-{len(list(root.glob('*.sqlite3')))}.sqlite3"
    counts = counts_for([words for phrase in phrases for words in sentences_from(phrase)])
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE ngrams(n INTEGER,c1 TEXT,c2 TEXT,word TEXT,count INTEGER,PRIMARY KEY(n,c1,c2,word)) WITHOUT ROWID")
        db.executemany("INSERT INTO ngrams VALUES(?,?,?,?,?)",
                       [(len(ctx) + 1, *(("", "") + ctx)[-2:], word, count) for (ctx, word), count in counts.items()])
    return TrainingNgrams(path)


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        lexicon = self.root / "words.txt"
        lexicon.write_text("per 9000000\npiacere 900000\nnon 9000000\nlo 9000000\nla 9000000\ngente 800000\n"
                           "agente 300000\nacqua 700000\nl 50000\nstrada 2000000\ntra 5000000\nda 9000000\n"
                           "ho 9000000\nè 9000000\nc'è 7000000\nne 9000000\nné 9000000\nun 9000000\nuna 9000000\n"
                           "amica 400000\naltro 3000000\nall 60000\ninizio 900000\nfavore 900000\ntarda 1500000\n")
        self.engine = AutocorrectEngine(lexicon, word_validator=Validator(), policy=Policy(min_frequency=5000))
        self.news = make_model(self.root, ["non lo so"] * 20 + ["la gente"] * 10 + ["l'agente"] * 8
                               + ["l'acqua"] * 6 + ["la strada"] * 50 + ["tra da"] * 4 + ["c'è"] * 9
                               + ["l'ho"] * 3 + ["un'amica"] * 4 + ["n'è"] * 5 + ["all'inizio"] * 7
                               + ["né lui né lei"] * 30 + ["ne ho"] * 30)
        self.chat = make_model(self.root, ["per piacere"] * 2 + ["per favore"])
        self.addCleanup(self.news.close)
        self.addCleanup(self.chat.close)
        self.segmenter = Segmenter(self.engine, [(self.news, 1.0), (self.chat, 1.0)])

    def run_token(self, token, **options):
        return self.segmenter.evaluate(token, self.engine.evaluate(token), **options)


class SegmentationTest(Fixture):
    def test_splits_joined_words_with_attested_bigram(self):
        decision, info = self.run_token("nonlo")
        self.assertEqual((decision.output, decision.action, decision.reason), ("non lo", "correct", "segmentation_split"))
        self.assertTrue(info["used"])

    def test_restores_apostrophe_validated_by_hunspell(self):
        self.assertEqual(self.run_token("lacqua")[0].output, "l'acqua")
        self.assertEqual(self.run_token("allinizio")[0].output, "all'inizio")
        # Hunspell rejects un'altro, so no elided reading is ever proposed.
        self.assertNotIn("un'altro", [c.term for c in self.run_token("unaltro")[0].candidates])

    def test_weak_or_ambiguous_evidence_abstains(self):
        self.assertEqual(self.run_token("perpiacere")[0].reason, "segmentation_low_evidence")
        decision, _ = self.run_token("lagente")
        self.assertEqual((decision.output, decision.reason), ("lagente", "segmentation_ambiguous"))
        self.assertEqual({c.term for c in decision.candidates[:2]}, {"la gente", "l'agente"})

    def test_generated_corpus_weight_scales_its_evidence(self):
        weighted = Segmenter(self.engine, [(self.news, 1.0), (self.chat, 2.0)])
        decision, _ = weighted.evaluate("perpiacere", self.engine.evaluate("perpiacere"))
        self.assertEqual(decision.output, "per piacere")
        self.assertEqual(decision.candidates[0].evidence, 4.0)

    def test_one_edit_word_competes_with_split(self):
        # "trada" is much more often strada than "tra da".
        decision, info = self.run_token("trada")
        self.assertEqual(decision.output, "trada")
        self.assertEqual(info["outcome"], "word_preferred")
        self.assertEqual(decision.reason, self.engine.evaluate("trada").reason)

    def test_short_elision_ignores_letter_edits_but_not_accent_confusion(self):
        self.assertEqual(self.run_token("cè")[0].output, "c'è")
        self.assertEqual(self.run_token("lho")[0].output, "l'ho")
        # né is far more frequent than n'è: nè is an accent slip, not a lost apostrophe.
        self.assertEqual(self.run_token("nè")[0].output, "nè")

    def test_vetoes_and_existing_decisions_are_untouched(self):
        for token in ("Lacqua", "NONLO", "acqua", "c'è", "non-lo", "l'acqua"):
            self.assertEqual(self.run_token(token)[0].output, token)
        self.assertEqual(self.run_token("nonlo", context="password")[0].output, "nonlo")
        self.engine.protected.add("nonlo")
        self.assertEqual(self.run_token("nonlo")[0].reason, "protected_word")
        self.segmenter.enabled = False
        self.assertEqual(self.run_token("lacqua")[0].output, "lacqua")

    def test_protected_parts_are_not_split_targets(self):
        self.engine.protected.add("lo")
        self.assertNotIn("non lo", [c.term for c in self.run_token("nonlo")[0].candidates])

    def test_segmented_parts_shape(self):
        self.assertEqual(segmented_parts("per piacere"), ["per", "piacere"])
        self.assertEqual(segmented_parts("l'acqua"), ["l", "acqua"])
        for text in ("non lo so", " per", "per ", "l'", "a1 b", "l'acqua bene"):
            self.assertIsNone(segmented_parts(text))

    def test_policy_margin_is_a_ratio(self):
        self.assertAlmostEqual(SegmentationPolicy(min_ratio=100).margin, 2.0)

    def test_server_keeps_punctuation_and_reports_segmentation(self):
        result = decide(self.engine, json.dumps({"token": "nonlo,", "previous": "io "}).encode(), segmenter=self.segmenter)
        self.assertEqual((result["output"], result["action"]), ("non lo,", "correct"))
        self.assertTrue(result["segmentation"]["used"])
        self.assertEqual(result["required_margin"], self.segmenter.policy.margin)
        paused = decide(self.engine, b'{"token": "nonlo"}', runtime=RuntimeControls(False), segmenter=self.segmenter)
        self.assertEqual((paused["output"], paused["reason"]), ("nonlo", "paused"))
        plain = decide(self.engine, b'{"token": "nonlo"}')
        self.assertEqual(plain["output"], "nonlo")
        self.assertFalse(plain["segmentation"]["enabled"])


class SegmentationFeedbackTest(Fixture):
    def setUp(self):
        super().setUp()
        self.memory = FeedbackMemory(self.root / "feedback.sqlite3")
        self.addCleanup(self.memory.close)
        self.learner = FeedbackLearner(self.engine, self.memory)

    def query(self, token):
        return handle_request(self.engine, json.dumps({"token": token, "previous": ""}).encode(),
                              learner=self.learner, segmenter=self.segmenter)

    def test_undo_of_a_split_is_remembered(self):
        self.assertEqual(self.query("nonlo")["output"], "non lo")
        result = self.learner.feedback({"op": "feedback", "id": "r1", "kind": "reject", "original": "nonlo",
                                        "target": "non lo", "previous": ""})
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(result["pair_eligible"])
        self.assertEqual((self.query("nonlo")["output"], self.query("nonlo")["reason"]), ("nonlo", "personal_rejected"))

    def test_manual_split_and_elision_are_learned(self):
        self.assertEqual(self.query("perpiacere")["output"], "perpiacere")
        for event_id, original, target in (("m1", "perpiacere", "per piacere,"), ("m2", "lagente", "l'agente")):
            result = self.learner.feedback({"op": "feedback", "id": event_id, "kind": "manual",
                                            "original": original, "target": target, "previous": ""})
            self.assertEqual(result["status"], "learned_pair")
        self.assertEqual(self.query("perpiacere")["output"], "per piacere")
        self.assertEqual(self.query("lagente")["output"], "l'agente")

    def test_unknown_or_multiword_targets_are_ignored(self):
        for event_id, target in (("u1", "per piacre"), ("u2", "non lo so")):
            result = self.learner.feedback({"op": "feedback", "id": event_id, "kind": "manual",
                                            "original": "nonloso", "target": target, "previous": ""})
            self.assertIn(result["status"], ("ignored_unknown_target", "ignored_edit"))


class ColloquialCorpusTest(unittest.TestCase):
    def test_filter_drops_headers_lists_and_unknown_words(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "batch.txt"
            raw.write_text("Batch 1: cena / chat\n```\nCi vediamo per piacere.\n\n- elenco puntato\n"
                           "1. numerata\nUn po' di pane.\nScrivo con un tpyo.\n", encoding="utf-8")
            known = {"ci", "vediamo", "per", "piacere", "un", "po'", "di", "pane", "scrivo", "con"}
            records, stats, unknown = filter_lines([raw], known.__contains__)
        self.assertEqual(records, ["1\tCi vediamo per piacere.", "2\tUn po' di pane."])
        self.assertEqual((stats["non_sentence_lines"], stats["lines_with_unknown_words"], stats["empty_lines"]), (4, 1, 1))
        self.assertEqual(unknown, {"tpyo": 1})

    @unittest.skipUnless(Path(str(DEFAULT_HUNSPELL_DICTIONARY) + ".dic").exists(), "Hunspell italiano assente")
    def test_prepare_replaces_previous_build_and_verifies_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw").mkdir()
            (root / "raw/a.txt").write_text("\n".join(f"Ci vediamo per piacere alle {w}." for w in
                                                      ("otto", "nove", "dieci", "undici", "cinque", "sei", "sette")) + "\n")
            lexicon = root / "words.txt"
            lexicon.write_text("ci 10\nvediamo 10\nper 10\npiacere 10\nalle 10\notto 10\nnove 10\ndieci 10\n"
                               "undici 10\ncinque 10\nsei 10\nsette 10\n")
            prepared = root / "prepared"
            first = prepare(root / "raw", prepared, lexicon, DEFAULT_HUNSPELL_DICTIONARY)
            self.assertEqual(first["filter"]["accepted_lines"], 7)
            (root / "raw/b.txt").write_text("Per piacere, a domani.\n")
            second = prepare(root / "raw", prepared, lexicon, DEFAULT_HUNSPELL_DICTIONARY)
            self.assertEqual(sorted(second["sources"]), ["a.txt", "b.txt"])
            with closing(load_prepared(prepared)) as model:
                self.assertEqual(model.metadata["accepted_lines"], second["filter"]["accepted_lines"])
            (prepared / "ngrams.sqlite3").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                load_prepared(prepared)


class TruncationTokenizerTest(unittest.TestCase):
    def test_apocope_keeps_the_sequence_but_quotes_break_it(self):
        self.assertEqual(sentences_from("prendo un po' di pane"), [["prendo", "un", "po'", "di", "pane"]])
        self.assertEqual(sentences_from("dico 'ciao' a te"), [["dico"], ["a", "te"]])


if __name__ == "__main__":
    unittest.main()
