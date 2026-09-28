import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from autocorrect_core import AutocorrectEngine
from autocorrect_core.probe_server import decide, refresh_policy


class ProbeServerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "words.txt"
        path.write_text("questo 10000000\nquesta 10000\nprogetto 2000000\ncaffè 10000000\nbanco 1000000\nbando 950000\n"
                        "maglione 44882\nmaglioni 1000\n", encoding="utf-8")
        self.engine = AutocorrectEngine(path)
        self.settings = Path(temp.name) / "settings.json"

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

    def test_live_margin_changes_only_the_final_gate(self):
        self.assertEqual(self.decision("banso")["reason"], "ambiguous")
        self.settings.write_text('{"min_score_margin":0.01}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        self.assertEqual(self.decision("banso")["output"], "banco")
        self.assertEqual(self.decision("banso")["required_margin"], .01)
        for token, reason in (("bando", "known_word"), ("proggeto", "edit_distance"),
                              ("Quesot", "capitalized_or_mixed_case")):
            self.assertEqual(self.decision(token)["reason"], reason)
        self.settings.write_text('{"min_score_margin":1.3}')
        refresh_policy(self.engine, self.settings)
        self.assertEqual(self.decision("banso")["reason"], "ambiguous")

    def test_invalid_settings_preserve_last_valid_margin(self):
        self.settings.write_text('{"min_score_margin":0.7}')
        refresh_policy(self.engine, self.settings)
        for payload in ('broken', '[]', '{}', '{"min_score_margin":true}',
                        '{"min_score_margin":"0.5"}', '{"min_score_margin":0}',
                        '{"min_score_margin":NaN}', '{"min_score_margin":Infinity}',
                        '{"min_score_margin":-1}', '{"min_score_margin":5.1}', ' ' * 1025):
            with self.subTest(payload=payload[:60]):
                self.settings.write_text(payload)
                self.assertFalse(refresh_policy(self.engine, self.settings))
                self.assertEqual(self.engine.policy.min_score_margin, .7)
        self.settings.unlink()
        self.assertFalse(refresh_policy(self.engine, self.settings))
        self.assertFalse(refresh_policy(self.engine, None))

    def test_live_frequency_releases_candidate_but_keeps_margin_and_other_guards(self):
        initial = self.decision("maglioner")
        self.assertEqual(initial["reason"], "low_frequency")
        self.assertEqual(initial["required_frequency"], 100000)
        self.assertEqual(initial["candidates"][0]["frequency"], 44882)
        self.settings.write_text('{"min_frequency":5000}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        result = self.decision("maglioner.")
        self.assertEqual(result["output"], "maglione.")
        self.assertEqual(result["required_frequency"], 5000)
        self.assertEqual(result["required_margin"], 1.3)
        for token, reason in (("banso", "ambiguous"), ("proggeto", "edit_distance"),
                              ("Maglioner", "capitalized_or_mixed_case"), ("maglione", "known_word")):
            self.assertEqual(self.decision(token)["reason"], reason)
        self.settings.write_text('{"min_frequency":100000}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        self.assertEqual(self.decision("maglioner")["reason"], "low_frequency")

    def test_settings_snapshot_is_atomic_and_single_field_updates_preserve_the_other(self):
        self.settings.write_text('{"min_score_margin":0.7,"min_frequency":5000}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        for payload in ('{"min_score_margin":1.3,"min_frequency":true}',
                        '{"min_score_margin":8,"min_frequency":20000}',
                        '{"min_score_margin":1.3,"unexpected":1}'):
            self.settings.write_text(payload)
            self.assertFalse(refresh_policy(self.engine, self.settings))
            self.assertEqual(self.engine.policy.min_score_margin, .7)
            self.assertEqual(self.engine.policy.min_frequency, 5000)
        self.settings.write_text('{"min_score_margin":1.3}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        self.assertEqual(self.engine.policy.min_frequency, 5000)
        self.settings.write_text('{"min_frequency":20000}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        self.assertEqual(self.engine.policy.min_score_margin, 1.3)
        self.assertEqual(self.engine.policy.min_frequency, 20000)

    def test_invalid_frequency_preserves_last_valid_policy(self):
        self.settings.write_text('{"min_frequency":5000}')
        refresh_policy(self.engine, self.settings)
        policy = self.engine.policy
        for value in (True, False, None, "5000", 5000.0, 0, -1, 999, 100001,
                      float("nan"), float("inf"), [], {}):
            with self.subTest(value=value):
                self.settings.write_text(json.dumps({"min_frequency": value}))
                self.assertFalse(refresh_policy(self.engine, self.settings))
                self.assertEqual(self.engine.policy, policy)
        self.settings.write_text('{"min_frequency":1000}')
        self.assertTrue(refresh_policy(self.engine, self.settings))
        self.assertEqual(self.engine.policy.min_frequency, 1000)

    def test_frequency_override_does_not_disable_validator(self):
        self.engine.word_validator = Mock()
        self.engine.word_validator.spell.return_value = True
        self.settings.write_text('{"min_score_margin":1.3,"min_frequency":5000}')
        refresh_policy(self.engine, self.settings)
        result = self.decision("maglioner")
        self.assertEqual(result["reason"], "valid_word")
        self.assertEqual(result["output"], "maglioner")
        self.assertEqual(result["required_frequency"], 5000)


if __name__ == "__main__":
    unittest.main()
