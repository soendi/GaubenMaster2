import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "GaubenMaster2" / "GaubenMaster2.exe"


def run_exe(args, timeout=90, env=None):
    return subprocess.run(
        [str(EXE), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


@unittest.skipUnless(EXE.is_file(), "gebaute EXE nicht vorhanden")
class BuiltArtifactTests(unittest.TestCase):
    def test_version_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "version.json"
            result = run_exe(["--version-out", str(out)])
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertRegex(payload["version"], r"^\d+\.\d+\.\d+$")

    def test_gui_startup_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "probe.json"
            result = run_exe(["--probe-out", str(out)])
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertGreater(payload["startup_ms"], 0)
            self.assertLess(payload["startup_ms"], 30000)

    def test_startup_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "check.json"
            env = os.environ.copy()
            env["HTTPS_PROXY"] = "http://127.0.0.1:9"
            env["HTTP_PROXY"] = "http://127.0.0.1:9"
            env.pop("NO_PROXY", None)
            env.pop("no_proxy", None)
            result = run_exe(["--check-update-out", str(out)], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
