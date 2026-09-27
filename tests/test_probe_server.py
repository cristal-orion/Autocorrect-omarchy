import json
from pathlib import Path
import tempfile
import unittest

from autocorrect_core import AutocorrectEngine
from autocorrect_core.probe_server import decide


class ProbeServerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "words.txt"
        path.write_text("questo 10000000\nquesta 10000\nprogetto 2000000\ncaffè 10000000\nbanco 1000000\nbando 950000\n", encoding="utf-8")
        self.engine = AutocorrectEngine(path)

    def decision(self, token):
        return decide(self.engine, json.dumps({"token": token}).encode())

    def test_real_policy_and_trailing_punctuation(self):
        for token, output in (("quesot", "questo"), ("quesot.", "questo."),
                              ("quesot?!", "questo?!"), ("proggeto", "proggeto"),
                              ("Quesot", "Quesot"), ("caffe", "caffè")):
            with self.subTest(token=token):
                result = self.decision(token)
                self.assertEqual(result["original"], token)
                self.assertEqual(result["output"], output)

    def test_structured_input_is_not_split(self):
        for token in ("https://quesot.it", "a@quesot.it", "/tmp/quesot", "quesot_foo", "l'quesot", "un quesot"):
            self.assertEqual(self.decision(token)["output"], token)

    def test_diagnostics_explain_ambiguity_without_changing_the_decision(self):
        result = self.decision("banso")
        self.assertEqual(result["action"], "keep")
        self.assertEqual(result["reason"], "ambiguous")
        self.assertEqual(result["output"], "banso")
        self.assertEqual(result["candidates"][0]["term"], "banco")
        self.assertLess(result["score_margin"], result["required_margin"])
        known = self.decision("bando")
        self.assertEqual(known["reason"], "known_word")
        self.assertEqual(known["candidates"], [])
        self.assertIsNone(known["score_margin"])

    def test_invalid_packets_are_rejected(self):
        for packet in (b"[]", b"null", b"{}", b'{"token":7}', b"broken",
                       json.dumps({"token": "a" * 129}).encode(), json.dumps({"token": "a\0b"}).encode()):
            with self.subTest(packet=packet[:20]), self.assertRaises(ValueError):
                decide(self.engine, packet)


if __name__ == "__main__":
    unittest.main()
