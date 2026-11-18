#!/usr/bin/env python3
"""Install the built plugin and its Lua shortcuts for this user, with backups."""
import argparse
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
project = Path(__file__).resolve().parent.parent
source = project / "build/hyprflip.so"
home = Path.home()
library = home / ".local/lib/hyprflip/hyprflip.so"
recovery = library.with_suffix(".upgrade.json")
state_dir = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / "hyprflip"
# While it exists and its pid lives, a program that keeps cards (OmaRelay) leaves them alone: the update is
# taking them apart and building them again. See docs/SCRIPTING.md, Updates and the programs that keep cards.
marker = state_dir / "updating"
# What became of the cards, written just before the marker goes.
result = state_dir / "update-result.json"
config_root = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "hypr"
module = config_root / "hyprflip.lua"
main = config_root / "hyprland.lua"
version = re.search(r"project\(hyprflip VERSION ([\d.]+)", (project / "CMakeLists.txt").read_text()).group(1)
if not source.is_file() or not main.is_file():
    raise SystemExit("Build with make first; this installer requires an existing Hyprland Lua configuration.")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from card_restore import (FullscreenWindow, alone, apps, as_it_was, cover_again, describe, owner, remember,  # noqa: E402
                          return_keyboard, settle, uncover, without_owner)


def ctl(*args):
    p = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout.strip()


def answer(*args):
    # The plugin's reply, a refusal included: Hyprland 0.56's hyprctl exits 7
    # when the reply is an error. hyprctl's own failures to reach Hyprland
    # (exits 1-6, such as no answer within its 5 s), a timeout or a missing
    # hyprctl still raise.
    p = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10)
    if p.returncode and not (p.returncode == 7 and p.stdout.startswith("error")):
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout.strip()

binds = json.loads(ctl("-j", "binds"))
keys = {"M", "P", "TAB", "U", "ESCAPE"}
conflicts = [b for b in binds if b["modmask"] == 76 and b["key"].upper() in keys
             and not b.get("description", "").startswith("Hyprflip:")]
if conflicts:
    raise SystemExit("Shortcut conflict; adjust examples/hyprflip.lua before installing: " + json.dumps(conflicts))

print(f"Plugin: {library}\nShortcuts: {module}\nLoad from: {main}")
print("Super+Ctrl+Alt with M=mark, P=pair, Tab=change face, U=unpair, Escape=cancel")
installed = any(p["name"] == "hyprflip" for p in json.loads(ctl("-j", "plugin", "list")))
installed_state = json.loads(ctl("hyprflip", "status")) if installed else {}


def parked(card):
    return bool(card.get("workspace", {}).get("special"))


def shown(containers):
    # The cards a monitor can show. A parked card never has a cover: it leaves it behind.
    return [card for card in containers if not parked(card)]


def keepable(containers):
    # The cards an update rebuilds: the core rebuilds a parked one on its special workspace. A parked card
    # that is fullscreen stays as separate windows there, for the program that parked it.
    return [card for card in containers if not (parked(card) and card.get("fullscreen"))]


containers = installed_state.get("containers", [])
cards = shown(containers)
if any(not card.get("native_group") for card in cards):
    raise SystemExit("Cards from the retired hy3 provider are open. Take them apart with Super+Ctrl+Alt+U, "
                     "then update; this installer keeps native pairs and dwindle and floating cards.")
if any(card.get("fullscreen") for card in cards):
    raise SystemExit("Leave fullscreen on every card before updating; open cards are kept through the update.")
saved_pairs = installed_state.get("pairs", [])
# A window a program put over a card comes off it for the update and goes back
# on after, as the card's description names only the card's own apps. A card
# with one face of its own under its cover is no card without it: it keeps its
# cover, which its description names, and is restored under it.
covering = installed_state.get("card_cover")
kept_cards = keepable(containers)
saved_cards = [describe(card) for card in kept_cards]
saved_covers = []
if not saved_pairs and not containers and recovery.is_file():
    pending = json.loads(recovery.read_text())
    if pending.get("instance") == os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        saved_pairs = pending.get("pairs", [])
        saved_cards = pending.get("cards", [])
        saved_covers = pending.get("covers", [])
