"""Recovery tests on temporary homes; no real systemd or input changes."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

SPEC = importlib.util.spec_from_file_location(
    "rescue", Path(__file__).resolve().parents[1] / "scripts/input-rescue.py")
rescue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rescue)


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.recovery = rescue.Recovery(self.home)
        self.recovery.state.mkdir(parents=True)
        self.profile = self.home / ".config/fcitx5/profile"
        self.profile.parent.mkdir(parents=True)
        self.profile.write_text("DefaultIM=keyboard-us\n")
        self.profile.chmod(0o600)
        self.bindings = self.home / ".config/hypr/bindings.lua"
        self.bindings.parent.mkdir(parents=True)
        self.bindings.write_text("-- existing personal bindings\n")
        self.link = self.home / rescue.PATHS[9]
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/usr/lib/systemd/user/omarchy-fcitx5.service")
        self.recovery.capture()

    def test_restore_and_preserve_displaced_files(self):
        self.profile.write_text("broken input\n")
        extra = self.profile.parent / "experimental.conf"
        extra.write_text("enabled")
        plugin = self.home / ".local/lib/autocorrect/addon.so"
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b"experimental")
        unrelated = self.home / "document.txt"
        unrelated.write_text("keep me")
        saved = self.recovery.restore_files()
        self.assertEqual(self.profile.read_text(), "DefaultIM=keyboard-us\n")
        self.assertEqual(self.profile.stat().st_mode & 0o777, 0o600)
        self.assertFalse(extra.exists())
        self.assertFalse(plugin.parent.exists())
        self.assertEqual((saved / ".config/fcitx5/profile").read_text(), "broken input\n")
        self.assertEqual((saved / ".local/lib/autocorrect/addon.so").read_bytes(), b"experimental")
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(unrelated.read_text(), "keep me")
        self.recovery.verify()

    def test_corrupt_backup_does_not_touch_current_files(self):
        backup = self.recovery.baseline / "files/.config/fcitx5/profile"
        backup.write_text("corrupted")
        self.profile.write_text("current")
        with self.assertRaisesRegex(RuntimeError, "Backup danneggiato"):
            self.recovery.restore_files()
        self.assertEqual(self.profile.read_text(), "current")

    def test_existing_baseline_cannot_be_overwritten(self):
        with self.assertRaisesRegex(RuntimeError, "non verrà sovrascritto"):
            self.recovery.capture()
        self.recovery.verify()

    def test_repeated_restore_keeps_hotkey_available_once(self):
        for _ in range(2):
            self.recovery.restore_files()
            self.recovery.ensure_hotkey()
            self.recovery.ensure_hotkey()
            self.assertEqual(self.bindings.read_text().count(rescue.HOTKEY_MARKER), 1)

    def test_restore_moves_symlink_instead_of_following_it(self):
        outside = self.home / "outside"
        outside.write_text("do not touch")
        self.profile.unlink()
        self.profile.symlink_to(outside)
        self.recovery.restore_files()
        self.assertEqual(outside.read_text(), "do not touch")
        self.assertFalse(self.profile.is_symlink())

    def test_redirected_parent_is_rejected_before_restore(self):
        share = self.home / ".local/share"
        target = self.home / "elsewhere"
        target.mkdir()
        share.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "padre simbolica"):
            self.recovery.restore_files()
        self.assertEqual(self.profile.read_text(), "DefaultIM=keyboard-us\n")

    def test_stop_masks_restart_always_service_before_process_check(self):
        def result(*args, **kwargs):
            return subprocess.CompletedProcess(args, 1 if args[0] == "pgrep" else 0, "", "")
        with patch.object(rescue, "run", side_effect=result) as commands:
            rescue.stop_input()
        calls = [call.args for call in commands.call_args_list]
        mask = ("systemctl", "--user", "mask", "--runtime", rescue.SERVICE)
        kill = next(c for c in calls if c[0] == "pkill")
        self.assertLess(calls.index(mask), calls.index(kill))

    def test_full_red_button_with_simulated_system_commands(self):
        self.profile.write_text("experimental input")

        def result(*args, **kwargs):
            if args[:2] == ("hyprctl", "reload"):
                self.assertEqual(self.profile.read_text(), "DefaultIM=keyboard-us\n")
            return subprocess.CompletedProcess(args, 1 if args[0] == "pgrep" else 0, "", "")

        with (patch.object(rescue.Path, "home", return_value=self.home),
              patch.object(rescue.sys, "argv", ["input-rescue"]),
              patch.dict(rescue.os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}),
              patch.object(rescue, "run", side_effect=result) as commands,
              patch.object(rescue, "notify"),
              patch.object(rescue.os, "umask")):
            rescue.main()
        calls = [call.args for call in commands.call_args_list]
        self.assertIn(("hyprctl", "configerrors"), calls)
        self.assertNotIn(("systemctl", "--user", "start", rescue.SERVICE), calls)
        self.assertIn(rescue.HOTKEY_MARKER, self.bindings.read_text())
        self.recovery.verify()

    def test_corrupt_backup_still_stops_input_in_full_red_button(self):
        (self.recovery.baseline / "files/.config/fcitx5/profile").write_text("corrupted")
        self.profile.write_text("current")
        with (patch.object(rescue.Path, "home", return_value=self.home),
              patch.object(rescue.sys, "argv", ["input-rescue"]),
              patch.object(rescue, "stop_input") as stop,
              patch.object(rescue.os, "umask")):
            with self.assertRaisesRegex(RuntimeError, "Backup danneggiato"):
                rescue.main()
        stop.assert_called_once()
        self.assertEqual(self.profile.read_text(), "current")


if __name__ == "__main__":
    unittest.main()
