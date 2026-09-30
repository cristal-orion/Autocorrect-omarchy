import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from autocorrect_core.control import Controller, ControlPaths, rpc
from autocorrect_core.engine import AutocorrectEngine, Policy
from autocorrect_core.feedback import FeedbackLearner, FeedbackMemory
from autocorrect_core.probe_server import RuntimeControls, handle_request, refresh_policy
from autocorrect_core.settings import DEFAULT_SETTINGS, load_settings, validate_patch, write_settings


class Validator:
    metadata = {}

    def spell(self, word):
        return False


class ControlTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        words = self.root / "words.txt"
        words.write_text("questo 10000000\nquesta 10000\npane 1000000\n")
        self.engine = AutocorrectEngine(words, policy=Policy(min_frequency=5000), word_validator=Validator())
        self.memory = FeedbackMemory(self.root / "feedback.sqlite3")
        self.addCleanup(self.memory.close)
        self.learner = FeedbackLearner(self.engine, self.memory)
        self.runtime = RuntimeControls()
        self.settings = self.root / "settings.json"
        write_settings(self.settings, {**DEFAULT_SETTINGS, "use_context": False})

    def request(self, payload):
        return handle_request(self.engine, json.dumps(payload).encode(), learner=self.learner,
                              runtime=self.runtime, settings=self.settings)

    def test_partial_configuration_preserves_other_controls_and_survives_restart(self):
        self.request({"op": "configure", "changes": {"suggestions_enabled": True}})
        result = self.request({"op": "configure", "changes": {"min_score_margin": .9}})
        self.assertTrue(result["configured"])
        self.assertTrue(result["state"]["settings"]["suggestions_enabled"])
        self.assertEqual(result["state"]["settings"]["min_frequency"], 5000)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        self.learner.suggestions_enabled = False
        self.assertTrue(refresh_policy(self.engine, self.settings, learner=self.learner, runtime=self.runtime))
        self.assertTrue(self.learner.suggestions_enabled)

    def test_pause_blocks_base_personal_and_learning_but_allows_forget(self):
        event = {"op": "feedback", "id": "one", "kind": "manual", "original": "pne", "target": "pane"}
        self.request(event)
        self.assertEqual(self.request({"token": "pne"})["output"], "pane")
        self.request({"op": "configure", "changes": {"correction_enabled": False}})
        self.assertEqual(self.request({"token": "quesot"})["output"], "quesot")
        self.assertEqual(self.request({"token": "pne"})["reason"], "paused")
        self.assertEqual(self.request({**event, "id": "two"})["feedback"]["status"], "ignored_paused")
        self.assertEqual(self.memory.status()["confirmations"], 1)
        runtime = RuntimeControls()
        refresh_policy(self.engine, self.settings, learner=self.learner, runtime=runtime)
        self.assertFalse(runtime.correction_enabled)
        self.assertEqual(self.request({"op": "forget", "token": "pne"})["feedback"]["forgotten_events"], 1)

    def test_invalid_configuration_is_atomic(self):
        before = self.settings.read_bytes()
        for changes in ({"learn_enabled": False, "min_frequency": True}, {"min_score_margin": float("nan")},
                        {"unknown": True}, {"use_context": True}, {"correction_enabled": "false"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.request({"op": "configure", "changes": changes})
            self.assertEqual(before, self.settings.read_bytes())
            self.assertTrue(self.learner.enabled)
            self.assertTrue(self.runtime.correction_enabled)

    def test_status_works_without_learning(self):
        result = handle_request(self.engine, b'{"op":"status"}', runtime=self.runtime)
        self.assertEqual(result["state"]["protocol_version"], 1)
        self.assertFalse(result["state"]["capabilities"]["learning"])
        self.assertIsNone(result["memory"])

    def test_read_only_memory_cannot_write(self):
        with FeedbackMemory(self.memory.path, read_only=True) as read_only:
            self.assertEqual(read_only.status()["pair_count"], 0)
            import sqlite3
            with self.assertRaises(sqlite3.OperationalError):
                read_only.forget("pne")

    def test_offline_controller_saves_settings_and_forgets_without_creating_data(self):
        paths = ControlPaths(self.root, self.settings, self.root / "other.sqlite3", self.root / "runtime", self.root / "unit")
        controller = Controller(paths)
        with patch.object(controller, "service_state", return_value={"active": "inactive", "autostart": False}):
            result = controller.configure({"min_frequency": 20000})
            self.assertFalse(result["connected"])
            self.assertEqual(load_settings(self.settings)["min_frequency"], 20000)
            self.assertEqual(controller.forget("pne")["forgotten_events"], 0)
            self.assertFalse(paths.memory.exists())
            self.assertFalse(result["desktop_integration"])

    def test_real_packet_transport(self):
        path = self.root / "test.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as server:
            server.bind(str(path))
            server.listen(1)
            def respond():
                client, _ = server.accept()
                with client:
                    packet = json.loads(client.recv(4096))
                    client.send(json.dumps({"echo": packet}).encode())
            worker = threading.Thread(target=respond)
            worker.start()
            self.assertEqual(rpc(path, {"op": "status"}), {"echo": {"op": "status"}})
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

    def test_desktop_status_reports_only_an_installed_trial(self):
        paths = ControlPaths(self.root, self.settings, self.root / "unused.sqlite3", self.root / "runtime", self.root / "unit")
        controller = Controller(paths)
        marker = self.settings.with_name("desktop-install.json")
        library = self.root / "addon.so"
        marker.write_text(json.dumps({"allowed_program": "BrowserOS", "files": {str(library): "digest"}}))
        with patch.object(controller, "service_state", return_value={}), patch.object(controller, "engine_state", return_value=None):
            self.assertFalse(controller.status()["desktop_integration"])
            library.touch()
            self.assertEqual(controller.status()["desktop_trial"]["allowed_program"], "BrowserOS")
            self.assertEqual(controller.status()["scope"], "browseros_trial")
            marker.write_text("invalid")
            self.assertIsNone(controller.status()["desktop_trial"])


class PanelInstallTest(unittest.TestCase):
    def test_install_preserves_configuration_and_refuses_user_modified_files(self):
        source = Path(__file__).resolve().parents[1] / "scripts/install-omarchy-panel.py"
        spec = importlib.util.spec_from_file_location("panel_installer", source)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, home = root / "project", root / "home"
            for name in (".venv/bin/python", "benchmark-data/leipzig-ita-news-2023-100k/ngrams.sqlite3", "build/fcitx-probe/libautocorrectprobe.so"):
                path = project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            assets = project / "shell/omarchy"
            assets.mkdir(parents=True)
            (assets / "manifest.json").write_text('{"id":"michele.autocorrect"}')
            (assets / "Panel.qml").write_text("Item {}")
            (assets / "autocorrectctl").write_text("#!/usr/bin/env python3\n")
            shell = home / ".config/omarchy/shell.json"
            shell.parent.mkdir(parents=True)
            shell.write_text('{"version":1,"plugins":[{"id":"keep.me"}]}')
            settings = home / ".config/autocorrect/settings.json"
            write_settings(settings, {**DEFAULT_SETTINGS, "min_frequency": 20000})
            before = shell.read_bytes()
            result = installer.install(project, home, enable=False)
            self.assertEqual(shell.read_bytes(), before)
            self.assertEqual(load_settings(settings)["min_frequency"], 20000)
            self.assertEqual((Path(result["backup"]) / ".config/omarchy/shell.json").read_bytes(), before)
            self.assertTrue((home / ".local/bin/autocorrect-control").stat().st_mode & 0o111)
            self.assertIn("RuntimeDirectory=autocorrect", Path(result["service"]).read_text())
            self.assertIn(f"WorkingDirectory={project}\n", Path(result["service"]).read_text())
            self.assertIn('"--segmentation"', Path(result["service"]).read_text())
            self.assertNotIn("--segmentation-corpus", Path(result["service"]).read_text())
            panel = Path(result["plugin"]) / "Panel.qml"
            panel.write_text("User changes")
            with self.assertRaises(ValueError):
                installer.install(project, home, enable=False)
            self.assertEqual(panel.read_text(), "User changes")


if __name__ == "__main__":
    unittest.main()
