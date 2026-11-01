"""Exercise installer transactions without touching the desktop or user files."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r"project\(hyprflip VERSION ([\d.]+)", (ROOT / "CMakeLists.txt").read_text()).group(1)
PAIR = {"front": "0xa", "back": "0xb"}


class InstallerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hyprflip-installer-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        for relative in ("scripts/install.py", "scripts/card_restore.py", "CMakeLists.txt", "examples/hyprflip.lua",
                         "examples/module-path.lua"):
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
        self.containers = []
        self.restored = []
        self.recovery_at_unload = None
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
            version = VERSION if self.library.read_bytes() == b"new plugin" else "0.1.0"
            reply = {"version": version, "pairs": self.pairs, "containers": self.containers}
        elif args == ["hyprflip", "finish"]:
            reply = "ok: settled"
        elif args == ["plugin", "unload", str(self.library)]:
            # What a failed update would retry from.
            self.recovery_at_unload = json.loads(self.recovery.read_text()) if self.recovery.exists() else None
            self.loaded = False
            self.pairs = []
            self.containers = []
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
        elif len(args) == 2 and args[0] == "hyprflip" and args[1].startswith("restore "):
            self.restored.append(args[1].removeprefix("restore "))
            reply = "ok: restored"
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
        self.output = io.StringIO()
        with patch.object(Path, "home", return_value=self.home), \
                patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config),
                                        "HYPRLAND_INSTANCE_SIGNATURE": "test-instance"}), \
                patch.object(sys, "argv", ["install.py", *arguments]), \
                patch("subprocess.run", side_effect=self.hyprctl), \
                contextlib.redirect_stdout(self.output):
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
                         {"instance": "test-instance", "pairs": [PAIR], "cards": []})

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

    def test_open_native_cards_are_restored_after_the_upgrade(self):
        self.containers = [{"faces": [["0xc"], ["0xd", "0xe"]], "native_group": True, "floating": True,
                            "active": 1, "unfolded": False, "box": [10, 20, 800, 600],
                            "layouts": [{"axis": "horizontal", "focused": "0xc", "ratios": [1]},
                                        {"axis": "vertical", "focused": "0xe", "ratios": [0.7, 0.3]}]}]
        self.run_installer()
        self.assertEqual(self.restored, ["floating 1 0 10 20 800 600 front horizontal 0xc 0xc:1 "
                                         "back vertical 0xe 0xd:0.7 0xe:0.3"])
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_update_leaves_parked_cards_out_of_restore_and_recovery(self):
        def card(front, back, workspace, **state):
            return {"faces": [[front], [back]], "native_group": True, "floating": False, "fullscreen": False,
                    "active": 0, "unfolded": False, "box": [10, 20, 800, 600], "workspace": workspace,
                    "layouts": [{"axis": "horizontal", "focused": front, "ratios": [1]},
                                {"axis": "horizontal", "focused": back, "ratios": [1]}], **state}
        # The fullscreen check covers the cards an update keeps, not a parked one.
        self.containers = [card("0xc", "0xd", {"id": 3, "name": "3", "special": False}),
                           card("0xe", "0xf", {"id": -98, "name": "special:park", "special": True}, fullscreen=True)]
        self.run_installer()
        shown = "tiled 0 0 10 20 800 600 front horizontal 0xc 0xc:1 back horizontal 0xd 0xd:1"
        self.assertEqual(self.restored, [shown])
        self.assertEqual(self.recovery_at_unload, {"instance": "test-instance", "pairs": [PAIR], "cards": [shown]})
        self.assertIn("Keeping 1 open card(s) through this update.\n"
                      "Leaving 1 hidden card(s) as separate windows; the program that parked them rebuilds them.\n",
                      self.output.getvalue())
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_active_hy3_containers_reject_native_upgrade_before_mutation(self):
        self.containers = [{"faces": [["0xc"], ["0xd", "0xe"]]}]
        with self.assertRaisesRegex(SystemExit, "hy3 cards are active"):
            self.run_installer()
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue(self.loaded)
        self.assertFalse(any(call[0] in ("plugin", "reload") for call in self.calls))
        self.assertFalse(list(self.home.rglob("*.bak-*")))


if __name__ == "__main__":
    unittest.main()
