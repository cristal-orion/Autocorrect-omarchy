from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def native_flags():
    if not shutil.which("g++") or not shutil.which("pkg-config"):
        return None
    found = subprocess.run(["pkg-config", "--cflags", "--libs", "Fcitx5Utils", "json-c"], capture_output=True, text=True)
    return found.stdout.split() if found.returncode == 0 else None


@unittest.skipUnless(native_flags() is not None, "Native engine client requires g++, Fcitx5Utils and json-c")
class EngineClientTest(unittest.TestCase):
    def test_replacement_shape_allows_one_inner_space(self):
        source = Path(__file__).resolve().parents[1] / "probes/fcitx/engine_client_test.cpp"
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "engine-client-test"
            subprocess.run(["g++", "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary),
                            *native_flags()], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
