from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("g++"), "Native edit tracker requires g++")
class EditTrackerTest(unittest.TestCase):
    def test_single_word_gesture_boundaries(self):
        source = Path(__file__).resolve().parents[1] / "probes/fcitx/edit_tracker_test.cpp"
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "edit-tracker-test"
            subprocess.run(["g++", "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
