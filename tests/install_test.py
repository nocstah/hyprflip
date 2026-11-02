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
SHOWN = {"id": 3, "name": "3", "special": False}
PARKED = {"id": -98, "name": "special:park", "special": True}
# What Hyprland 0.56's hyprctl prints, by its exit code, when Hyprland does not answer.
UNANSWERED = {4: "Couldn't connect to /run/user/1000/hypr/test-instance/.socket.sock. (4)\n",
              6: "Hyprland IPC didn't respond in time\n\nCouldn't read (6)\n"}


def card(front, back, workspace, **state):
    """A tiled native card with one app on each face, as status reports it."""
    return {"faces": [[front], [back]], "native_group": True, "floating": False, "fullscreen": False,
            "active": 0, "unfolded": False, "box": [10, 20, 800, 600], "workspace": workspace,
            "layouts": [{"axis": "horizontal", "focused": front, "ratios": [1]},
                        {"axis": "horizontal", "focused": back, "ratios": [1]}], **state}


def line(front, back):
    """The restore line the installer sends for that card."""
    return f"tiled 0 0 10 20 800 600 front horizontal {front} {front}:1 back horizontal {back} {back}:1"


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
        # Restore lines the core refuses, and those that get no answer: the exit
        # code hyprctl gives up with, or None for a hyprctl that never returns.
        self.refused, self.unanswered = set(), {}
        self.park_at_finish = False
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
            # Another program may park a card while the update settles.
            if self.park_at_finish:
                for container in self.containers:
                    container["workspace"] = PARKED
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
            restore = args[1].removeprefix("restore ")
            if restore in self.unanswered:
                code = self.unanswered[restore]
                if code is None: raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
                return subprocess.CompletedProcess(command, code, UNANSWERED[code], "")
            if restore in self.refused:
                reply = "error: The card could not be restored; its apps stay open."
            else:
                self.restored.append(restore)
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
        # Hyprland 0.56's hyprctl exits 7 when the reply is an error.
        return subprocess.CompletedProcess(command, 7 if reply.startswith("error:") else 0, reply, "")

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
        # The fullscreen check covers the cards an update keeps, not a parked one.
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", PARKED, fullscreen=True)]
        self.run_installer()
        shown = line("0xc", "0xd")
        self.assertEqual(self.restored, [shown])
        self.assertEqual(self.recovery_at_unload, {"instance": "test-instance", "pairs": [PAIR], "cards": [shown]})
        self.assertIn("Keeping 1 open card(s) through this update.\n"
                      "Leaving 1 hidden card(s) as separate windows; the program that parked them rebuilds them.\n",
                      self.output.getvalue())
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_dry_run_counts_hidden_cards_without_changing_anything(self):
        self.containers = [card("0xe", "0xf", PARKED)]
        with self.assertRaises(SystemExit) as result:
            self.run_installer("--dry-run")
        self.assertEqual(result.exception.code, 0)
        self.assertIn("Leaving 1 hidden card(s) as separate windows; the program that parked them rebuilds them.\n",
                      self.output.getvalue())
        self.assertEqual(self.calls, [["-j", "binds"], ["-j", "plugin", "list"], ["hyprflip", "status"]])

    def test_parked_cards_alone_never_replay_the_recovery_file(self):
        # The recovery file is read only when no card or pair of any kind is open.
        self.pairs = []
        self.containers = [card("0xe", "0xf", PARKED)]
        self.recovery.write_text(json.dumps({"instance": "test-instance", "pairs": [PAIR],
                                             "cards": [line("0xc", "0xd")]}))
        self.run_installer()
        self.assertEqual(self.restored, [])
        self.assertEqual(self.pairs, [])
        self.assertNotIn(["hyprflip", "adopt", PAIR["front"], PAIR["back"]], self.calls)
        self.assertEqual(self.library.read_bytes(), b"new plugin")

    def test_a_card_parked_while_the_update_settles_is_left_out(self):
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.park_at_finish = True
        self.run_installer()
        self.assertEqual(self.restored, [])
        self.assertEqual(self.recovery_at_unload["cards"], [])
        self.assertEqual(self.library.read_bytes(), b"new plugin")

    def test_a_refused_restore_leaves_that_card_and_keeps_the_others(self):
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
        self.refused = {line("0xc", "0xd")}
        self.run_installer()
        self.assertEqual(self.restored, [line("0xe", "0xf")])
        self.assertIn("Could not keep a card; its apps stay open as separate windows: "
                      "The card could not be restored; its apps stay open.\n", self.output.getvalue())
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_a_refused_restore_in_the_rollback_keeps_the_other_cards(self):
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
        self.refused = {line("0xc", "0xd")}
        self.fail_adoption = True
        with self.assertRaisesRegex(RuntimeError, "Could not restore pair"):
            self.run_installer()
        self.assertEqual(self.restored, [line("0xe", "0xf")])
        self.assertIn("Could not keep a card", self.output.getvalue())
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(json.loads(self.recovery.read_text()), {"instance": "test-instance", "pairs": [PAIR],
                                                                  "cards": [line("0xc", "0xd"), line("0xe", "0xf")]})

    def test_a_stale_recovery_file_with_a_parked_card_no_longer_aborts(self):
        # Written before updates left parked cards out. Nothing is open, so the
        # update replays it, and the core refuses the card whose apps are parked.
        self.pairs = []
        self.recovery.write_text(json.dumps({"instance": "test-instance", "pairs": [],
                                             "cards": [line("0xc", "0xd"), line("0xe", "0xf")]}))
        self.refused = {line("0xe", "0xf")}
        self.run_installer()
        self.assertEqual(self.restored, [line("0xc", "0xd")])
        self.assertIn("Could not keep a card", self.output.getvalue())
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_a_restore_that_gets_no_answer_still_rolls_the_update_back(self):
        # Only the core's refusal is answered per card. A Hyprland that does not
        # answer stops the update: hyprctl gives up with exit 4 when it cannot
        # connect, or exit 6 after its own 5 s, before the installer's timeout.
        for code in (4, 6, None):
            with self.subTest(code=code):
                self.setUp()
                self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
                self.unanswered = {line("0xc", "0xd"): code}
                with self.assertRaises(RuntimeError if code else subprocess.TimeoutExpired):
                    self.run_installer()
                self.assertNotIn("Could not keep a card", self.output.getvalue())
                for path, content in self.originals.items():
                    self.assertEqual(path.read_bytes(), content)
                self.assertEqual(json.loads(self.recovery.read_text())["cards"], [line("0xc", "0xd"), line("0xe", "0xf")])

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
