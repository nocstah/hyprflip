#!/usr/bin/env python3
"""Install the built plugin and its Lua shortcuts for this user, with backups."""
import argparse
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
config_root = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "hypr"
module = config_root / "hyprflip.lua"
main = config_root / "hyprland.lua"
version = re.search(r"project\(hyprflip VERSION ([\d.]+)", (project / "CMakeLists.txt").read_text()).group(1)
if not source.is_file() or not main.is_file():
    raise SystemExit("Build with make first; this installer requires an existing Hyprland Lua configuration.")

def ctl(*args):
    p = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout.strip()

binds = json.loads(ctl("-j", "binds"))
keys = {"M", "P", "F", "U", "ESCAPE"}
conflicts = [b for b in binds if b["modmask"] == 76 and b["key"].upper() in keys
             and not b.get("description", "").startswith("Hyprflip:")]
if conflicts:
    raise SystemExit("Shortcut conflict; adjust examples/hyprflip.lua before installing: " + json.dumps(conflicts))

print(f"Plugin: {library}\nShortcuts: {module}\nLoad from: {main}")
print("Super+Ctrl+Alt with M=mark, P=pair, F=flip, U=unpair, Escape=cancel")
installed = any(p["name"] == "hyprflip" for p in json.loads(ctl("-j", "plugin", "list")))
installed_state = json.loads(ctl("hyprflip", "status")) if installed else {}
if installed_state.get("containers"):
    raise SystemExit("Multi-app cards are active. Save and ungroup them before updating the core; their apps stay open. "
                     "This installer preserves two-window native pairs. "
                     "For hy3 cards, use the matching core/provider updater in docs/INSTALL.md.")
saved_pairs = installed_state.get("pairs", [])
if not saved_pairs and recovery.is_file():
    pending = json.loads(recovery.read_text())
    if pending.get("instance") == os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        saved_pairs = pending["pairs"]
if saved_pairs:
    print(f"Preserving {len(saved_pairs)} existing pair(s) through this update.")
if args.dry_run:
    raise SystemExit(0)

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

try:
    # Capture after settling: a turn may have been active when installation
    # began. Native groups retain geometry, focus and current side on unload.
    if installed:
        ctl("hyprflip", "finish")
        saved_pairs = json.loads(ctl("hyprflip", "status"))["pairs"] or saved_pairs
    if saved_pairs:
        atomic(recovery, json.dumps({"instance": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"),
                                     "pairs": saved_pairs}).encode())
    if installed:
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
        reply = ctl("hyprflip", "adopt", pair["front"], pair["back"])
        if not reply.startswith("ok:"): raise RuntimeError("Could not restore pair: " + reply)
    errors = ctl("configerrors")
    if errors: raise RuntimeError(errors)
    recovery.unlink(missing_ok=True)
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
            ctl("hyprflip", "adopt", pair["front"], pair["back"])
    except Exception:
        pass
    raise