if saved_pairs:
    print(f"Preserving {len(saved_pairs)} existing pair(s) through this update.")
if saved_cards:
    hidden = sum(1 for card in kept_cards if parked(card))
    print(f"Keeping {len(saved_cards)} open card(s) through this update" +
          (f", {hidden} of them parked out of sight" if hidden else "") + ".")
def restored_under(item, lines):
    """Whether a card's description names its cover, so that the restore builds it under the cover again."""
    return any(line.split()[-2:] == ["cover", item["cover"]] for line in lines)


covers = (sum(1 for item in saved_covers if not restored_under(item, saved_cards)) if saved_covers else
          sum(1 for card in cards if covering and card.get("cover") and not alone(card)))
if covers:
    print(f"Taking the cover off {covers} card(s) for this update, and putting it back after.")
if len(kept_cards) < len(containers):
    # Named for the program that manages them, when they say which (card_owner).
    owners = sorted({card["owner"] for card in containers if card not in kept_cards and isinstance(card.get("owner"), str)})
    print(f"Leaving {len(containers) - len(kept_cards)} hidden card(s) as separate windows; " +
          (f"{' and '.join(owners)} rebuilds them." if owners else "the program that parked them rebuilds them."))
if args.dry_run:
    raise SystemExit(0)


def release_name():
    """The release this checkout is, as bootstrap.py records it, else the plugin's version."""
    if (project / ".git").exists():
        found = subprocess.run(["git", "-C", str(project), "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
                               capture_output=True, text=True, timeout=10)
        tag = found.stdout.strip()[1:]
        if not found.returncode and re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+)?", tag):
            return tag
    return version


def hold_lock():
    """The card helper's request lock, held for the whole update so that card menus and unattended requests
    wait, or None outside a Hyprland session. Raises SystemExit, before anything changes, when it stays taken."""
    runtime, instance = os.environ.get("XDG_RUNTIME_DIR"), os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not runtime or not instance:
        return None
    from workflow import Busy, Request
    held = contextlib.ExitStack()
    try:
        held.enter_context(Request(Path(runtime), instance).exclusive(10))
    except Busy:
        raise SystemExit("A card menu or another program is changing cards. Close the menu or wait for it, "
                         "then update again; nothing was changed.") from None
    return held


release = release_name()
lock = hold_lock()

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
originals = {p: p.read_bytes() if p.exists() else None for p in (library, module, main)}
for path, content in originals.items():
    if content is not None:
        backup = path.with_name(path.name + ".bak-" + stamp)
        shutil.copy2(path, backup)
        print("Backup:", backup)

def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".hyprflip-new")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def report(outcome, lines):
    """Writes update-result.json: whether the update installed, how many cards were kept, and each card that came
    apart with its apps as they are now. Never raises."""
    try:
        windows = {w["address"]: w for w in json.loads(ctl("-j", "clients"))}
        apart = []
        for members, manager in ([(sorted(apps(line)), owner(line)) for line in lines if line not in outcome["kept"]]
                                 if outcome["changed"] else []) + outcome["left"]:
            present = [a for a in members if a in windows]
            if present:
                apart.append({"workspace": windows[present[0]].get("workspace", {}).get("name", ""), "owner": manager,
                              "apps": [{"address": a, "pid": windows[a].get("pid"), "class": windows[a].get("class", "")}
                                       for a in present]})
        kept = len(outcome["kept"]) if outcome["changed"] else len(lines)
        atomic(result, json.dumps({"release": release, "finished_ms": int(time.time() * 1000), "ok": outcome["ok"],
                                   "kept": kept, "apart": apart}).encode())
    except Exception:
        pass


def marks_owners():
    """Whether the core loaded now takes a card's owner (card_owner)."""
    try:
        return json.loads(ctl("hyprflip", "status")).get("card_owner") is True
    except (ValueError, AttributeError, RuntimeError, OSError):
        return False


