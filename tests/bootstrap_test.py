import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
PINNED = "efb50993780079460b0cbed1363e2166a2de1d9f"


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tools = {"cmake", "ninja", "pkg-config", "c++", "git", "python3", "hyprctl"}
        self.modules = {"lua5.4", "glesv2", "hyprland"}
        self.running = {"tag": "v0.56.2", "commit": PINNED}
        self.headers = "0.56.2"

    def fake_run(self, command, **kwargs):
        command = list(command)
        if command[:2] == ["pkg-config", "--exists"]:
            return subprocess.CompletedProcess(command, 0 if command[2] in self.modules else 1, "", "")
        if command[:2] == ["pkg-config", "--modversion"]:
            return subprocess.CompletedProcess(command, 0, self.headers + "\n", "")
        if command[:2] == ["hyprctl", "version"]:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.running), "")
        if command[:2] == ["cmake", "--version"]:
            return subprocess.CompletedProcess(command, 0, "cmake version 4.4.3\n", "")
        self.fail(f"Unexpected command: {command}")

    def check(self):
        out = io.StringIO()
        with patch("shutil.which", side_effect=lambda tool: f"/usr/bin/{tool}" if tool in self.tools else None), \
                patch("subprocess.run", side_effect=self.fake_run), \
                patch.object(sys, "argv", ["bootstrap.py", "--check", "--json"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(PROJECT / "scripts/bootstrap.py"), run_name="__main__")
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        return result.exception.code, events

    def failure(self):
        code, events = self.check()
        self.assertEqual(code, 1)
        failed = next(e for e in events if e.get("status") == "failed")
        self.assertEqual(events[-1], {"event": "done", "ok": False, "checked_only": True})
        return failed

    def test_ready_system_passes(self):
        code, events = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(events[-1]["ok"], True)

    def test_missing_tools_and_modules_name_their_packages(self):
        self.tools -= {"ninja", "c++"}
        self.modules -= {"lua5.4"}
        failed = self.failure()
        self.assertIn("ninja", failed["detail"])
        self.assertEqual(failed["fix"], "sudo pacman -S --needed gcc lua ninja")

    def test_other_hyprland_version_is_refused(self):
        self.running = {"tag": "v0.57.0", "commit": "f" * 40}
        self.assertIn("targets Hyprland 0.56.2", self.failure()["detail"])

    def test_mismatched_headers_are_refused(self):
        self.headers = "0.55.0"
        self.assertIn("headers are 0.55.0", self.failure()["detail"])

    def test_untested_hyprland_commit_is_refused(self):
        self.running = {"tag": "v0.56.2", "commit": "a" * 40}
        self.assertIn("not one this source was tested against", self.failure()["detail"])


if __name__ == "__main__":
    unittest.main()
