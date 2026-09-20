"""Exercise installer transactions without touching the desktop or user files."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
PAIR = {"front": "0xa", "back": "0xb"}


class InstallerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hyprflip-installer-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        for relative in ("scripts/install.py", "CMakeLists.txt", "examples/hyprflip.lua"):
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        source = self.project / "build/hyprflip.so"
        source.parent.mkdir()
        source.write_bytes(b"new plugin")
        self.home = self.root / "user"
        self.config = self.home / "config"
        self.library = self.home / ".local/lib/hyprflip/hyprflip.so"
        self.recovery = self.library.with_suffix(".upgrade.json")
        self.module = self.config / "hypr/hyprflip.lua"
        self.main = self.config / "hypr/hyprland.lua"
        self.main.parent.mkdir(parents=True)
        self.main.write_text("-- existing desktop configuration\n")
        self.library.parent.mkdir(parents=True)
        self.library.write_bytes(b"old plugin")
        self.module.write_text("-- custom settings stay intact\n"
                               "duration_ms = 280,\nperspective = 6.5,\nretreat = 0.035,\n")
        self.originals = {p: p.read_bytes() for p in (self.library, self.module, self.main)}
        self.loaded = True
        self.pairs = [PAIR.copy()]
        self.fail_adoption = False
        self.calls = []

    def hyprctl(self, command, **kwargs):
        self.assertEqual(command[0], "hyprctl")
        args = command[1:]
        self.calls.append(args)
        if args == ["-j", "binds"]:
            reply = []
        elif args == ["-j", "plugin", "list"]:
            reply = [{"name": "hyprflip"}] if self.loaded else []
        elif args == ["hyprflip", "status"]:
            self.assertTrue(self.loaded)
            version = "0.1.1" if self.library.read_bytes() == b"new plugin" else "0.1.0"
            reply = {"version": version, "pairs": self.pairs}
        elif args == ["hyprflip", "finish"]:
            reply = "ok: settled"
        elif args == ["plugin", "unload", str(self.library)]:
            self.loaded = False
            self.pairs = []
            reply = "ok"
        elif args == ["plugin", "load", str(self.library)]:
            self.assertTrue(self.library.is_file())
            self.loaded = True
            reply = "ok"
        elif args == ["reload"]:
            # Model Hyprland's cached desired plugin list: an unchanged load
            # declaration after manual unload does not load it again.
            reply = "ok"
        elif args == ["configerrors"]:
            reply = ""
        elif args == ["-j", "clients"]:
            reply = [{"address": address, "grouped": list(PAIR.values())}
                     for address in PAIR.values()]
        elif args == ["hyprflip", "adopt", PAIR["front"], PAIR["back"]]:
            if self.library.read_bytes() == b"old plugin":
                reply = "unknown request"
            elif self.fail_adoption:
                reply = "error: adoption failed"
            else:
                self.pairs.append(PAIR.copy())
                reply = "ok: adopted"
        else:
            self.fail(f"Unexpected IPC: {args}")
        if not isinstance(reply, str):
            reply = json.dumps(reply)
        return subprocess.CompletedProcess(command, 0, reply, "")

    def run_installer(self, *arguments):
        with patch.object(Path, "home", return_value=self.home), \
                patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config),
                                        "HYPRLAND_INSTANCE_SIGNATURE": "test-instance"}), \
                patch.object(sys, "argv", ["install.py", *arguments]), \
                patch("subprocess.run", side_effect=self.hyprctl), \
                contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(self.project / "scripts/install.py"), run_name="__main__")

    def test_upgrade_restores_pairs_and_preserves_custom_settings(self):
        self.run_installer()
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertEqual(self.pairs, [PAIR])
        self.assertFalse(self.recovery.exists())
        self.assertTrue(self.loaded)
        self.assertIn(["plugin", "load", str(self.library)], self.calls)
        self.assertEqual(self.module.read_text(), "-- custom settings stay intact\n"
                         "duration_ms = 420,\nperspective = 6.5,\nretreat = 0.02,\n")
        self.assertEqual(self.main.read_text().count('require("hypr.hyprflip")'), 1)
        for path, content in self.originals.items():
            backups = list(path.parent.glob(path.name + ".bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), content)

    def test_failed_adoption_rolls_back_and_retains_recovery_for_retry(self):
        self.fail_adoption = True
        with self.assertRaisesRegex(RuntimeError, "Could not restore pair"):
            self.run_installer()
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue(self.loaded)
        self.assertEqual(self.pairs, [])
        self.assertEqual(json.loads(self.recovery.read_text()),
                         {"instance": "test-instance", "pairs": [PAIR]})

        self.fail_adoption = False
        self.run_installer()
        self.assertEqual(self.pairs, [PAIR])
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_fresh_install_loads_plugin_and_adds_lua_setup(self):
        self.library.unlink()
        self.module.unlink()
        self.loaded = False
        self.pairs = []
        self.run_installer()
        self.assertTrue(self.loaded)
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertEqual(self.module.read_bytes(), (ROOT / "examples/hyprflip.lua").read_bytes())
        self.assertEqual(self.main.read_text().count('require("hypr.hyprflip")'), 1)
        self.assertFalse(self.recovery.exists())

    def test_dry_run_does_not_modify_files_or_plugin_state(self):
        with self.assertRaises(SystemExit) as result:
            self.run_installer("--dry-run")
        self.assertEqual(result.exception.code, 0)
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue(self.loaded)
        self.assertEqual(self.pairs, [PAIR])
        self.assertFalse(self.recovery.exists())
        self.assertFalse(list(self.home.rglob("*.bak-*")))
        self.assertEqual(self.calls, [["-j", "binds"], ["-j", "plugin", "list"],
                                     ["hyprflip", "status"]])


if __name__ == "__main__":
    unittest.main()