def keep(line, form="restore "):
    # A card whose apps closed or changed meanwhile stays as separate windows,
    # and the other cards are still kept. A core without owners, such as the
    # older one a rollback goes back to, keeps the card unmarked.
    manager = owner(line)
    reply = answer("hyprflip", form + (line if manager is None or marks_owners() else without_owner(line)))
    if not reply.startswith("ok:"):
        print("Could not keep a card" + (f" {manager} manages" if manager else "") +
              "; its apps stay open as separate windows:", reply.removeprefix("error: "))
    return reply.startswith("ok:")

# changed: the core was unloaded. kept: the lines rebuilt. left: the apps and owner of cards the update never described.
def left_out(cards, kept):
    return [([a for face in card["faces"] for a in face], card.get("owner") if isinstance(card.get("owner"), str) else None)
            for card in cards if card not in kept]


outcome = {"ok": False, "changed": False, "kept": [], "left": left_out(containers, kept_cards)}
atomic(marker, json.dumps({"pid": os.getpid(), "release": release, "started_ms": int(time.time() * 1000)}).encode())
try:
    # Capture after settling: a turn may have been active when installation
    # began. Native groups retain geometry, focus and current side on unload.
    # A card parked meanwhile is kept as well.
    if installed:
        ctl("hyprflip", "finish")
        current = json.loads(ctl("hyprflip", "status"))
        saved_pairs = current["pairs"] or saved_pairs
        if current.get("containers"):
            if current.get("card_cover"):
                # Before the unload: it would leave each cover a face that no description names.
                try:
                    saved_covers = uncover(answer, shown(current["containers"]))
                except Exception as refused:
                    raise SystemExit(f"A covered card kept its cover, so nothing was updated: {refused} "
                                     "Then update again.") from None
                current = json.loads(ctl("hyprflip", "status"))
            kept_now = keepable(current["containers"])
            saved_cards = [describe(card) for card in kept_now]
            outcome["left"] = left_out(current["containers"], kept_now)
    if saved_pairs or saved_cards:
        record = {"instance": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"), "pairs": saved_pairs, "cards": saved_cards}
        if saved_covers:
            record["covers"] = saved_covers
        atomic(recovery, json.dumps(record).encode())
    # Unloading the core drops the keyboard from most apps of a multi-app face.
    place = remember(ctl)
    if installed:
        outcome["changed"] = True
        reply = ctl("plugin", "unload", str(library))
        if reply != "ok": raise RuntimeError(reply)
    atomic(library, source.read_bytes())
    if originals[module] is None:
        module_content = (project / "examples/hyprflip.lua").read_text()
    else:
        module_content = originals[module].decode()
        # Migrate the shipped 0.1.0 motion values. Preserve any custom values,
        # bindings, comments and other user content in the existing module.
        for key, old, new in (("duration_ms", "280", "420"), ("perspective", "3.2", "5.0"), ("retreat", "0.035", "0.02")):
            module_content = re.sub(r"(?m)^(\s*" + key + r"\s*=\s*)" + re.escape(old) + r"(?=\s*[,\n])",
                                    lambda m: m[1] + new, module_content)
    atomic(module, module_content.encode())
    content = main.read_text()
    bootstrap = (project / "examples/module-path.lua").read_text()
    if bootstrap.splitlines()[0] not in content:
        content = bootstrap + "\n" + content
    statement = 'require("hypr.hyprflip")'
    if not any(line.strip() == statement for line in content.splitlines()):
        content = content.rstrip() + "\n\n-- Two-sided application windows.\n" + statement + "\n"
    atomic(main, content.encode())
    ctl("reload")
    # Hyprland 0.56 caches the desired config plugin list. A manual unload does
    # not invalidate it, so an unchanged declaration alone won't load it again.
    if not any(p["name"] == "hyprflip" for p in json.loads(ctl("-j", "plugin", "list"))):
        reply = ctl("plugin", "load", str(library))
        if reply != "ok": raise RuntimeError("Could not load updated plugin: " + reply)
    errors = ctl("configerrors")
    if errors: raise RuntimeError(errors)
    # Config-declared plugins load after parsing, then trigger a second parse
    # with their Lua functions and configuration values available.
    for _ in range(30):
        reply = ctl("hyprflip", "status")
        if reply.startswith("{"): break
        time.sleep(.1)
    state = json.loads(reply)
    if state.get("version") != version: raise RuntimeError("Installed plugin did not respond with the built version")
    for pair in saved_pairs:
        windows = {w["address"]: w for w in json.loads(ctl("-j", "clients"))}
        members = {pair["front"], pair["back"]}
        if not members.issubset(windows) or any(set(windows[w]["grouped"]) != members for w in members):
            print("Pair changed during update; leaving its native windows untouched:", sorted(members))
            continue
        reply = answer("hyprflip", "adopt", pair["front"], pair["back"])
        if not reply.startswith("ok:"): raise RuntimeError("Could not restore pair: " + reply)
    # Quiet, so the update leaves the keyboard and what each monitor shows alone.
    # The core just loaded is this checkout's. The rollback below stays plain:
    # the core it goes back to can be older than quiet restores and refuse them.
    # All of them first: a correction next to a card that is still loose tiles
    # resizes the wrong split and squeezes that card to a sliver.
    outcome["changed"] = True
    kept = outcome["kept"] = [line for line in saved_cards if keep(line, "restore quiet ")]
    # A quiet restore leaves the keyboard where the unload left it, which can be
    # nowhere. It goes back before any correction, as each of those gives it back
    # where it found it, and a monitor put back there can hand it to someone else.
    ours = ({a for line in saved_cards for a in apps(line)} | {item["cover"] for item in saved_covers} |
            {a for pair in saved_pairs for a in (pair["front"], pair["back"])})
    return_keyboard(ctl, place, ours)
    for line in kept:
        try:
            settle(line)
        except FullscreenWindow:
            print("A card was kept, but a fullscreen window on its workspace kept its tile from being checked or returned.")
        except (RuntimeError, KeyError, StopIteration, TypeError, ValueError):
            print("A card was kept, but its tile could not be checked or returned to the same place.")
    # Back in its tile, each card takes its cover again, which fills the card's place.
    if saved_covers:
        for note in cover_again(answer, saved_covers):
            print("A card was kept, but its cover could not be put back on it:", note)
        return_keyboard(ctl, place, ours)
    # Giving these back never fails an update, so this is the only word of it.
    if (saved_pairs or saved_cards) and not as_it_was(ctl, place):
        print("The keyboard or what a monitor shows is not as it was before the update, or Hyprland did not say.")
    errors = ctl("configerrors")
    if errors: raise RuntimeError(errors)
    recovery.unlink(missing_ok=True)
    outcome["ok"] = True
    print("Installed and loaded. Hyprland reports no configuration errors.")
except Exception:
    # Restore exact user content if loading or validation fails.
    for path, content in originals.items():
        if content is None: path.unlink(missing_ok=True)
        else: atomic(path, content)
    try:
        ctl("plugin", "unload", str(library))
        ctl("reload")
        if installed and not any(p["name"] == "hyprflip" for p in json.loads(ctl("-j", "plugin", "list"))):
            ctl("plugin", "load", str(library))
        # Newer originals support adoption; older originals retain native
        # groups and the recovery file for the next successful upgrade.
        for pair in saved_pairs:
            answer("hyprflip", "adopt", pair["front"], pair["back"])
        # Older cores lack restore; their cards stay as open windows and the
        # recovery file keeps them for the next successful update.
        outcome["kept"] = []
        for line in saved_cards:
            if keep(line):
                outcome["kept"].append(line)
        cover_again(answer, saved_covers)
    except Exception:
        pass
    raise
finally:
    # Programs that keep cards read the result once the marker is gone; the core just loaded says so on socket2.
    report(outcome, saved_cards)
    marker.unlink(missing_ok=True)
    if lock:
        lock.close()
    if outcome["ok"]:
        try:
            answer("hyprflip", "announce", "updated", release)
        except Exception:
            pass
