#!/usr/bin/env python3
"""Exercise replacement of a config-loaded library in the disposable session."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("session", type=Path)
parser.add_argument("--baseline", type=Path, required=True)
args = parser.parse_args()
env = environment(args.session)
config = args.session.parent / "hyprland.lua"
original = config.read_bytes()
library = args.session.parent / "config-upgrade.so"
version = re.search(r"project\(hyprflip VERSION ([\d.]+)", Path("CMakeLists.txt").read_text()).group(1)

def ctl(*arguments):
    return subprocess.check_output(["hyprctl", *arguments], env=env, text=True, timeout=10).strip()

def state():
    return json.loads(ctl("hyprflip", "status"))

def focus(address):
    ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')

assert not any(p["name"] == "hyprflip" for p in json.loads(ctl("-j", "plugin", "list")))
windows = json.loads(ctl("-j", "clients"))
a = next(w["address"] for w in windows if w["class"] == "hyprflip-front")
b = next(w["address"] for w in windows if w["class"] == "hyprflip-back")
try:
    shutil.copy2(args.baseline, library)
    config.write_bytes(original + f'\nhl.plugin.load("{library}")\n'.encode())
    ctl("reload"); time.sleep(.3)
    assert state()["version"] == "0.1.0"
    focus(a); ctl("hyprflip", "mark"); focus(b); ctl("hyprflip", "pair")
    time.sleep(1)
    ctl("hyprflip", "flip"); ctl("hyprflip", "finish")
    before = state()["pairs"][0]
    geometry = {w["address"]: (w["at"], w["size"]) for w in json.loads(ctl("-j", "clients"))}
    assert ctl("plugin", "unload", str(library)) == "ok"
    temporary = library.with_suffix(".new.so")
    shutil.copy2(Path("build/hyprflip.so"), temporary)
    temporary.replace(library)
    ctl("reload")
    assert ctl("hyprflip", "status") == "unknown request", "Expected Hyprland's cached config plugin list"
    assert ctl("plugin", "load", str(library)) == "ok"
    time.sleep(.3)
    assert state()["version"] == version
    assert ctl("hyprflip", "adopt", a, b).startswith("ok:")
    assert state()["pairs"][0] == before
    assert json.loads(ctl("-j", "activewindow"))["address"] == before["current"]
    for w in json.loads(ctl("-j", "clients")):
        assert (w["at"], w["size"]) == geometry[w["address"]]
    assert not ctl("configerrors")
    ctl("hyprflip", "flip"); time.sleep(.6)
    assert not state()["animating"] and state()["pairs"][0]["current"] == a
    ctl("hyprflip", "unpair")
    print(f"PASS config-loaded 0.1.0 → {version} upgrade, cached-list reload, preserved pair/focus/geometry, animated flip")
finally:
    ctl("plugin", "unload", str(library))
    config.write_bytes(original)
    ctl("reload")
