#!/usr/bin/env python3
"""Describe open native cards for the core's restore action, and put a restored
tiled card back in its tile. Used by scripts/install.py."""
import json
import re
import subprocess

# workflow.py sits beside this file in every checkout install.py runs from.
from workflow import Unattended

# A window address as Hyprland prints it: the only text a focus or a step here carries.
ADDRESS = re.compile(r"0x[0-9a-fA-F]{1,16}")


class FullscreenWindow(RuntimeError):
    """A window on the card's workspace is fullscreen, so its tile is left alone."""


def ctl(*args):
    p = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout.strip()


def describe(card):
    """A native card as the core's restore action expects it."""
    x, y, width, height = card["box"]
    line = [("floating" if card.get("floating") else "tiled"), str(card["active"]), str(int(bool(card.get("unfolded")))),
            f"{x:.12g}", f"{y:.12g}", f"{width:.12g}", f"{height:.12g}"]
    # Faces after the back are written as face, in order.
    words = ["front", "back"] + ["face"] * (len(card["faces"]) - 2)
    for name, face, layout in zip(words, card["faces"], card["layouts"]):
        line += [name, layout["axis"], layout["focused"]] + [f"{w}:{r:.12g}" for w, r in zip(face, layout["ratios"])]
    return " ".join(line)


def active(ctl):
    """The address of the window that has the keyboard, or None."""
    return json.loads(ctl("-j", "activewindow")).get("address")


def window_address(address):
    if not isinstance(address, str) or not ADDRESS.fullmatch(address):
        raise ValueError("Not a window address.")
    return address


def focus(ctl, address):
    """Gives a window the keyboard and leaves the pointer where it is.

    Hyprland's focus puts the pointer in the middle of the window it focuses.
    This sends the helper's focus instead: one request that turns pointer warps
    off for itself alone.
    """
    ctl("dispatch", Unattended.focus_command(window_address(address)))


def step_command(members, dispatcher):
    """A dispatcher that acts on the focused window, sent so that it acts only while one of the card's apps has the keyboard.

    Dwindle's split controls and the resize name no window, so after a focus that
    moved in the middle of a correction they would rearrange that window's tile.
    Hyprland runs this one function whole, with nothing between its read of the
    focus and the dispatcher. If the focus left it does nothing: an error here
    stays in `hyprctl configerrors`, which rolls an update back. It has no ';',
    '[' or ']'.
    """
    return ('function() local window = hl.get_active_window() if window and (' +
            ' or '.join(f'window.address == "{window_address(address)}"' for address in sorted(members)) +
            ') then hl.dispatch(' + dispatcher + ') end end')


def shown(ctl):
    """What the monitors show: for each by name, its workspace's id and its open special workspace's name, then the focused one's name."""
    monitors = json.loads(ctl("-j", "monitors"))
    return ({m["name"]: (m["activeWorkspace"]["id"], m["specialWorkspace"]["name"]) for m in monitors},
            next((m["name"] for m in monitors if m.get("focused")), None))


def put_back(ctl, before):
    """Puts back what a focus changed: what the monitor it left focused shows, then which monitor has the focus.

    A focus changes only the monitor it leaves focused, so another monitor that
    changed was changed by someone else, and stays. A monitor that went away is
    left out.
    """
    monitors, focused = before
    now = shown(ctl)
    if now[1] in monitors:
        workspace, special = monitors[now[1]]
        changed = now[0][now[1]][0] != workspace
        if changed:
            ctl("dispatch", Unattended.workspace_command(workspace))
        # Focusing a window under a special workspace closes it, and so can changing the workspace under it.
        if special and now[0][now[1]][1] != special:
            # Showing an empty workspace hands the focus to the monitor under the
            # pointer, and a special workspace opens on the monitor that has it.
            if changed:
                ctl("dispatch", Unattended.monitor_command(now[1]))
            ctl("dispatch", Unattended.special_command(special))
    if focused != now[1] and focused in now[0]:
        ctl("dispatch", Unattended.monitor_command(focused))


def give_back(ctl, address, ours, before=None):
    """After a focus of the card's apps, puts the monitors back and gives the keyboard back to the window that had it. Never raises.

    A keyboard the user or a new window took meanwhile stays where it is, and so
    does everything else. The window that has the keyboard already gets no focus
    at all, and neither does one that is closed or does not take input, such as
    an app on a card's hidden side, which a focus would turn the card to.
    """
    try:
        now = active(ctl)
        if now is not None and now != address and now not in ours:
            return
        if before:
            put_back(ctl, before)
        if address is None or active(ctl) == address:
            return
        window = next((w for w in json.loads(ctl("-j", "clients")) if w.get("address") == address), None)
        if window and window.get("acceptsInput", True):
            focus(ctl, address)
    except Exception:
        # Where the keyboard ends up never decides whether the card was kept.
        pass


