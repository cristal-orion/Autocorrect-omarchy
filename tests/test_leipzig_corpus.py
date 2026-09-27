import contextlib
import io
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from autocorrect_core.leipzig_corpus import CORPUS, build_counts, digest_file, prepare_corpus, split_for


class LeipzigCorpusTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_training_only_counts_deduplication_and_sentence_boundaries(self):
        def split(sentence):
            return "evaluation" if sentence == "riservato segreto" else "train"
        lines = ["1\tUno due. Tre quattro!\n", "2\tUNO due.\n", "3\triservato segreto\n",
                 "4\tuno due tre\n"]
        with patch("autocorrect_core.leipzig_corpus.split_for", side_effect=split):
            result = build_counts(lines, self.root)
        self.assertEqual(result["split_segments"], {"train": 3, "evaluation": 1})
        self.assertEqual(result["statistics"]["duplicate_segments"], 1)
        with contextlib.closing(sqlite3.connect(self.root / "ngrams.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT count FROM ngrams WHERE n=1 AND word='uno'").fetchone()[0], 2)
            self.assertIsNone(connection.execute("SELECT count FROM ngrams WHERE word='segreto'").fetchone())
            # Only the fourth input has due -> tre; the first sentence boundary must not add another.
            self.assertEqual(connection.execute("SELECT count FROM ngrams WHERE n=2 AND c2='due' AND word='tre'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count FROM ngrams WHERE n=3 AND c1='uno' AND c2='due' AND word='tre'").fetchone()[0], 1)
        self.assertEqual((self.root / "evaluation.txt").read_text(), "riservato segreto\n")
        self.assertNotIn("riservato", (self.root / "unigrams.txt").read_text())

    def test_bad_input_and_duplicate_identifiers_are_rejected(self):
        for index, lines in enumerate((["missing tab"], ["0\tparola"], ["1\tuno due", "1\ttre quattro"])):
            folder = self.root / str(index)
            folder.mkdir()
            with self.assertRaises(ValueError):
                build_counts(lines, folder)

    def test_archive_is_pinned_and_ignores_unrelated_paths(self):
        archive = self.root / "sample.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, content in ((f"{CORPUS}/{CORPUS}-sentences.txt", b"1\tuno due tre\n"),
                                  (f"{CORPUS}/{CORPUS}-meta.txt", b"1\tSENTENCES\t1\n"),
                                  ("../../outside", b"not extracted")):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        destination = self.root / "result"
        with self.assertRaisesRegex(ValueError, "Checksum"):
            prepare_corpus(archive, destination)
        self.assertFalse(destination.exists())
        with (patch("autocorrect_core.leipzig_corpus.SHA256", digest_file(archive)),
              patch("autocorrect_core.leipzig_corpus.split_for", return_value="train"),
              contextlib.redirect_stdout(io.StringIO())):
            manifest = prepare_corpus(archive, destination)
        self.assertEqual(manifest["license_verification"]["status"], "unverified_for_this_archive")
        self.assertEqual(manifest["files_sha256"]["train.txt"], digest_file(destination / "train.txt"))
        self.assertFalse((self.root / "outside").exists())
        with self.assertRaisesRegex(ValueError, "esiste"):
            prepare_corpus(archive, destination)

    def test_split_is_order_independent(self):
        phrases = ["uno due", "tre quattro", "cinque sei"]
        expected = {phrase: split_for(phrase) for phrase in phrases}
        self.assertEqual(expected, {phrase: split_for(phrase) for phrase in reversed(phrases)})
        self.assertTrue(set(expected.values()) <= {"train", "development", "evaluation"})
