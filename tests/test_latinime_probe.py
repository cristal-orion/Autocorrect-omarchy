"""The native checks exercise real dictionary I/O, context and request isolation."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from autocorrect_core.aosp_data import Wordlist
from autocorrect_core.engine import AutocorrectEngine
from autocorrect_core.latinime_probe import (
    NativeClient, context_words, decide, encode_probability, export_tables,
)


BINARY = Path(os.environ.get("LATINIME_PROBE_BINARY", "build/latinime-probe/latinime-probe")).resolve()


class ExportAndPolicyTests(unittest.TestCase):
    def test_rank_surrogate_is_ordered_and_missing_endpoints_are_excluded(self):
        data = Wordlist({"grazie": 150, "alle": 200, "ai": 180, "agli": 170, "x" * 48: 100},
                        {("grazie", "alle"): 1, ("grazie", "ai"): 2, ("grazie", "agli"): 3,
                         ("grazie", "missing"): 1, ("x" * 48, "alle"): 1}, {})
        tables, counts = export_tables(data)
        self.assertEqual(counts, {"words": 4, "bigrams": 3, "excluded_long_words": 1})
        self.assertIn("1\t150\tgrazie\n", tables["unigrams"])
        scores = {fields[3]: int(fields[1]) for line in tables["rank-bigrams"].splitlines()
                  if (fields := line.split("\t"))[0] == "2"}
        self.assertGreater(scores["alle"], scores["ai"])
        self.assertGreater(scores["ai"], scores["agli"])
        self.assertEqual(encode_probability(1), 255)
        for bad in (0, -1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                encode_probability(bad)

    def test_context_does_not_cross_sentence_url_or_number(self):
        self.assertEqual(context_words("ci vediamo. ho perso le "), ["ho", "perso", "le"])
        self.assertEqual(context_words("ci vediamo https://example.com domani "), ["domani"])
        self.assertEqual(context_words("ci vediamo 123 "), [])
        self.assertEqual(context_words("uno due tre quattro "), ["due", "tre", "quattro"])
        self.assertEqual(context_words("x" * 48 + " "), [])

    def test_native_score_never_overrides_lexical_context_or_form_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lexicon.txt"
            path.write_text("domani 1000000\nacqua 1000000\n")
            engine = AutocorrectEngine(path, protected_words=["speciale"])
            candidate = {"term": "domani", "score": 900000, "normalized_score": 0.9,
                         "appropriate_for_autocorrection": True, "type": 268435457}
            response = {"candidates": [candidate], "input_probability_code": -1}
            self.assertEqual(decide("domnai", response, engine).output, "domani")
            for word in ("Domnai", "domani", "speciale", "lacqua", "abc", "a/b", "l'acqua"):
                self.assertEqual(decide(word, response, engine).output, word)
            self.assertEqual(decide("domnai", response, engine, context="password").output, "domnai")
            response["input_probability_code"] = 1
            self.assertEqual(decide("domnai", response, engine).reason, "native_known_word")
            response["input_probability_code"] = -1
            candidate["appropriate_for_autocorrection"] = False
            self.assertEqual(decide("domnai", response, engine).reason, "native_not_appropriate")
            candidate["appropriate_for_autocorrection"] = True
            candidate["normalized_score"] = 0.18
            self.assertEqual(decide("domnai", response, engine).reason, "native_low_score")


@unittest.skipUnless(BINARY.is_file(), "Build the optional native LatinIME probe first")
class NativeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.dictionary = cls.root / "dictionary"
        cls.tsv = cls.root / "words.tsv"
        cls.tsv.write_text("1\t150\tcane\n1\t150\tpane\n1\t150\tvedo\n1\t150\tmangio\n"
                           "1\t170\tcaffè\n1\t170\tperché\n1\t170\tdomani\n"
                           "2\t250\tvedo\tcane\n2\t180\tvedo\tpane\n"
                           "2\t250\tmangio\tpane\n2\t180\tmangio\tcane\n", encoding="utf-8")
        output = subprocess.check_output([str(BINARY), "--compile", str(cls.tsv), str(cls.dictionary)], text=True)
        if json.loads(output) != {"words": 7, "bigrams": 4}:
            raise AssertionError(output)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_context_reverses_predictions_and_survives_reopen(self):
        with NativeClient(BINARY, self.dictionary) as client:
            self.assertEqual(client.ready["words"], 7)
            for previous, expected in (("vedo ", "cane"), ("mangio ", "pane"), ("vedo ", "cane")):
                result = client.query("", previous)
                self.assertEqual(result["candidates"][0]["term"], expected)
            self.assertEqual(client.query("", "vedo. ")["candidates"], [])

    def test_unicode_roundtrip_and_length_limit(self):
        with NativeClient(BINARY, self.dictionary) as client:
            for word in ("caffè", "perché"):
                result = client.query(word)
                self.assertEqual(result["input_probability_code"], 170)
                self.assertIn(word, [candidate["term"] for candidate in result["candidates"]])
            with self.assertRaises(ValueError):
                client.query("x" * 48)
            self.assertEqual(client.query("domani")["input_probability_code"], 170)

    def test_typo_search_has_no_cross_request_cache_or_duplicate_words(self):
        with NativeClient(BINARY, self.dictionary) as client:
            first = client.query("domnai")
            self.assertEqual(first["candidates"][0]["term"], "domani")
            self.assertGreater(first["candidates"][0]["normalized_score"], 0)
            client.query("caffè", "vedo ")
            second = client.query("domnai")
            self.assertEqual(first["candidates"], second["candidates"])
            words = [c["term"] for c in first["candidates"]]
            self.assertEqual(len(words), len(set(words)))

    def test_timeout_closes_process_instead_of_reusing_a_late_response(self):
        with NativeClient(BINARY, self.dictionary) as client:
            client.timeout = 0
            with self.assertRaises(TimeoutError):
                client.query("domnai")
            self.assertIsNotNone(client.process.poll())
            with self.assertRaises(RuntimeError):
                client.query("caffè")

    def test_invalid_requests_do_not_poison_following_request(self):
        bad = ["[]", "{", '{"input":"x","previous":[1]}',
               json.dumps({"input": "x" * 48, "previous": []}),
               json.dumps({"input": "x", "previous": ["one"] * 4}),
               '{"input":"x","previous":[]} trailing']
        valid = json.dumps({"input": "domnai", "previous": []})
        completed = subprocess.run([str(BINARY), str(self.dictionary)],
                                   input="\n".join(bad + [valid]) + "\n", text=True,
                                   capture_output=True, check=True, timeout=20)
        rows = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertTrue(rows[0]["ready"])
        self.assertTrue(all("error" in row for row in rows[1:-1]))
        self.assertEqual(rows[-1]["candidates"][0]["term"], "domani")

    def test_compilation_rejects_overwrite_and_missing_endpoints(self):
        result = subprocess.run([str(BINARY), "--compile", str(self.tsv), str(self.dictionary)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        bad = self.root / "bad.tsv"
        bad.write_text("1\t100\tcane\n2\t200\tmangio\tcane\n")
        result = subprocess.run([str(BINARY), "--compile", str(bad), str(self.root / "bad-dictionary")], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