def apps(line):
    """The windows a card description names."""
    return {token.split(":")[0] for token in line.split() if ":" in token}


def remember(ctl):
    """Where the keyboard is and what the monitors show, before an unload can drop the keyboard. None if Hyprland won't say."""
    try:
        return active(ctl), shown(ctl)
    except Exception:
        return None


def return_keyboard(ctl, remembered, ours):
    """Gives the keyboard back to the window that had it before the unload. Never raises.

    Not when a monitor changed since: someone is at the desk, and the keyboard
    follows them.
    """
    try:
        if remembered and shown(ctl) == remembered[1]:
            give_back(ctl, remembered[0], ours)
    except Exception:
        pass


def as_it_was(ctl, remembered):
    """Whether the keyboard and what each monitor shows are as remembered. Never raises.

    Which monitor has the focus is left out: with the pointer on another monitor
    than the keyboard, a focus that gives the keyboard back brings it along.
    """
    now = remember(ctl)
    return bool(now and remembered) and now[0] == remembered[0] and now[1][0] == remembered[1][0]


def settle(line, ctl=ctl):
    """Return a restored tiled card to its saved tile, leaving the keyboard, the pointer and the monitors as they were.

    While a tiled card is briefly separate tiles, dwindle can reflow the
    workspace: a card beside a neighbour may come back stacked under it. Undo
    that with dwindle's own controls, keeping a step only if it brings the
    card closer to where it was, then restore its size. These act on the
    focused window, so the card's window gets the keyboard for them unless it
    has it already, which shows its workspace if that is hidden and moves the
    focus to its monitor. Afterwards, also when a step fails, the monitors and
    the keyboard go back. None of these focuses moves the pointer. A card that
    needs none of this reads nothing but its own box.

    Raises before any focus when a monitor could not be put back or a window on
    the card's workspace is fullscreen, before any step when the card does not
    take the keyboard, as a step would act on another window, and afterwards when
    the card is not back, as when the keyboard left it in the middle of the steps,
    which then stays with whoever took it.
    """
    parts = line.split()
    if parts[0] != "tiled":
        return
    target = [float(v) for v in parts[3:7]]
    members = apps(line)

    def card():
        return next((c for c in json.loads(ctl("hyprflip", "status")).get("containers", [])
                     if {a for face in c["faces"] for a in face} == members), None)

    def distance():
        found = card()
        return sum(abs(p - q) for p, q in zip(found["box"], target)) if found else None

    best = distance()
    # A tile rebuilt under a fullscreen window reads as no size until that ends: then there is no saved tile to go back to.
    if best is None or best <= 4 or not (target[2] and target[3]):
        return
    found = card()
    current = found["current"]
    # Before any focus: where the keyboard goes back to, and what the monitors show.
    had = active(ctl)
    before = shown(ctl)
    # A focus by number reaches no named workspace: leave the tile rather than the monitor.
    for name, (workspace, special) in before[0].items():
        Unattended.monitor_command(name)
        Unattended.workspace_command(workspace)
        if special:
            Unattended.special_command(special)
    # A focus under a fullscreen window takes the fullscreen from it or ends it, and the card's box says little there.
    if any(w["id"] == found["workspace"]["id"] and w["hasfullscreen"] for w in json.loads(ctl("-j", "workspaces"))):
        raise FullscreenWindow("A window on the card's workspace is fullscreen.")
    ours = set(members)
    try:
        if current != had:
            focus(ctl, current)
            # Hyprland answers ok and leaves the keyboard alone for a window it
            # will not focus: a modal child, a lock screen, a no_focus rule. Showing
            # the card's workspace can still have moved it to another window there.
            now = active(ctl)
            if now not in members:
                ours.add(now)
                raise RuntimeError("The card did not take the keyboard.")
        for message in ("togglesplit", "swapsplit"):
            ctl("dispatch", step_command(members, f'hl.dsp.layout("{message}")'))
            now = distance()
            if now is not None and now < best - 1:
                best = now
            else:
                ctl("dispatch", step_command(members, f'hl.dsp.layout("{message}")'))
        x, y, width, height = card()["box"]
        # A card that is not back in its corner has another neighbour than its size
        # was measured against: a resize from there squeezes that one to a sliver.
        if abs(target[0] - x) <= 4 and abs(target[1] - y) <= 4 and (abs(target[2] - width) > 2 or abs(target[3] - height) > 2):
            ctl("dispatch", step_command(members, f'hl.dsp.window.resize({{x={round(target[2] - width)},y={round(target[3] - height)},relative=true}})'))
        if any(abs(p - q) > 4 for p, q in zip(card()["box"], target)):
            raise RuntimeError("The card is not back in its tile.")
    finally:
        give_back(ctl, had, ours, before)
