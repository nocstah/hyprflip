"""Returning a displaced tiled card to its tile after an update leaves the keyboard and the pointer where they were."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import card_restore  # noqa: E402
from workflow import Unattended  # noqa: E402

# The only focuses settle may send: one request that turns pointer warps off for itself alone,
# aimed at a window by address, a workspace by number, a special workspace or a monitor by name.
WARPS_OFF = (r'local was = hl\.get_config\("cursor\.no_warps"\) == true hl\.config\(\{ cursor = \{ no_warps = true \} \}\) '
             r'local ok, err = pcall\(hl\.dispatch, focus\) hl\.config\(\{ cursor = \{ no_warps = was \} \}\) '
             r'if not ok then error\(err\) end end')
NO_WARP = re.compile(r'function\(\) local focus = hl\.dsp\.focus\(\{ window = "address:(0x[0-9a-fA-F]+)" \}\) ' + WARPS_OFF)
SHOW = re.compile(r'function\(\) local focus = hl\.dsp\.focus\(\{ workspace = ([1-9][0-9]*) \}\) ' + WARPS_OFF)
SPECIAL = re.compile(r'function\(\) local focus = hl\.dsp\.focus\(\{ workspace = "(special:[a-z]+)" \}\) ' + WARPS_OFF)
MONITOR = re.compile(r'function\(\) local focus = hl\.dsp\.focus\(\{ monitor = "([A-Z][A-Z0-9-]+)" \}\) ' + WARPS_OFF)
# Hyprland's own focus, which puts the pointer in the middle of the window it focuses.
PLAIN = re.compile(r'hl\.dsp\.focus\(\{ ?window ?= ?"address:(0x[0-9a-fA-F]+)" ?\}\)')
LAYOUT = re.compile(r'hl\.dsp\.layout\("(togglesplit|swapsplit)"\)')
RESIZE = re.compile(r'hl\.dsp\.window\.resize\(\{x=(-?\d+),y=(-?\d+),relative=true\}\)')
# The only way a step of a correction goes out: acting only while one of the card's own apps has the keyboard.
MEMBER = r'window\.address == "(0x[0-9a-fA-F]+)"'
STEP = re.compile(r'function\(\) local window = hl\.get_active_window\(\) if window and \(' + MEMBER + r'(?: or ' + MEMBER +
                  r')*\) then hl\.dispatch\((.+)\) end end')
# The card's saved tile, as the installer describes it: beside the neighbour, on the right.
LINE = "tiled 0 0 1000 0 1000 1000 front horizontal 0xc 0xc:1 back horizontal 0xd 0xd:1"
SAVED = [1000, 0, 1000, 1000]


def step(dispatcher):
    return card_restore.step_command({"0xc", "0xd"}, dispatcher)


def layout(message):
    return step(f'hl.dsp.layout("{message}")')


class Desktop:
    """Hyprland as settle reaches it: dwindle with a tiled card beside a neighbour, on two monitors.

    0xa is the neighbour, 0xc the card's shown app (0xd is behind it) and 0xb a
    window elsewhere. The card and the neighbour share one split, side by side
    or stacked, with the card first or second; the card's saved tile is side by
    side and second. togglesplit, swapsplit and a resize act on the focused window,
    so only the guarded form goes out, and it changes the card only while one of
    its apps has the keyboard. A plain focus puts the pointer in the middle of its
    window, and the no-warp focus leaves it where it is. For a window in
    unfocusable, Hyprland answers ok and leaves the keyboard where it is. Every
    call lands in calls, every focus of a window in focuses and every other focus
    in visits, and the callables in before[kind] and after[kind] run around each
    call of that kind.

    DP-1 shows workspace 1, with the neighbour and the card, and HDMI-A-1 shows
    workspace 2, with the window elsewhere. Their other workspaces are empty, as
    is any other: hide() moves the card off the monitor and show() brings it
    back. The focus follows Hyprland's Actions::focus: it first changes to the
    window's workspace on that workspace's monitor, whichever monitor had the
    focus, then focuses the window. Changing a workspace on the focused monitor
    gives the keyboard to the window last focused there, or to nothing; moving
    to another monitor does too. Focusing a window under an open special
    workspace closes it, unless hide_special closed it already, and changing a
    workspace on the focused monitor opens a special one there, wherever it was.
    A monitor named in under_pointer stands for the pointer resting there: showing
    an empty workspace moves the focus to it. Workspaces in fullscreen say so.
    """
    def __init__(self, keyboard="0xa", stacked=True, second=False, short=(0, 0)):
        self.keyboard, self.stacked, self.second, self.short = keyboard, stacked, second, list(short)
        self.open, self.carded, self.unfocusable = {"0xa", "0xb", "0xc", "0xd"}, True, set()
        # Off-centre over the neighbour, where any warp shows.
        self.pointer = (250, 333)
        self.calls, self.focuses, self.visits, self.before, self.after = [], [], [], {}, {}
        # A kind of call that fails, and how: hyprctl's exit 7, or no answer in time.
        self.refuse = None
        # Each monitor's workspace and open special workspace, the workspaces that
        # belong to each, each window's workspace and each workspace's last window.
        self.monitors = {"DP-1": [1, ""], "HDMI-A-1": [2, ""]}
        self.owner = {1: "DP-1", 2: "HDMI-A-1", 3: "DP-1", 4: "DP-1", 5: "HDMI-A-1", -1337: "DP-1"}
        self.at = {"0xa": 1, "0xb": 2, "0xc": 1, "0xd": 1}
        self.last = {1: "0xa", 2: "0xb"}
        self.hide_special, self.under_pointer, self.fullscreen = False, None, set()
        self.focused = self.owner[self.at.get(keyboard, 1)]
        if keyboard:
            self.last[self.at[keyboard]] = keyboard

    def hide(self, workspace=3, last="0xc"):
        """The card on a workspace of DP-1 that it does not show, where `last` was focused last."""
        self.at["0xc"] = self.at["0xd"] = workspace
        self.last[workspace] = last
        self.at[last] = workspace
        return self

    def nothing(self, monitor="DP-1", workspace=4):
        """The keyboard on nothing, on an empty workspace of a monitor."""
        self.monitors[monitor][0], self.keyboard, self.focused = workspace, None, monitor
        return self

    def special(self, name="special:pad", monitor="DP-1", keyboard=True):
        """A special workspace open on a monitor, holding a window that has the keyboard unless told otherwise."""
        self.monitors[monitor][1] = name
        self.owner[name] = monitor
        self.open.add("0xe")
        self.at["0xe"] = name
        self.last[name] = "0xe"
        if keyboard:
            self.keyboard, self.focused = "0xe", monitor
        return self

    def close(self, address):
        self.open.discard(address)
        self.last = {workspace: window for workspace, window in self.last.items() if window != address}

    def view(self):
        return {name: tuple(monitor) for name, monitor in self.monitors.items()}, self.focused

    def box(self):
        x, y, width, height = ((0, 500 if self.second else 0, 2000, 500) if self.stacked
                               else (1000 if self.second else 0, 0, 1000, 1000))
        return [x, y, width - self.short[0], height - self.short[1]]

    def middle(self, address):
        if address in ("0xc", "0xd"):
            x, y, width, height = self.box()
            return x + width // 2, y + height // 2
        return {"0xa": (500, 500), "0xb": (3000, 500), "0xe": (100, 100)}[address]

    def __call__(self, *args):
        self.calls.append(args)
        kind = self.kind(args)
        self.before.get(kind, lambda: None)()
        if self.refuse and self.refuse[0] == kind:
            raise self.refuse[1]
        reply = self.answer(*args)
        self.after.get(kind, lambda: None)()
        return reply

    @staticmethod
    def kind(args):
        if args[0] != "dispatch":
            return {("-j", "activewindow"): "activewindow", ("-j", "clients"): "clients", ("-j", "monitors"): "monitors",
                    ("-j", "workspaces"): "workspaces", ("hyprflip", "status"): "status"}[args]
        assert len(args) == 2, args
        if NO_WARP.fullmatch(args[1]) or PLAIN.fullmatch(args[1]):
            return "focus"
        for kind, pattern in (("show", SHOW), ("open", SPECIAL), ("move", MONITOR)):
            if pattern.fullmatch(args[1]):
                return kind
        if match := STEP.fullmatch(args[1]):
            if inner := LAYOUT.fullmatch(match[match.lastindex]):
                return inner[1]
            if RESIZE.fullmatch(match[match.lastindex]):
                return "resize"
        raise AssertionError("Unexpected dispatch: " + args[1])

    def window_focus(self, address):
        """CFocusState::fullWindowFocus."""
        if address in self.unfocusable:
            return
        monitor = self.owner[self.at[address]]
        if self.monitors[monitor][1] not in ("", self.at[address]):
            self.monitors[monitor][1] = ""
        self.keyboard, self.focused, self.last[self.at[address]] = address, monitor, address

    def workspace_focus(self, workspace):
        """Actions::changeWorkspace."""
        if isinstance(workspace, str):
            # A special workspace opens on the focused monitor, and leaves any other.
            for monitor in self.monitors.values():
                if monitor[1] == workspace:
                    monitor[1] = ""
            self.monitors[self.focused][1], self.owner[workspace] = workspace, self.focused
            if workspace in self.last:
                self.window_focus(self.last[workspace])
            return
        came_from, owner = self.focused, self.owner[workspace]
        self.focused = owner
        if self.hide_special:
            self.monitors[owner][1] = ""
        if self.monitors[owner][0] != workspace:
            self.monitors[owner][0] = workspace
            if not self.monitors[owner][1]:
                self.keyboard = None
                if workspace in self.last:
                    self.window_focus(self.last[workspace])
        if came_from != owner:
            if workspace in self.last:
                self.window_focus(self.last[workspace])
            else:
                self.keyboard = None
        # The pointer's simulated motion after a change that leaves no window in focus.
        if self.keyboard is None and self.under_pointer:
            self.focused = self.under_pointer

    def answer(self, *args):
        if args == ("-j", "activewindow"):
            return json.dumps({"address": self.keyboard} if self.keyboard else {})
        if args == ("-j", "clients"):
            return json.dumps([{"address": a} for a in sorted(self.open)])
        if args == ("-j", "monitors"):
            return json.dumps([{"name": name, "focused": name == self.focused, "activeWorkspace": {"id": workspace, "name": str(workspace)},
                                "specialWorkspace": {"id": -98 if special else 0, "name": special}}
                               for name, (workspace, special) in self.monitors.items()])
        if args == ("hyprflip", "status"):
            cards = ([{"faces": [["0xc"], ["0xd"]], "current": "0xc", "box": self.box(), "workspace": {"id": self.at["0xc"]}}]
                     if self.carded else [])
            return json.dumps({"containers": cards})
        if args == ("-j", "workspaces"):
            return json.dumps([{"id": workspace, "hasfullscreen": workspace in self.fullscreen} for workspace in self.owner])
        text = args[1]
        for kind, pattern in (("no warp", NO_WARP), ("plain", PLAIN)):
            if match := pattern.fullmatch(text):
                self.focuses.append((kind, match[1]))
                if match[1] not in self.open:
                    return "warning: window not found"
                workspace = self.at[match[1]]
                if workspace not in self.monitors[self.focused]:
                    self.workspace_focus(workspace)
                self.window_focus(match[1])
                if kind == "plain":
                    self.pointer = self.middle(match[1])
                return "ok"
        if match := SHOW.fullmatch(text):
            self.visits.append(("show", int(match[1])))
            self.workspace_focus(int(match[1]))
            return "ok"
        if match := SPECIAL.fullmatch(text):
            self.visits.append(("open", match[1]))
            self.workspace_focus(match[1])
            return "ok"
        if match := MONITOR.fullmatch(text):
            self.visits.append(("move", match[1]))
            if match[1] != self.focused:
                candidate = self.monitors[match[1]][1] or self.monitors[match[1]][0]
                self.focused = match[1]
                if candidate in self.last:
                    self.window_focus(self.last[candidate])
                else:
                    self.keyboard = None
            return "ok"
        match = STEP.fullmatch(text)
        # The guard: with the focus elsewhere the step does nothing, without an error.
        if self.keyboard in re.findall(MEMBER, text):
            if inner := LAYOUT.fullmatch(match[match.lastindex]):
                if inner[1] == "togglesplit":
                    self.stacked = not self.stacked
                else:
                    self.second = not self.second
            else:
                inner = RESIZE.fullmatch(match[match.lastindex])
                self.short = [self.short[0] - int(inner[1]), self.short[1] - int(inner[2])]
        return "ok"


class SettleTest(unittest.TestCase):
    def settle(self, desktop, line=LINE):
        card_restore.settle(line, ctl=desktop)
        return desktop

    def dispatches(self, desktop):
        return [args[1] for args in desktop.calls if args[0] == "dispatch"]

    def assertNoWarps(self, desktop):
        """Every focus settle sent is the helper's no-warp focus."""
        for text in self.dispatches(desktop):
            if "focus" in text:
                self.assertTrue(any(pattern.fullmatch(text) for pattern in (NO_WARP, SHOW, SPECIAL, MONITOR)), text)
                self.assertFalse(set(text) & set(";[]"), text)
                if match := NO_WARP.fullmatch(text):
                    self.assertEqual(text, Unattended.focus_command(match[1]))

    def test_the_card_gets_the_keyboard_without_a_warp_and_gives_it_back(self):
        desktop = Desktop(keyboard="0xa")
        pointer = desktop.pointer
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        # The window to give the keyboard back to is read before the first focus.
        self.assertLess(desktop.calls.index(("-j", "activewindow")), desktop.calls.index(("dispatch", Unattended.focus_command("0xc"))))
        self.assertEqual(self.dispatches(desktop), [Unattended.focus_command("0xc"), layout("togglesplit"),
                                                    layout("swapsplit"), Unattended.focus_command("0xa")])
        self.assertEqual(desktop.focuses, [("no warp", "0xc"), ("no warp", "0xa")])
        self.assertNoWarps(desktop)
        self.assertEqual((desktop.keyboard, desktop.pointer), ("0xa", pointer))

    def test_no_focus_goes_to_the_window_that_has_the_keyboard(self):
        # The card's app has it: the steps act on it as it is, and it keeps it.
        desktop = Desktop(keyboard="0xc")
        pointer = desktop.pointer
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.focuses, [])
        self.assertEqual((desktop.keyboard, desktop.pointer), ("0xc", pointer))
        # The window that had it has it again by the end, so nothing gives it back.
        desktop = Desktop(keyboard="0xa")
        desktop.after["swapsplit"] = lambda: setattr(desktop, "keyboard", "0xa")
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertEqual((desktop.keyboard, desktop.pointer), ("0xa", pointer))

    def test_the_keyboard_goes_back_only_to_a_window_that_is_still_open(self):
        desktop = Desktop(keyboard="0xa")
        desktop.after["togglesplit"] = lambda: desktop.close("0xa")
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertEqual(desktop.keyboard, "0xc")
        # Nothing had the keyboard: the card keeps it, with no window to look for.
        desktop = self.settle(Desktop(keyboard=None))
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertNotIn(("-j", "clients"), desktop.calls)
        self.assertNoWarps(desktop)

    def test_the_keyboard_goes_back_after_a_failed_step_and_giving_it_back_never_fails_the_card(self):
        desktop = Desktop(keyboard="0xa", short=(40, 0))
        pointer = desktop.pointer
        desktop.refuse = ("resize", RuntimeError("error: refused"))
        with self.assertRaises(RuntimeError):
            self.settle(desktop)
        self.assertEqual(desktop.focuses, [("no warp", "0xc"), ("no warp", "0xa")])
        self.assertNoWarps(desktop)
        self.assertEqual((desktop.keyboard, desktop.pointer), ("0xa", pointer))
        # Hyprland stops answering only once the card is back: settle still succeeds.
        for kind, error in (("clients", RuntimeError("Couldn't read (6)")),
                            ("activewindow", subprocess.TimeoutExpired(["hyprctl"], 10)),
                            ("focus", RuntimeError("error: refused"))):
            with self.subTest(kind=kind):
                desktop = Desktop(keyboard="0xa")
                desktop.after["swapsplit"] = lambda: setattr(desktop, "refuse", (kind, error))
                self.settle(desktop)
                self.assertEqual(desktop.box(), SAVED)
                self.assertEqual(desktop.keyboard, "0xc")
                self.assertEqual(desktop.pointer, pointer)

    def test_giving_it_back_never_fails_the_card_whatever_breaks(self):
        for kind, error in (("clients", ValueError("not JSON")), ("activewindow", ValueError("not JSON")),
                            ("clients", OSError("no hyprctl")), ("activewindow", FileNotFoundError("hyprctl")),
                            ("clients", AttributeError("not a list of objects")), ("activewindow", AttributeError("a list")),
                            ("clients", KeyError("address")), ("clients", TypeError("null"))):
            with self.subTest(kind=kind, error=type(error).__name__):
                desktop = Desktop(keyboard="0xa")
                desktop.after["swapsplit"] = lambda: setattr(desktop, "refuse", (kind, error))
                self.settle(desktop)
                self.assertEqual(desktop.box(), SAVED)
                self.assertEqual(desktop.keyboard, "0xc")

    def test_a_card_that_does_not_take_the_keyboard_stops_before_any_step(self):
        # Each step would act on the window that kept the keyboard, and rearrange it.
        def unfocusable(desktop): desktop.unfocusable.add("0xc")
        def closed(desktop): desktop.open.discard("0xc")
        def refused(desktop): desktop.refuse = ("focus", RuntimeError("error: refused"))
        for how in (unfocusable, closed, refused):
            with self.subTest(how=how.__name__):
                desktop = Desktop(keyboard="0xa", short=(40, 0))
                pointer = desktop.pointer
                how(desktop)
                with self.assertRaises(RuntimeError):
                    self.settle(desktop)
                # Only the card's focus went out: no step, and nothing to give back.
                self.assertEqual(self.dispatches(desktop), [Unattended.focus_command("0xc")])
                self.assertEqual((desktop.keyboard, desktop.pointer), ("0xa", pointer))
        # Another of the card's apps taking it will do: the steps act on the card all the same.
        desktop = Desktop(keyboard="0xa")
        desktop.after["focus"] = lambda: (setattr(desktop, "keyboard", "0xd"), desktop.after.clear())
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.keyboard, "0xa")

    def test_a_keyboard_that_went_elsewhere_during_the_steps_stays_there(self):
        # The user clicked another window, or a new one mapped: it is not pulled back.
        desktop = Desktop(keyboard="0xa")
        pointer = desktop.pointer
        desktop.after["swapsplit"] = lambda: setattr(desktop, "keyboard", "0xb")
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertEqual((desktop.keyboard, desktop.pointer), ("0xb", pointer))

    def test_a_step_that_brings_the_card_no_closer_is_undone(self):
        class Still(Desktop):
            def box(self):
                return [0, 0, 2000, 500]
        desktop = Still(keyboard="0xa")
        # A card that does not come back says so, with no resize from the wrong corner.
        with self.assertRaisesRegex(RuntimeError, "not back in its tile"):
            self.settle(desktop)
        self.assertEqual([text for text in self.dispatches(desktop)[1:-1]],
                         [layout("togglesplit"), layout("togglesplit"), layout("swapsplit"), layout("swapsplit")])
        self.assertEqual(desktop.keyboard, "0xa")

    def test_it_keeps_its_steps_and_its_early_returns(self):
        # A floating card is never corrected: nothing is read or sent.
        desktop = Desktop()
        self.settle(desktop, LINE.replace("tiled", "floating", 1))
        self.assertEqual(desktop.calls, [])
        # A card already in its tile, or no longer open, is read and left alone.
        gone = Desktop()
        gone.carded = False
        for desktop in (Desktop(stacked=False, second=True), gone):
            self.settle(desktop)
            self.assertEqual(desktop.calls, [("hyprflip", "status")])
        # A step stays only when it brings the card closer; then its size comes back.
        desktop = self.settle(Desktop(keyboard="0xa", stacked=True, second=True, short=(40, -20)))
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(self.dispatches(desktop)[1:-1], [
            layout("togglesplit"), layout("swapsplit"), layout("swapsplit"), step("hl.dsp.window.resize({x=40,y=-20,relative=true})")])
        self.assertEqual(desktop.focuses, [("no warp", "0xc"), ("no warp", "0xa")])

    def test_a_hidden_card_shows_its_workspace_only_for_its_steps(self):
        # The keyboard on another workspace of the card's monitor.
        desktop = Desktop(keyboard="0xa").hide()
        pointer, view = desktop.pointer, desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(self.dispatches(desktop), [Unattended.focus_command("0xc"), layout("togglesplit"),
                                                    layout("swapsplit"), Unattended.workspace_command(1)])
        self.assertEqual((desktop.view(), desktop.keyboard, desktop.pointer), (view, "0xa", pointer))
        # What the monitors show is read before the card's focus can change it.
        self.assertLess(desktop.calls.index(("-j", "monitors")), desktop.calls.index(("dispatch", Unattended.focus_command("0xc"))))
        self.assertNoWarps(desktop)

    def test_the_keyboard_on_the_other_monitor_comes_back_with_it(self):
        # Hidden on its own monitor: that monitor goes back, then the focus to the keyboard's.
        desktop = Desktop(keyboard="0xb").hide()
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.visits, [("show", 1), ("move", "HDMI-A-1")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xb"))
        self.assertNoWarps(desktop)
        # Shown on its own monitor: no workspace changes, only the focus goes back.
        desktop = Desktop(keyboard="0xb")
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.visits, [("move", "HDMI-A-1")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xb"))
        # The monitor's last window is another: the keyboard's window gets one focus too.
        desktop = Desktop(keyboard="0xb")
        desktop.open.add("0xf")
        desktop.at["0xf"], desktop.last[2] = 2, "0xf"
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.focuses, [("no warp", "0xc"), ("no warp", "0xb")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xb"))
        # Its window closed meanwhile: the focus still goes back, but no window gets one.
        desktop = Desktop(keyboard="0xb")
        desktop.after["togglesplit"] = lambda: desktop.close("0xb")
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertEqual(desktop.view(), view)
        self.assertEqual(desktop.keyboard, None)

    def test_a_keyboard_on_nothing_comes_back_to_nothing_wherever_it_can(self):
        # An empty workspace on the card's monitor, the card hidden there.
        desktop = Desktop().hide().nothing()
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.visits, [("show", 4)])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, None))
        self.assertNotIn(("-j", "clients"), desktop.calls)
        # An empty workspace on the other monitor, the card shown on its own.
        desktop = Desktop().nothing("HDMI-A-1", 5)
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.visits, [("move", "HDMI-A-1")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, None))
        # The workspace and the card on the same monitor: the card keeps it, as nothing can take it away.
        desktop = Desktop()
        desktop.keyboard = None
        view = desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.visits, [])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xc"))

    def test_a_failed_step_or_a_refused_keyboard_still_puts_the_monitors_back(self):
        desktop = Desktop(keyboard="0xb", short=(40, 0)).hide()
        view = desktop.view()
        desktop.refuse = ("resize", RuntimeError("error: refused"))
        with self.assertRaises(RuntimeError):
            self.settle(desktop)
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xb"))
        # A card that will not focus: Hyprland still shows its workspace first.
        desktop = Desktop(keyboard="0xa").hide()
        desktop.unfocusable.add("0xc")
        view = desktop.view()
        with self.assertRaises(RuntimeError):
            self.settle(desktop)
        self.assertEqual(desktop.visits, [("show", 1)])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xa"))
        self.assertTrue(desktop.stacked)

    def test_a_refused_keyboard_that_went_to_another_window_there_comes_back(self):
        # Showing the card's workspace gave the keyboard to the window last focused
        # there. That was this focus's doing, so it is no reason to leave it.
        for keyboard in ("0xa", "0xb"):
            with self.subTest(keyboard=keyboard):
                desktop = Desktop(keyboard=keyboard).hide(last="0xf")
                desktop.open.add("0xf")
                desktop.unfocusable.add("0xc")
                view = desktop.view()
                with self.assertRaises(RuntimeError):
                    self.settle(desktop)
                self.assertEqual((desktop.view(), desktop.keyboard), (view, keyboard))
                self.assertTrue(desktop.stacked)

    def test_nothing_that_changed_nothing_goes_out(self):
        for desktop in (Desktop(), Desktop(keyboard="0xb"), Desktop().hide().special(), Desktop(keyboard="0xb").special(keyboard=False),
                        Desktop().nothing()):
            with self.subTest(view=desktop.view()):
                card_restore.put_back(desktop, card_restore.shown(desktop))
                self.assertEqual(desktop.visits, [])
                self.assertEqual(desktop.focuses, [])

    def test_a_special_workspace_stays_open(self):
        for hide_special in (False, True):
            with self.subTest(hide_special=hide_special):
                # The keyboard in it, over another workspace of the card's monitor.
                desktop = Desktop().hide().special()
                desktop.hide_special, view = hide_special, desktop.view()
                self.settle(desktop)
                self.assertEqual(desktop.box(), SAVED)
                self.assertEqual(desktop.visits, [("show", 1), ("move", "DP-1"), ("open", "special:pad")])
                self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xe"))
                # The keyboard in it, over the card.
                desktop = Desktop().special()
                desktop.hide_special, view = hide_special, desktop.view()
                self.settle(desktop)
                self.assertEqual(desktop.visits, [("open", "special:pad")])
                self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xe"))
                # The keyboard on the other monitor: the card's focus still closes it.
                desktop = Desktop(keyboard="0xb").hide().special(keyboard=False)
                desktop.hide_special, view = hide_special, desktop.view()
                self.settle(desktop)
                self.assertEqual(desktop.visits, [("show", 1), ("move", "DP-1"), ("open", "special:pad"), ("move", "HDMI-A-1")])
                self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xb"))
                # The keyboard in it, on the other monitor. A focus of its window from
                # the card's monitor would bring the special workspace there.
                desktop = Desktop().hide().special(monitor="HDMI-A-1")
                desktop.hide_special, view = hide_special, desktop.view()
                self.settle(desktop)
                self.assertEqual(desktop.visits, [("show", 1), ("move", "HDMI-A-1")])
                self.assertEqual(desktop.focuses, [("no warp", "0xc")])
                self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xe"))
                self.assertNoWarps(desktop)

    def test_a_special_workspace_opens_again_on_its_own_monitor_with_the_pointer_elsewhere(self):
        # Showing an empty workspace hands the focus to the monitor under the pointer.
        # The special workspace goes back on its own monitor all the same.
        desktop = Desktop().hide().nothing().special()
        desktop.under_pointer, view = "HDMI-A-1", desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.visits, [("show", 4), ("move", "DP-1"), ("open", "special:pad")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xe"))
        self.assertNoWarps(desktop)
        # With the keyboard on the other monitor too, which gets the focus back last.
        desktop = Desktop(keyboard="0xb").hide().nothing().special(keyboard=False)
        desktop.keyboard, desktop.focused = "0xb", "HDMI-A-1"
        desktop.under_pointer, view = "HDMI-A-1", desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.visits, [("show", 4), ("move", "DP-1"), ("open", "special:pad"), ("move", "HDMI-A-1")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xb"))
        # No workspace to change: the focus is on its monitor already, and nothing moves it.
        desktop = Desktop().special()
        desktop.under_pointer, view = "HDMI-A-1", desktop.view()
        self.settle(desktop)
        self.assertEqual(desktop.visits, [("open", "special:pad")])
        self.assertEqual((desktop.view(), desktop.keyboard), (view, "0xe"))

    def test_a_focus_that_moves_during_the_steps_stops_them(self):
        # Whichever step it moved before, the window that took it keeps its tile and
        # the keyboard, and the card that did not come back says so.
        for kind in ("togglesplit", "swapsplit", "resize"):
            with self.subTest(kind=kind):
                # A card to turn and to size, so that each kind of step is due.
                desktop = Desktop(keyboard="0xa", short=(40, 0))
                view = desktop.view()
                desktop.before[kind] = lambda: (setattr(desktop, "keyboard", "0xb"), setattr(desktop, "focused", "HDMI-A-1"))
                with self.assertRaisesRegex(RuntimeError, "not back in its tile"):
                    self.settle(desktop)
                self.assertNotEqual(desktop.box(), SAVED)
                self.assertEqual(desktop.keyboard, "0xb")
                self.assertEqual(desktop.focuses, [("no warp", "0xc")])
                self.assertEqual(desktop.view()[0], view[0])
                self.assertEqual(desktop.visits, [])
                self.assertEqual(desktop.short[0], 40)
        # Every step names the card's own windows, in the one form Hyprland runs whole.
        desktop = Desktop(keyboard="0xa", short=(40, 0))
        self.settle(desktop)
        steps = [text for text in self.dispatches(desktop) if "hl.dsp.focus" not in text]
        self.assertEqual(len(steps), 3)
        for text in steps:
            self.assertEqual(STEP.fullmatch(text)[1], "0xc")
            self.assertEqual(sorted(re.findall(MEMBER, text)), ["0xc", "0xd"])
            self.assertFalse(set(text) & set(";[]"), text)

    def test_a_step_never_raises_when_the_focus_has_left(self):
        # An error from a dispatched function stays in `hyprctl configerrors`, which
        # rolls an update back: the function has no error in it, and does nothing instead.
        self.assertNotIn("error", step('hl.dsp.layout("togglesplit")'))
        desktop = Desktop(keyboard="0xb")
        before = desktop.box()
        self.assertEqual(desktop("dispatch", layout("togglesplit")), "ok")
        self.assertEqual(desktop.box(), before)
        # With nothing in focus, as a lone `window.address` would raise.
        self.assertIn("if window and (", layout("togglesplit"))

    def test_a_step_carries_only_window_addresses(self):
        for members in ({"0xa ; dispatch exit"}, {'0xa" }) hl.dsp.exit() --'}, {None}, {7}, {"address:0xa"}, {"0x" + "a" * 17}, {"0xc", "bad"}):
            with self.subTest(members=members), self.assertRaises(ValueError):
                card_restore.step_command(members, 'hl.dsp.layout("togglesplit")')
        self.assertEqual(card_restore.step_command({"0xd", "0xc"}, "X"),
                         'function() local window = hl.get_active_window() if window and '
                         '(window.address == "0xc" or window.address == "0xd") then hl.dispatch(X) end end')

    def test_a_resize_waits_for_the_card_to_be_back_in_its_corner(self):
        class At(Desktop):
            """A card that no split control moves, a given distance from its saved corner."""
            def __init__(self, x=1000, y=0, short=(0, 0), grows=True):
                super().__init__(keyboard="0xa", short=short)
                self.x, self.y, self.grows = x, y, grows

            def box(self):
                return [self.x, self.y, 1000 - self.short[0], 1000 - self.short[1]]

            def answer(self, *args):
                if self.kind(args) == "resize" and not self.grows:
                    return "ok"
                return super().answer(*args)

        def resizes(desktop):
            return [text for text in self.dispatches(desktop) if "resize" in text]

        # Within four pixels of it, either way, the size comes back.
        for x, y in ((996, 0), (1004, 0), (1000, 4), (1000, -4)):
            with self.subTest(x=x, y=y):
                desktop = At(x=x, y=y, short=(20, -30))
                self.settle(desktop)
                self.assertEqual(resizes(desktop), [step("hl.dsp.window.resize({x=20,y=-30,relative=true})")])
                self.assertEqual(desktop.box(), [x, y, 1000, 1000])
        # Further off a resize would squeeze another neighbour than the one it was measured against.
        for x, y in ((995, 0), (1005, 0), (1000, 5), (1000, -5), (0, 0), (0, 500)):
            with self.subTest(x=x, y=y):
                desktop = At(x=x, y=y, short=(20, -30))
                with self.assertRaisesRegex(RuntimeError, "not back in its tile"):
                    self.settle(desktop)
                self.assertEqual(resizes(desktop), [])
                self.assertEqual(desktop.short, [20, -30])
                self.assertEqual(desktop.keyboard, "0xa")
        # Two pixels of a size stay, as they have from the start, and three go.
        for short, sent in (((2, 0), []), ((0, 2), []), ((-2, -2), []),
                            ((3, 0), [step("hl.dsp.window.resize({x=3,y=0,relative=true})")]),
                            ((-3, 0), [step("hl.dsp.window.resize({x=-3,y=0,relative=true})")]),
                            ((0, 3), [step("hl.dsp.window.resize({x=0,y=3,relative=true})")]),
                            ((0, -3), [step("hl.dsp.window.resize({x=0,y=-3,relative=true})")])):
            with self.subTest(short=short):
                desktop = At(x=997, short=short)
                self.settle(desktop)
                self.assertEqual(resizes(desktop), sent)
        # What it checks last is the whole box, within four pixels of each number.
        for short, fails in (((4, 0), False), ((0, -4), False), ((5, 0), True), ((0, 5), True), ((-5, 0), True), ((0, -5), True)):
            with self.subTest(short=short):
                desktop = At(short=short, grows=False)
                if fails:
                    with self.assertRaisesRegex(RuntimeError, "not back in its tile"):
                        self.settle(desktop)
                else:
                    self.settle(desktop)
                self.assertEqual(desktop.keyboard, "0xa")

    def test_a_fullscreen_window_on_the_cards_workspace_leaves_its_tile_alone(self):
        # Before any focus: a focus under it would take the fullscreen from it or end it.
        for keyboard, hide in (("0xa", False), ("0xb", False), ("0xb", True)):
            with self.subTest(keyboard=keyboard, hide=hide):
                desktop = Desktop(keyboard=keyboard)
                if hide:
                    desktop.hide()
                desktop.fullscreen.add(desktop.at["0xc"])
                view = desktop.view()
                with self.assertRaises(card_restore.FullscreenWindow):
                    self.settle(desktop)
                self.assertEqual(self.dispatches(desktop), [])
                self.assertEqual((desktop.view(), desktop.keyboard), (view, keyboard))
                self.assertTrue(desktop.stacked)
        # It is a RuntimeError, so that nothing else has to know.
        self.assertTrue(issubclass(card_restore.FullscreenWindow, RuntimeError))
        # A fullscreen window on another workspace changes nothing, on either monitor.
        for workspace in (2, 3):
            with self.subTest(workspace=workspace):
                desktop = Desktop(keyboard="0xa")
                desktop.fullscreen.add(workspace)
                self.settle(desktop)
                self.assertEqual(desktop.box(), SAVED)
        # A card that needs nothing never asks.
        desktop = Desktop(stacked=False, second=True)
        desktop.fullscreen.add(1)
        self.settle(desktop)
        self.assertNotIn(("-j", "workspaces"), desktop.calls)
        # Saved under such a window, the tile reads as no size: there is nothing to go back to, whatever the card reads now.
        for zeros in ("0 0 0 0", "1000 0 0 1000", "1000 0 1000 0"):
            with self.subTest(zeros=zeros):
                desktop = Desktop(keyboard="0xa")
                self.settle(desktop, LINE.replace("1000 0 1000 1000", zeros))
                self.assertEqual(desktop.calls, [("hyprflip", "status")])
                self.assertTrue(desktop.stacked)
        # What the workspaces are can't be read: nothing goes out.
        desktop = Desktop(keyboard="0xa")
        desktop.refuse = ("workspaces", RuntimeError("Couldn't read (6)"))
        with self.assertRaises(RuntimeError):
            self.settle(desktop)
        self.assertEqual(self.dispatches(desktop), [])

    def test_a_card_that_needs_nothing_reads_nothing_but_its_box(self):
        # Hyprland failing to say where the keyboard is is no fault of a card already in its tile.
        for kind in ("activewindow", "monitors", "workspaces", "clients"):
            with self.subTest(kind=kind):
                desktop = Desktop(stacked=False, second=True)
                desktop.refuse = (kind, RuntimeError("Couldn't read (6)"))
                self.settle(desktop)
                self.assertEqual(desktop.calls, [("hyprflip", "status")])
        # Up to four pixels, summed over the whole box, is nothing.
        class Off(Desktop):
            off = 0

            def box(self):
                return [1000 + self.off, 0, 1000, 1000]
        for off, reads in ((4, False), (-4, False), (5, True), (-5, True)):
            with self.subTest(off=off):
                desktop = Off(keyboard="0xa")
                desktop.off = off
                try:
                    self.settle(desktop)
                except RuntimeError:
                    pass
                self.assertEqual(("-j", "activewindow") in desktop.calls, reads)

    def test_a_keyboard_that_could_not_be_read_stops_before_any_focus(self):
        desktop = Desktop(keyboard="0xa")
        desktop.refuse = ("activewindow", RuntimeError("Couldn't read (6)"))
        with self.assertRaises(RuntimeError):
            self.settle(desktop)
        self.assertEqual(self.dispatches(desktop), [])
        self.assertTrue(desktop.stacked)

    def test_a_monitor_it_could_not_put_back_leaves_the_card_where_it_is(self):
        # A focus by number reaches no named workspace. Nothing goes out, so nothing changes.
        def named(desktop): desktop.monitors["DP-1"][0] = -1337
        def zero(desktop): desktop.monitors["DP-1"][0] = 0
        def text(desktop): desktop.monitors["DP-1"][0] = "1 }) hl.dsp.exit() --"
        def missing(desktop): desktop.monitors["HDMI-A-1"][0] = None
        def special(desktop): desktop.monitors["DP-1"][1] = 'special:" hl.dsp.exit() --'
        def monitor(desktop): desktop.monitors['DP"-1'] = desktop.monitors.pop("HDMI-A-1")
        for how in (named, zero, text, missing, special, monitor):
            with self.subTest(how=how.__name__):
                desktop = Desktop(keyboard="0xa").hide()
                how(desktop)
                with self.assertRaises(ValueError):
                    self.settle(desktop)
                self.assertEqual(self.dispatches(desktop), [])
                self.assertEqual(desktop.keyboard, "0xa")
                self.assertTrue(desktop.stacked)
        # What the monitors show can't be read at all: the same.
        for error in (RuntimeError("Couldn't read (6)"), ValueError("not JSON")):
            desktop = Desktop(keyboard="0xa").hide()
            desktop.refuse = ("monitors", error)
            with self.assertRaises(type(error)):
                self.settle(desktop)
            self.assertEqual(self.dispatches(desktop), [])
        # A card already in its tile never needs to know.
        desktop = Desktop(stacked=False, second=True)
        named(desktop)
        self.settle(desktop)
        self.assertNotIn(("-j", "monitors"), desktop.calls)

    def test_what_someone_else_changed_stays(self):
        # Another monitor changed during the steps: no focus of this one's did it.
        desktop = Desktop(keyboard="0xa").hide()
        desktop.after["togglesplit"] = lambda: desktop.monitors["HDMI-A-1"].__setitem__(0, 5)
        self.settle(desktop)
        self.assertEqual(desktop.visits, [("show", 1)])
        self.assertEqual(desktop.monitors["HDMI-A-1"], [5, ""])
        self.assertEqual(desktop.keyboard, "0xa")
        # A keyboard someone took during the steps: the monitors stay as they are too.
        desktop = Desktop(keyboard="0xa").hide()
        desktop.after["swapsplit"] = lambda: setattr(desktop, "keyboard", "0xb")
        self.settle(desktop)
        self.assertEqual(desktop.visits, [])
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertEqual(desktop.monitors["DP-1"], [3, ""])
        self.assertEqual(desktop.keyboard, "0xb")
        # A special workspace that closes by itself is reopened only where it was open.
        desktop = Desktop(keyboard="0xb").hide()
        self.settle(desktop)
        self.assertNotIn("open", [kind for kind, _ in desktop.visits])

    def test_a_monitor_that_went_away_is_left_out(self):
        # The keyboard's monitor: nothing moves the focus to it, and its window still gets the keyboard.
        desktop = Desktop(keyboard="0xb")
        desktop.after["togglesplit"] = lambda: (desktop.monitors.pop("HDMI-A-1"), desktop.owner.__setitem__(2, "DP-1"))
        self.settle(desktop)
        self.assertEqual(desktop.box(), SAVED)
        self.assertEqual(desktop.visits, [])
        self.assertEqual(desktop.focuses, [("no warp", "0xc"), ("no warp", "0xb")])
        # The card's monitor: its workspace went to the other one, and the keyboard goes back there.
        desktop = Desktop(keyboard="0xb").hide()
        def gone():
            desktop.monitors.pop("DP-1")
            desktop.owner.update({1: "HDMI-A-1", 3: "HDMI-A-1"})
            desktop.focused = "HDMI-A-1"
        desktop.after["togglesplit"] = gone
        self.settle(desktop)
        self.assertEqual(desktop.visits, [])
        self.assertEqual(desktop.keyboard, "0xb")
        # A monitor that only now has the focus was never read: nothing goes back on it.
        desktop = Desktop(keyboard="0xa")
        def arrived():
            desktop.monitors["DP-2"] = [7, ""]
            desktop.focused = "DP-2"
        desktop.after["togglesplit"] = arrived
        self.settle(desktop)
        self.assertEqual(desktop.visits, [("move", "DP-1")])

    def test_a_window_that_takes_no_input_gets_no_focus(self):
        # An app on a card's hidden side: a focus would turn the card to it.
        class Hidden(Desktop):
            def answer(self, *args):
                if args == ("-j", "clients"):
                    return json.dumps([{"address": "0xc", "acceptsInput": True}, {"address": "0xd", "acceptsInput": False}])
                return super().answer(*args)
        desktop = Hidden(keyboard="0xc")
        card_restore.give_back(desktop, "0xd", {"0xc", "0xd"})
        self.assertEqual(desktop.focuses, [])
        self.assertEqual(desktop.keyboard, "0xc")
        # One that takes it gets it.
        desktop = Hidden(keyboard="0xd")
        card_restore.give_back(desktop, "0xc", {"0xc", "0xd"})
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])

    def test_giving_it_back_with_the_monitors_never_fails_the_card_whatever_breaks(self):
        class Bad(Desktop):
            shape = None

            def answer(self, *args):
                if args == ("-j", "monitors") and self.shape:
                    return self.shape
                return super().answer(*args)
        kinds = [("monitors", RuntimeError("Couldn't read (6)")), ("monitors", OSError("no hyprctl")),
                 ("monitors", subprocess.TimeoutExpired(["hyprctl"], 10)), ("show", RuntimeError("error: refused")),
                 ("open", subprocess.TimeoutExpired(["hyprctl"], 10)), ("move", OSError("no hyprctl"))]
        for kind, error in kinds:
            with self.subTest(kind=kind, error=type(error).__name__):
                desktop = Desktop(keyboard="0xb").hide().special(keyboard=False)
                desktop.after["swapsplit"] = lambda: setattr(desktop, "refuse", (kind, error))
                self.settle(desktop)
                self.assertEqual(desktop.box(), SAVED)
        # Hyprland answers with something it never says.
        for shape in ("not JSON", "null", "[1]", '[{"name": "DP-1"}]', '[{"name": "DP-1", "focused": true, "activeWorkspace": null}]'):
            with self.subTest(shape=shape):
                desktop = Bad(keyboard="0xb").hide()
                desktop.after["swapsplit"] = lambda: setattr(desktop, "shape", shape)
                self.settle(desktop)
                self.assertEqual(desktop.box(), SAVED)

    def test_remembering_the_keyboard_never_fails_the_update(self):
        desktop = Desktop(keyboard="0xb")
        self.assertEqual(card_restore.remember(desktop), ("0xb", desktop.view()))
        self.assertEqual(desktop.calls, [("-j", "activewindow"), ("-j", "monitors")])
        for kind, error in (("activewindow", RuntimeError("Couldn't read (6)")), ("monitors", ValueError("not JSON")),
                            ("monitors", subprocess.TimeoutExpired(["hyprctl"], 10)), ("activewindow", OSError("no hyprctl"))):
            with self.subTest(kind=kind):
                desktop = Desktop()
                desktop.refuse = (kind, error)
                self.assertIsNone(card_restore.remember(desktop))

    def test_the_keyboard_an_unload_dropped_goes_back_without_a_warp(self):
        ours = {"0xc", "0xd"}
        desktop = Desktop(keyboard="0xc")
        pointer, place = desktop.pointer, card_restore.remember(desktop)
        desktop.keyboard = None
        card_restore.return_keyboard(desktop, place, ours)
        self.assertEqual(desktop.focuses, [("no warp", "0xc")])
        self.assertEqual((desktop.keyboard, desktop.pointer), ("0xc", pointer))
        self.assertNoWarps(desktop)
        # It is there, or on another of the card's apps: the first needs nothing, the second one focus.
        for now, focuses in (("0xc", []), ("0xd", [("no warp", "0xc")])):
            desktop = Desktop(keyboard="0xc")
            place = card_restore.remember(desktop)
            desktop.keyboard = now
            card_restore.return_keyboard(desktop, place, ours)
            self.assertEqual(desktop.focuses, focuses)
            self.assertEqual(desktop.keyboard, "0xc")

    def test_the_keyboard_stays_with_whoever_moved_something_during_the_update(self):
        ours = {"0xc", "0xd"}
        # Someone took the keyboard.
        desktop = Desktop(keyboard="0xc")
        place = card_restore.remember(desktop)
        desktop.keyboard = "0xa"
        card_restore.return_keyboard(desktop, place, ours)
        self.assertEqual((desktop.focuses, desktop.keyboard), ([], "0xa"))
        # Someone went to an empty workspace, or the focus moved to the other monitor.
        for change in (lambda d: d.nothing(), lambda d: d.nothing("HDMI-A-1", 5), lambda d: d.special(keyboard=False)):
            desktop = Desktop(keyboard="0xc")
            place = card_restore.remember(desktop)
            desktop.keyboard = None
            change(desktop)
            calls = len(desktop.calls)
            card_restore.return_keyboard(desktop, place, ours)
            self.assertEqual(desktop.focuses, [])
            self.assertEqual(desktop.calls[calls:], [("-j", "monitors")])
        # Its window closed, or never was one, or nothing was remembered: no focus, and no error.
        desktop = Desktop(keyboard="0xc")
        place = card_restore.remember(desktop)
        desktop.keyboard = None
        desktop.close("0xc")
        card_restore.return_keyboard(desktop, place, ours)
        self.assertEqual((desktop.focuses, desktop.keyboard), ([], None))
        desktop = Desktop().nothing()
        place = card_restore.remember(desktop)
        card_restore.return_keyboard(desktop, place, ours)
        self.assertEqual(self.dispatches(desktop), [])
        desktop = Desktop()
        card_restore.return_keyboard(desktop, None, ours)
        self.assertEqual(desktop.calls, [])

    def test_giving_the_keyboard_back_after_an_update_never_raises(self):
        ours = {"0xc", "0xd"}
        for kind, error in (("monitors", RuntimeError("Couldn't read (6)")), ("monitors", ValueError("not JSON")),
                            ("activewindow", OSError("no hyprctl")), ("clients", KeyError("address")),
                            ("focus", subprocess.TimeoutExpired(["hyprctl"], 10))):
            with self.subTest(kind=kind):
                desktop = Desktop(keyboard="0xc")
                place = card_restore.remember(desktop)
                desktop.keyboard = None
                desktop.refuse = (kind, error)
                card_restore.return_keyboard(desktop, place, ours)
                self.assertEqual(desktop.keyboard, None)

    def test_as_it_was_compares_the_keyboard_and_what_each_monitor_shows(self):
        place = card_restore.remember(Desktop(keyboard="0xa"))
        self.assertTrue(card_restore.as_it_was(Desktop(keyboard="0xa"), place))
        # Which monitor has the focus is left out: giving the keyboard back can bring it along.
        desktop = Desktop(keyboard="0xa")
        desktop.focused = "HDMI-A-1"
        self.assertTrue(card_restore.as_it_was(desktop, place))
        # The keyboard elsewhere, or on nothing.
        self.assertFalse(card_restore.as_it_was(Desktop(keyboard="0xb"), place))
        desktop = Desktop(keyboard="0xa")
        desktop.keyboard = None
        self.assertFalse(card_restore.as_it_was(desktop, place))
        # Another workspace shown, a special workspace opened or closed, a monitor gone.
        desktop = Desktop(keyboard="0xa")
        desktop.monitors["HDMI-A-1"][0] = 5
        self.assertFalse(card_restore.as_it_was(desktop, place))
        desktop = Desktop(keyboard="0xa").special(keyboard=False)
        self.assertFalse(card_restore.as_it_was(desktop, place))
        desktop = Desktop(keyboard="0xa")
        del desktop.monitors["HDMI-A-1"]
        self.assertFalse(card_restore.as_it_was(desktop, place))
        # Hyprland won't say now, or would not say before: that is not as it was.
        for kind in ("activewindow", "monitors"):
            desktop = Desktop(keyboard="0xa")
            desktop.refuse = (kind, RuntimeError("Couldn't read (6)"))
            self.assertFalse(card_restore.as_it_was(desktop, place))
        self.assertFalse(card_restore.as_it_was(Desktop(keyboard="0xa"), None))

    def test_the_apps_of_a_description(self):
        self.assertEqual(card_restore.apps("tiled 0 0 10 20 800 600 front horizontal 0xc 0xc:1 back vertical 0xe 0xd:0.7 0xe:0.3"),
                         {"0xc", "0xd", "0xe"})

    def test_each_focus_carries_only_what_it_says(self):
        commands = {Unattended.workspace_command(97): "workspace = 97", Unattended.special_command("special:pad-terminal"):
                    'workspace = "special:pad-terminal"', Unattended.monitor_command("HDMI-A-1"): 'monitor = "HDMI-A-1"',
                    Unattended.focus_command("0x5d"): 'window = "address:0x5d"'}
        for command, target in commands.items():
            self.assertEqual(command, Unattended.no_warp("hl.dsp.focus({ " + target + " })"))
            # One request Hyprland runs whole, which a batch could carry too.
            self.assertFalse(set(command) & set(";[]"), command)
        self.assertEqual(Unattended.workspace_command(1), Unattended.no_warp("hl.dsp.focus({ workspace = 1 })"))
        self.assertEqual(Unattended.workspace_command(2 ** 31 - 1), Unattended.no_warp("hl.dsp.focus({ workspace = 2147483647 })"))
        # A focus of a workspace by number carries an integer and nothing else. Hyprland
        # reads a negative one as an offset, and below 1 as 1, so a named workspace's id can't pass.
        for number in (0, -1, -1337, -98, 2 ** 31, None, True, False, 1.0, "1", "97", "1 }) hl.dsp.exit() --", "name:a", [1], {}):
            with self.subTest(number=number), self.assertRaises(ValueError):
                Unattended.workspace_command(number)
        for name in ("pad", "special:", "special:a b", 'special:a"', "special:a;b", "special:a]", "special:[a", "special:" + "a" * 57, None, 1, "name:a"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Unattended.special_command(name)
        # Hyprland reads a lone letter or a number as a direction or an id.
        for name in ("l", "3", "-1", "+1", "desc:x", 'a"', "DP-1;", "DP[1]", "DP 1", "a" * 57, None, 1):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Unattended.monitor_command(name)

    def test_a_focus_carries_only_a_window_address(self):
        desktop = Desktop()
        for address in (None, 7, "0xa ; dispatch exit", 'address:0xa', '0xa"}) hl.dsp.exit() --', "0x" + "a" * 17):
            with self.assertRaises(ValueError):
                card_restore.focus(desktop, address)
        self.assertEqual(desktop.calls, [])


if __name__ == "__main__":
    unittest.main()
