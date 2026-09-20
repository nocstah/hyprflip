#!/usr/bin/env python3
"""Exercise the real plugin in tests/nested_session.py's disposable compositor."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("session", type=Path)
parser.add_argument("--plugin", type=Path, default=Path("build/hyprflip.so"))
parser.add_argument("--output", type=Path, default=Path("test-results"))
args = parser.parse_args()
env = environment(args.session)
args.output.mkdir(parents=True, exist_ok=True)
library = args.session.parent / "integration-hyprflip.so"
shutil.copy2(args.plugin.resolve(), library)
processes = []
checks = []

def ctl(*arguments, success=True):
    result = subprocess.run(["hyprctl", *arguments], env=env, capture_output=True, text=True, timeout=6)
    output = result.stdout.strip()
    if success and (result.returncode or output.startswith("error:") or "could not be loaded" in output):
        raise AssertionError(f"{arguments}: {output} {result.stderr}")
    return output

def lua(code):
    output = ctl("repl", code)
    if output.startswith("error") or "Lua error" in output:
        raise AssertionError(output)
    return output

def clients():
    return json.loads(ctl("-j", "clients"))

def client(address):
    return next(c for c in clients() if c["address"] == address)

def status():
    return json.loads(ctl("hyprflip", "status"))

def action(name):
    return ctl("hyprflip", name)

def wait(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.015)
    raise AssertionError("Timed out waiting for compositor state")

def focus(address):
    ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')

def spawn(name, x11=False):
    app = "hyprflip-test-" + name
    command = ["foot", "--config", "/dev/null", "--app-id", app, "--title", app,
               "sh", "-c", f"printf '\\n  {name.upper()} — Hyprflip integration\\n'; sleep 300"]
    if x11:
        raise NotImplementedError
    process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(c["class"] == app for c in clients()))
    return next(c["address"] for c in clients() if c["class"] == app)

def pair(a, b):
    focus(a); action("mark"); focus(b); action("pair")
    wait(lambda: len(status()["pairs"]) == 1)
    time.sleep(1.0)
    assert status()["pairs"][0]["current"] == a

def check(name):
    checks.append(name)
    print("PASS", name, flush=True)

def capture(name):
    subprocess.run(["grim", str(args.output / name)], env=env, check=True, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

loaded = False
try:
    # Do not allow a second instance of the same plugin in the test compositor.
    assert "hyprflip" not in ctl("plugin", "list"), "Unload the previous test plugin first"
    ctl("plugin", "load", str(library)); loaded = True
    lua("hl.config({plugin={hyprflip={duration_ms=180,notifications=false}}})")
    assert status()["pairs"] == []
    a, b = spawn("a"), spawn("b")
    focus(a)
    assert ctl("hyprflip", "pair", success=False).startswith("error:")
    action("mark"); action("cancel")
    assert status()["marked"] is None
    action("mark")
    assert ctl("hyprflip", "pair", success=False).startswith("error:")
    check("invalid pairing and cancellation")

    pair(a, b)
    before = client(a)["at"], client(a)["size"]
    check("two real windows share a native group")
    for i in range(16):
        action("flip")
        assert status()["animating"], status()
        wait(lambda: not status()["animating"])
        expected = b if i % 2 == 0 else a
        assert status()["pairs"][0]["current"] == expected
        assert (client(expected)["at"], client(expected)["size"]) == before
        group_clients = [client(a), client(b)]
        assert sum(c["acceptsInput"] for c in group_clients) == 1
    check("16 animated flips preserve geometry and exclusive input")

    lua("hl.config({plugin={hyprflip={duration_ms=1500}}})")
    action("flip")
    wait(lambda: status()["progress"] > .23)
    capture("outgoing.png")
    wait(lambda: status()["progress"] > .63)
    capture("incoming.png")
    wait(lambda: not status()["animating"])
    check("GPU output captured on both sides of midpoint")

    original = status()["pairs"][0]["current"]
    action("flip"); time.sleep(.10); action("flip")
    wait(lambda: not status()["animating"])
    assert status()["pairs"][0]["current"] == original
    action("flip"); wait(lambda: status()["progress"] > .6); action("flip")
    wait(lambda: not status()["animating"])
    assert status()["pairs"][0]["current"] == original
    check("reverse before and after midpoint returns to original")

    action("flip")
    subprocess.run(["wtype", "x"], env=env, check=True, timeout=5)
    assert not status()["animating"]
    check("new keyboard input settles animation")

    neighbor = spawn("neighbor")
    focus(a)
    action("flip"); focus(neighbor)
    assert not status()["animating"]
    assert json.loads(ctl("-j", "activewindow"))["address"] == neighbor
    check("external focus settles without stealing focus")

    focus(a)
    lua("hl.config({plugin={hyprflip={enabled=false}}})")
    original = status()["pairs"][0]["current"]
    action("flip")
    assert not status()["animating"] and status()["pairs"][0]["current"] != original
    lua("hl.config({plugin={hyprflip={enabled=true}}})")
    check("reduced motion switches instantly")

    action("unpair")
    assert not status()["pairs"] and not client(a)["grouped"] and not client(b)["grouped"]
    assert client(a)["acceptsInput"] and client(b)["acceptsInput"]
    check("unpair exposes both windows")

    # Floating state is native group state; both windows inherit the first footprint.
    for address in (a, b):
        focus(address); ctl("dispatch", 'hl.dsp.window.float({action="float"})')
    time.sleep(.5)
    pair(a, b)
    action("flip"); action("finish")
    assert client(b)["floating"] and status()["pairs"][0]["current"] == b
    action("unpair")
    for address in (a, b):
        focus(address); ctl("dispatch", 'hl.dsp.window.float({action="tile"})')
    check("floating pairs flip and unpair")

    pair(a, b)
    focus(a); ctl("dispatch", 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    time.sleep(.5)
    action("flip"); action("finish")
    assert client(b)["fullscreen"] != 0
    ctl("dispatch", 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    time.sleep(.4)
    check("fullscreen transfers to reverse side")

    action("flip"); ctl("reload")
    assert not status()["animating"] and len(status()["pairs"]) == 1
    lua("hl.config({plugin={hyprflip={duration_ms=1500,notifications=false}}})")
    check("configuration reload settles safely")

    action("flip"); ctl("plugin", "unload", str(library)); loaded = False
    assert len(client(a)["grouped"]) == 2
    assert sum(client(w)["acceptsInput"] for w in (a,b)) == 1
    # A normal native group remains operable after all plugin code is unloaded.
    focus(a)
    previous = json.loads(ctl("-j", "activewindow"))["address"]
    ctl("dispatch", "hl.dsp.group.next()")
    assert json.loads(ctl("-j", "activewindow"))["address"] != previous
    check("unload during animation leaves accessible native group")
    ctl("plugin", "load", str(library)); loaded = True
    assert status()["pairs"] == []
    # Upgrade recovery only adopts the exact two live members. It must not
    # focus a window, rearrange tiles, change the visible side or accept stale
    # addresses from a previous process.
    current = json.loads(ctl("-j", "activewindow"))["address"]
    geometry = client(a)["at"], client(a)["size"]
    assert ctl("hyprflip", "adopt", a, "0x1", success=False).startswith("error:")
    assert ctl("hyprflip", "adopt", a, neighbor, success=False).startswith("error:")
    ctl("hyprflip", "adopt", a, b)
    assert status()["pairs"][0]["front"] == a and status()["pairs"][0]["back"] == b
    assert status()["pairs"][0]["current"] == current
    assert json.loads(ctl("-j", "activewindow"))["address"] == current
    assert (client(a)["at"], client(a)["size"]) == geometry
    assert ctl("hyprflip", "adopt", a, b, success=False).startswith("error:")
    action("flip"); action("finish")
    assert status()["pairs"][0]["current"] != current
    action("unpair")
    check("upgrade adopts the existing pair without layout or focus changes")
    pair(a, b)
    action("flip")
    ctl("dispatch", "hl.dsp.focus({workspace=2})")
    assert not status()["animating"]
    ctl("dispatch", "hl.dsp.focus({workspace=1})")
    time.sleep(1)
    focus(a)
    check("workspace change settles without losing the pair")

    action("flip")
    lua(f'hl.get_window("address:{a}").group:remove(hl.get_window("address:{b}"))')
    assert not status()["animating"] and not status()["pairs"]
    assert client(a)["acceptsInput"] and client(b)["acceptsInput"]
    lua(f'hl.get_window("address:{a}").group:remove(hl.get_window("address:{a}"))')
    check("external group removal relinquishes ownership safely")

    pair(a,b)
    action("flip")
    focus(a); ctl("dispatch", "hl.dsp.window.close()")
    wait(lambda: all(c["address"] != a for c in clients()))
    wait(lambda: not status()["pairs"])
    assert client(b)["acceptsInput"]
    check("closing a member during flip preserves the survivor")

    assert not ctl("configerrors").strip()
    check("no configuration errors")
finally:
    if loaded:
        ctl("plugin", "unload", str(library), success=False)
    for process in processes:
        process.terminate()
    for process in processes:
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill()
    (args.output / "integration.json").write_text(json.dumps({"checks_passed": checks, "count": len(checks)}, indent=2) + "\n")
print(f"{len(checks)} integration checks passed", flush=True)
