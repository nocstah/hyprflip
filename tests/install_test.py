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
sys.path.insert(0, str(ROOT / "scripts"))
import workflow as setup  # noqa: E402
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


def monitor(name, workspace, special="", focused=False):
    """A monitor as `-j monitors` reports it."""
    return {"name": name, "focused": focused, "activeWorkspace": {"id": workspace, "name": str(workspace)},
            "specialWorkspace": {"id": -98 if special else 0, "name": special}}


def line(front, back):
    """The restore line the installer sends for that card."""
    return f"tiled 0 0 10 20 800 600 front horizontal {front} {front}:1 back horizontal {back} {back}:1"


class InstallerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hyprflip-installer-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        for relative in ("scripts/install.py", "scripts/card_restore.py", "scripts/workflow.py", "CMakeLists.txt",
                         "examples/hyprflip.lua", "examples/module-path.lua"):
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
        # The keyboard, what it does at the unload, what the monitors show and what
        # Hyprland says of each window. None for a keyboard on nothing.
        self.keyboard, self.dropped_at_unload = PAIR["front"], False
        self.monitors = [monitor("DP-1", 3, focused=True), monitor("HDMI-A-1", 9)]
        self.taken_after_restore = self.taken_at_adoption = self.closed_after_restore = self.moved_after_restore = self.read_failure = None
        self.hidden_after_restore = set()
        # A card as the core reports it once rebuilt, when the reload moved its tile,
        # and as a correction brings it back. A step acts only while it has the keyboard.
        self.moved_card = self.back_card = None
        # Workspaces with a fullscreen window, and a change at the desk during the corrections.
        self.fullscreen, self.after_steps = set(), None

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
            if self.dropped_at_unload:
                self.keyboard = None
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
            reply = [{"address": address, "grouped": list(PAIR.values()), "acceptsInput": address not in self.hidden_after_restore}
                     for address in (*PAIR.values(), "0xc", "0xd", "0xe", "0xf") if address != self.closed_after_restore]
        elif args == ["-j", "activewindow"]:
            # Where the keyboard goes back to, after an unload and after a card's tile correction.
            if self.read_failure == "activewindow":
                raise RuntimeError("Couldn't read (6)")
            reply = {"address": self.keyboard} if self.keyboard else {}
        elif args == ["-j", "monitors"]:
            if self.read_failure == "monitors":
                raise RuntimeError("Couldn't read (6)")
            reply = self.monitors
        elif args == ["-j", "workspaces"]:
            reply = [{"id": SHOWN["id"], "hasfullscreen": SHOWN["id"] in self.fullscreen}]
        elif len(args) == 2 and args[0] == "dispatch":
            # Only the no-warp focuses and a correction's guarded steps go out in these updates.
            address = re.fullmatch(r'function\(\) local focus = hl\.dsp\.focus\(\{ window = "address:(0x[0-9a-f]+)" \}\) .*', args[1])
            step = re.fullmatch(r'function\(\) local window = hl\.get_active_window\(\) if window and \((.+)\) then hl\.dispatch\((.+)\) end end', args[1])
            elsewhere = re.fullmatch(r'function\(\) local focus = hl\.dsp\.focus\(\{ monitor = "[A-Z][A-Z0-9-]+" \}\) .*', args[1])
            self.assertTrue(address or step or elsewhere, args[1])
            if address:
                self.keyboard = address[1]
            elif step and self.keyboard in re.findall(r'"(0x[0-9a-f]+)"', step[1]) and self.back_card:
                self.containers = [self.back_card]
                if self.after_steps:
                    self.after_steps()
            reply = "ok"
        elif len(args) == 2 and args[0] == "hyprflip" and args[1].startswith("restore "):
            restore = args[1].removeprefix("restore ")
            quiet, restore = restore.startswith("quiet "), restore.removeprefix("quiet ")
            if restore in self.unanswered:
                code = self.unanswered[restore]
                if code is None: raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
                return subprocess.CompletedProcess(command, code, UNANSWERED[code], "")
            if quiet and self.library.read_bytes() == b"old plugin":
                # A core older than quiet restores answers with its usage line.
                reply = "error: Use restore <tiled|floating> <active> <unfolded> <x> <y> <w> <h> front ... back ..."
            elif restore in self.refused:
                reply = "error: The card could not be restored; its apps stay open."
            else:
                self.restored.append(restore)
                reply = "ok: restored"
                if self.moved_card:
                    self.containers = [self.moved_card]
                # Someone at the desk, while the update runs.
                if self.taken_after_restore:
                    self.keyboard = self.taken_after_restore
                if self.moved_after_restore:
                    self.monitors = self.moved_after_restore
        elif args == ["hyprflip", "adopt", PAIR["front"], PAIR["back"]]:
            if self.library.read_bytes() == b"old plugin":
                reply = "unknown request"
            elif self.fail_adoption:
                reply = "error: adoption failed"
            else:
                self.pairs.append(PAIR.copy())
                reply = "ok: adopted"
                if self.taken_at_adoption:
                    self.keyboard = self.taken_at_adoption
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

    def test_an_update_restores_cards_quietly_and_a_rollback_plainly(self):
        # A plain restore gives each card the keyboard and shows its workspace.
        # The core an update loads is this checkout's, which has the quiet form;
        # the one a rollback goes back to can be older and refuse it.
        def restores():
            return [args[1] for args in self.calls if args[0] == "hyprflip" and args[1].startswith("restore ")]
        first, second = line("0xc", "0xd"), line("0xe", "0xf")
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
        self.run_installer()
        self.assertEqual(restores(), ["restore quiet " + first, "restore quiet " + second])
        self.setUp()
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
        self.unanswered = {second: 6}
        with self.assertRaises(RuntimeError):
            self.run_installer()
        self.assertEqual(restores(), ["restore quiet " + first, "restore quiet " + second,
                                      "restore " + first, "restore " + second])

    def focuses(self):
        return [args[1] for args in self.calls if args[0] == "dispatch"]

    def test_the_keyboard_an_unload_dropped_goes_back_to_its_app(self):
        # Unloading the core takes it from every app of a multi-app face but one,
        # and a quiet restore gives it to nothing.
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
        self.pairs, self.keyboard, self.dropped_at_unload = [], "0xd", True
        self.run_installer()
        self.assertEqual(self.focuses(), [setup.Unattended.focus_command("0xd")])
        self.assertEqual(self.keyboard, "0xd")
        # Read before the unload, and given back once, after the last restore and before any tile is looked at.
        self.assertLess(self.calls.index(["-j", "activewindow"]), self.calls.index(["plugin", "unload", str(self.library)]))
        focus = self.calls.index(["dispatch", self.focuses()[0]])
        restored = self.calls.index(["hyprflip", "restore quiet " + line("0xe", "0xf")])
        self.assertLess(restored, focus)
        self.assertNotIn(["hyprflip", "status"], self.calls[restored:focus])
        self.assertIn(["hyprflip", "status"], self.calls[focus:])
        self.assertTrue(self.library.read_bytes() == b"new plugin" and not self.recovery.exists())

    def moved(self, **state):
        """A card that the reload moves out of its tile and a correction brings back."""
        self.containers = [card("0xc", "0xd", SHOWN, current="0xc", **state)]
        self.moved_card = card("0xc", "0xd", SHOWN, box=[900, 20, 800, 600], current="0xc")
        self.back_card = card("0xc", "0xd", SHOWN, current="0xc")

    def test_every_card_is_rebuilt_before_any_tile_is_corrected(self):
        # A correction next to a card that is still loose tiles resizes the wrong
        # split, which squeezes that card to a sliver.
        self.moved()
        self.containers.append(card("0xe", "0xf", SHOWN))
        self.pairs, self.keyboard = [], "0xa"
        self.run_installer()
        self.assertEqual(self.restored, [line("0xc", "0xd"), line("0xe", "0xf")])
        last = self.calls.index(["hyprflip", "restore quiet " + line("0xe", "0xf")])
        steps = [i for i, args in enumerate(self.calls) if args[0] == "dispatch" and "get_active_window" in args[1]]
        self.assertTrue(steps)
        self.assertLess(last, steps[0])
        self.assertNotIn(["hyprflip", "status"], self.calls[self.calls.index(["hyprflip", "restore quiet " + line("0xc", "0xd")]):last])
        # A refused card is left alone, even if its apps come to read as a card meanwhile.
        self.setUp()
        self.moved()
        self.containers.append(card("0xe", "0xf", SHOWN))
        self.pairs, self.keyboard, self.refused = [], "0xa", {line("0xc", "0xd")}
        self.run_installer()
        self.assertEqual(self.restored, [line("0xe", "0xf")])
        self.assertEqual(self.containers, [self.moved_card])
        self.assertIn("Could not keep a card", self.output.getvalue())
        self.assertNotIn("A card was kept", self.output.getvalue())
        self.assertEqual(self.focuses(), [])

    def test_the_keyboard_goes_back_before_the_first_correction(self):
        # Each correction gives the keyboard back where it found it. Found on nothing,
        # with a monitor to put back, it would be left with whatever that monitor hands it to.
        self.moved()
        self.pairs, self.keyboard, self.dropped_at_unload = [], "0xa", True
        self.run_installer()
        focus = setup.Unattended.focus_command
        self.assertEqual([text for text in self.focuses() if "get_active_window" not in text],
                         [focus("0xa"), focus("0xc"), focus("0xa")])
        steps = [text for text in self.focuses() if "get_active_window" in text]
        self.assertEqual(self.focuses(), [focus("0xa"), focus("0xc"), *steps, focus("0xa")])
        self.assertEqual(self.keyboard, "0xa")
        self.assertNotIn("A card was kept", self.output.getvalue())
        self.assertNotIn("not as it was", self.output.getvalue())

    def test_a_card_that_could_not_come_back_says_so_and_the_update_goes_on(self):
        # Reloads and restores moved it, and no step brings it back.
        self.moved()
        self.back_card = None
        self.pairs, self.keyboard = [], "0xa"
        self.run_installer()
        self.assertIn("A card was kept, but its tile could not be checked or returned to the same place.", self.output.getvalue())
        self.assertEqual(self.keyboard, "0xa")
        self.assertNotIn("not as it was", self.output.getvalue())
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_a_fullscreen_window_on_a_cards_workspace_is_named(self):
        self.moved()
        self.pairs, self.keyboard, self.fullscreen = [], "0xa", {SHOWN["id"]}
        self.run_installer()
        self.assertIn("A card was kept, but a fullscreen window on its workspace kept its tile from being checked or returned.",
                      self.output.getvalue())
        self.assertNotIn("could not be checked", self.output.getvalue())
        self.assertEqual(self.focuses(), [])
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_the_update_says_when_the_keyboard_or_a_monitor_is_not_as_it_was(self):
        word = "The keyboard or what a monitor shows is not as it was before the update, or Hyprland did not say."
        # Someone took the keyboard, or Hyprland stopped answering after the restores.
        def taken(): self.keyboard = "0xe"
        def shows(): self.monitors = [monitor("DP-1", 4, focused=True), monitor("HDMI-A-1", 9)]
        def opens(): self.monitors = [monitor("DP-1", 3, "special:pad", focused=True), monitor("HDMI-A-1", 9)]
        def unread(): self.read_failure = "monitors"
        for change in (taken, shows, opens, unread):
            with self.subTest(change=change.__name__):
                self.setUp()
                self.moved()
                self.pairs, self.keyboard = [], "0xa"
                self.after_steps = change
                self.run_installer()
                self.assertIn(word, self.output.getvalue())
                self.assertEqual(self.library.read_bytes(), b"new plugin")
                self.assertFalse(self.recovery.exists())
        # Hyprland would not say before the unload either.
        self.setUp()
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.pairs, self.read_failure = [], "activewindow"
        self.run_installer()
        self.assertIn(word, self.output.getvalue())
        # Only which monitor has the focus differs: with the pointer on another
        # monitor than the keyboard, a focus that gives the keyboard back brings it along.
        self.setUp()
        self.moved()
        self.pairs, self.keyboard = [], "0xa"
        self.after_steps = lambda: setattr(self, "monitors", [monitor("DP-1", 3), monitor("HDMI-A-1", 9, focused=True)])
        self.run_installer()
        self.assertNotIn(word, self.output.getvalue())
        # All as it was, with a pair kept too.
        self.setUp()
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.run_installer()
        self.assertNotIn(word, self.output.getvalue())
        # A pair kept and no card: the same line for the same reasons.
        self.setUp()
        self.keyboard, self.taken_at_adoption = "0xa", "0xf"
        self.run_installer()
        self.assertIn(word, self.output.getvalue())
        self.setUp()
        self.keyboard = "0xa"
        self.run_installer()
        self.assertNotIn(word, self.output.getvalue())
        # Nothing to keep: nothing to say, and nothing is read for it.
        self.setUp()
        self.pairs = []
        self.keyboard = "0xa"
        self.run_installer()
        self.assertNotIn(word, self.output.getvalue())
        self.setUp()
        self.pairs, self.read_failure = [], "monitors"
        self.run_installer()
        self.assertNotIn(word, self.output.getvalue())

    def test_a_monitor_that_could_not_be_put_back_leaves_the_card_and_the_update_goes_on(self):
        # A named workspace, whose id no focus can show again. Reloads and restores
        # have moved the card, and its tile stays out rather than the monitor.
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.moved_card = card("0xc", "0xd", SHOWN, box=[900, 20, 800, 600], current="0xc")
        self.pairs, self.keyboard = [], "0xe"
        self.monitors = [monitor("DP-1", -1337, focused=True), monitor("HDMI-A-1", 9)]
        self.run_installer()
        self.assertIn("A card was kept, but its tile could not be checked or returned to the same place.", self.output.getvalue())
        self.assertEqual(self.focuses(), [])
        self.assertEqual(self.library.read_bytes(), b"new plugin")
        self.assertFalse(self.recovery.exists())

    def test_the_keyboard_on_a_window_that_kept_it_gets_no_focus(self):
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.keyboard = "0xc"
        self.run_installer()
        self.assertEqual(self.focuses(), [])
        # Nothing had it either: nothing gets it.
        self.setUp()
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.keyboard = None
        self.run_installer()
        self.assertEqual(self.focuses(), [])

    def test_a_pairs_app_counts_as_the_updates_own(self):
        # Adopting a pair may leave the keyboard on its other app: that is no one at the desk.
        self.keyboard, self.taken_after_restore = "0xc", PAIR["back"]
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.run_installer()
        self.assertEqual(self.focuses(), [setup.Unattended.focus_command("0xc")])

    def test_the_keyboard_stays_with_someone_at_the_desk(self):
        # They took it during the update, went to an empty workspace, or opened a special one.
        for name, value in (("taken_after_restore", "0xf"),
                            ("moved_after_restore", [monitor("DP-1", 4, focused=True), monitor("HDMI-A-1", 9)]),
                            ("moved_after_restore", [monitor("DP-1", 3), monitor("HDMI-A-1", 9, focused=True)]),
                            ("moved_after_restore", [monitor("DP-1", 3, "special:pad", focused=True), monitor("HDMI-A-1", 9)])):
            with self.subTest(name=name, value=value):
                self.setUp()
                self.containers = [card("0xc", "0xd", SHOWN)]
                self.pairs, self.keyboard, self.dropped_at_unload = [], "0xd", True
                setattr(self, name, value)
                self.run_installer()
                self.assertEqual(self.focuses(), [])
                self.assertEqual(self.library.read_bytes(), b"new plugin")

    def test_a_window_that_closed_or_takes_no_input_gets_no_focus(self):
        # One that closed during the update.
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.pairs, self.keyboard, self.dropped_at_unload, self.closed_after_restore = [], "0xd", True, "0xd"
        self.run_installer()
        self.assertEqual(self.focuses(), [])
        self.assertFalse(self.recovery.exists())
        # One on a side the restored card does not show: a focus would turn the card.
        self.setUp()
        self.containers = [card("0xc", "0xd", SHOWN)]
        self.pairs, self.keyboard, self.dropped_at_unload, self.hidden_after_restore = [], "0xd", True, {"0xd"}
        self.run_installer()
        self.assertEqual(self.focuses(), [])

    def test_where_the_keyboard_is_never_decides_the_update(self):
        # Hyprland does not say, before the unload or after the restores.
        for failure in ("activewindow", "monitors"):
            with self.subTest(failure=failure):
                self.setUp()
                self.containers = [card("0xc", "0xd", SHOWN)]
                self.pairs, self.read_failure = [], failure
                self.run_installer()
                self.assertEqual(self.restored, [line("0xc", "0xd")])
                self.assertEqual(self.focuses(), [])
                self.assertEqual(self.library.read_bytes(), b"new plugin")
                self.assertFalse(self.recovery.exists())

    def test_a_rollback_gives_nothing_back(self):
        # Its plain restores give the last card the keyboard, which an older core would do anyway.
        self.containers = [card("0xc", "0xd", SHOWN), card("0xe", "0xf", SHOWN)]
        self.keyboard, self.dropped_at_unload, self.fail_adoption = "0xd", True, True
        with self.assertRaisesRegex(RuntimeError, "Could not restore pair"):
            self.run_installer()
        self.assertEqual(self.focuses(), [])
        self.assertTrue(self.recovery.exists())

    def test_a_recovery_run_gives_the_keyboard_back_like_an_update(self):
        # Nothing is open and the core is gone: the keyboard is read as usual, with
        # no unload to drop it. A restore can take it, and it goes back unless that app is hidden.
        self.loaded = False
        self.pairs = []
        self.recovery.write_text(json.dumps({"instance": "test-instance", "pairs": [], "cards": [line("0xc", "0xd")]}))
        self.keyboard, self.taken_after_restore = "0xd", "0xc"
        self.run_installer()
        self.assertEqual(self.restored, [line("0xc", "0xd")])
        self.assertEqual(self.focuses(), [setup.Unattended.focus_command("0xd")])
        self.assertNotIn(["plugin", "unload", str(self.library)], self.calls)
        self.assertFalse(self.recovery.exists())
        self.setUp()
        self.loaded = False
        self.pairs = []
        self.recovery.write_text(json.dumps({"instance": "test-instance", "pairs": [], "cards": [line("0xc", "0xd")]}))
        self.keyboard, self.taken_after_restore, self.hidden_after_restore = "0xd", "0xc", {"0xd"}
        self.run_installer()
        self.assertEqual(self.focuses(), [])
        self.assertEqual(self.keyboard, "0xc")

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
