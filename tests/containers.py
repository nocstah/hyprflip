#!/usr/bin/env python3
"""Exercise opt-in hy3 containers only in an explicitly selected nested session."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("session", type=Path)
parser.add_argument("--plugin", type=Path, default=Path("build/containers/core/hyprflip.so"))
parser.add_argument("--hy3", type=Path, default=Path("build/containers/provider/upstream/libhy3.so"))
parser.add_argument("--output", type=Path, default=Path("test-results/containers"))
args = parser.parse_args()
env = environment(args.session)
args.output.mkdir(parents=True, exist_ok=True)
core = args.session.parent / "container-hyprflip.so"
hy3 = args.session.parent / "container-hy3.so"
processes = []
checks = []
loaded = []
config = args.session.parent / "hyprland.lua"
original_config = config.read_text()


def ctl(*arguments, success=True):
    result = subprocess.run(["hyprctl", *arguments], env=env, capture_output=True, text=True, timeout=6)
    output = result.stdout.strip()
    if success and (result.returncode or output.startswith("error") or "could not be loaded" in output or "Lua error" in output):
        raise AssertionError(f"{arguments}: {output} {result.stderr}")
    return output


def lua(code):
    return ctl("repl", code)


def status():
    return json.loads(ctl("hyprflip", "status"))


def card():
    cards = status()["containers"]
    assert len(cards) == 1, cards
    return cards[0]


def clients():
    return json.loads(ctl("-j", "clients"))


def client(address):
    return next(c for c in clients() if c["address"] == address)


def active():
    return json.loads(ctl("-j", "activewindow")).get("address")


def action(name):
    return ctl("hyprflip", name)


def wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.015)
    raise AssertionError(f"Timed out; status={status()}; clients={clients()}")


def focus(address):
    ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')


def spawn(name, color="223747"):
    app = "hyprflip-container-" + name
    process = subprocess.Popen([
        "foot", "--config", "/dev/null", "--app-id", app, "--title", name,
        "--override", f"colors-dark.background={color}", "--override", "font=monospace:size=18",
        "sh", "-c", f"printf '\\n  {name.upper()}\\n\\n  LEFT        CENTER        RIGHT\\n'; exec cat",
    ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(c["class"] == app for c in clients()))
    return next(c["address"] for c in clients() if c["class"] == app)


def close(address):
    focus(address)
    ctl("dispatch", 'hl.dsp.window.close()')
    wait(lambda: all(c["address"] != address for c in clients()))


def pair(a, b):
    focus(a)
    action("mark")
    focus(b)
    action("pair")
    assert card()["faces"] == [[a], [b]]
    assert active() == a


def attach(candidate, destination, axis="horizontal"):
    focus(candidate)
    action("mark")
    focus(destination)
    action("attach " + axis)


def flip():
    action("flip")
    wait(lambda: not status()["animating"])


def visibility():
    current = card()
    for side, face in enumerate(current["faces"]):
        for address in face:
            c = client(address)
            assert c["hidden"] == (side != current["active"]), (current, c)
            assert c["acceptsInput"] == (side == current["active"]), (current, c)


def check(name):
    checks.append(name)
    print("PASS", name, flush=True)


def capture(name):
    subprocess.run(["grim", str(args.output / name)], env=env, check=True, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


try:
    monitor = next(m['name'] for m in json.loads(ctl('-j', 'monitors')) if m['name'] != 'FALLBACK')
    plugins = ctl("plugin", "list")
    assert "hy3" not in plugins and "hyprflip" not in plugins, "Unload previous test libraries first"
    shutil.copy2(args.plugin.resolve(), core)
    shutil.copy2(args.hy3.resolve(), hy3)
    ctl("plugin", "load", str(hy3)); loaded.append(hy3)
    ctl("plugin", "load", str(core)); loaded.append(core)
    config.write_text(original_config.replace('layout="dwindle"', 'layout="hy3"'))
    ctl("reload")
    lua('hl.config({general={layout="hy3"},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ctl("dispatch", "hl.dsp.focus({workspace=100})")
    assert status()["container_provider"]
    a, b, c = spawn("front"), spawn("back", "482d48"), spawn("notes", "4b352b")
    pair(a, b)
    assert status()["pairs"] == []
    flip()
    attach(c, b)
    assert card()["faces"] == [[a], [b, c]]
    visibility()
    assert active() == b
    check("three real windows; explicit attachment and exclusive face input")

    focus(c)
    flip()
    assert active() == a
    flip()
    assert active() == c
    check("flips restore the last focused pane on each face")

    neighbor = spawn("neighbor", "253c32")
    assert card()["faces"] == [[a], [b, c]]
    assert not client(neighbor)["hidden"]
    attach(neighbor, a, "vertical")
    assert card()["faces"] == [[a, neighbor], [b, c]]
    fifth = spawn("outside")
    attach(fifth, a, "horizontal")
    assert card()["faces"] == [[a, neighbor, fifth], [b, c]]
    sixth = spawn("over-capacity")
    focus(sixth); action("mark"); focus(a)
    assert ctl("hyprflip", "attach", success=False).startswith("error:")
    assert status()["marked"] == sixth
    action("cancel")
    close(sixth)
    focus(fifth); action("release")
    assert card()["faces"] == [[a, neighbor], [b, c]]
    focus(neighbor); action("release")
    assert card()["faces"] == [[a], [b, c]]
    assert active() == neighbor and not client(neighbor)["hidden"]
    close(fifth)
    check("both split axes, three-pane limit, outside opens and focused release")

    focus(c)
    action("workspace 101")
    assert all(client(w)["workspace"]["id"] == 101 for w in (a, b, c))
    assert client(neighbor)["workspace"]["id"] == 100
    assert active() == c
    visibility()
    action("workspace 100")
    assert all(client(w)["workspace"]["id"] == 100 for w in (a, b, c))
    assert active() == c
    assert ctl("hyprflip", "workspace 0", success=False).startswith("error:")
    check("whole-card workspace moves preserve membership and application focus")

    focus(b)
    time.sleep(1)
    lua("hl.config({plugin={hyprflip={duration_ms=420}}})")
    bounds = card()["box"]
    pane_boxes = {w: (client(w)["at"], client(w)["size"]) for w in (a, b, c)}
    for i in range(12):
        action("flip")
        assert status()["animating"], status()
        wait(lambda: not status()["animating"])
        assert card()["box"] == bounds
        assert not status()["last_fallback"], status()
        visibility()
        assert {w: (client(w)["at"], client(w)["size"]) for w in (a, b, c)} == pane_boxes
    check("12 animated flips preserve outer and pane geometry")

    lua("hl.config({plugin={hyprflip={duration_ms=1600}}})")
    capture("back-rest.png")
    action("flip")
    wait(lambda: status()["progress"] > .20)
    capture("back-outgoing.png")
    wait(lambda: status()["progress"] > .63)
    capture("front-incoming.png")
    wait(lambda: not status()["animating"])
    action("flip")
    wait(lambda: status()["progress"] > .63)
    capture("back-incoming.png")
    action("flip")
    wait(lambda: not status()["animating"])
    assert card()["active"] == 0
    check("GPU captures across midpoint and reversal after midpoint")

    lua(f'hl.monitor({{output={json.dumps(monitor)},mode="1280x800@60",position="0x0",scale=1.6,transform=1}})')
    output = next(m for m in json.loads(ctl('-j', 'monitors')) if m['name'] == monitor)
    assert output['scale'] == 1.6 and output['transform'] == 1, output
    time.sleep(1)
    action("flip")
    assert status()["animating"], status()
    wait(lambda: status()["progress"] > .63)
    capture("split-scale-1.6-rotation-1.png")
    wait(lambda: not status()["animating"])
    assert not status()["last_fallback"]
    visibility()
    lua(f'hl.monitor({{output={json.dumps(monitor)},mode="1280x800@60",position="0x0",scale=1,transform=0}})')
    time.sleep(1)
    focus(a)
    check("split-face animation on a rotated output at fractional scale 1.6")

    action("flip")
    wait(lambda: status()["progress"] > .15)
    focus(neighbor)
    assert not status()["animating"] and active() == neighbor
    visibility()
    focus(a)
    action("flip")
    subprocess.run(["wtype", "x"], env=env, check=True, timeout=5)
    wait(lambda: not status()["animating"])
    check("external focus is preserved and keyboard input settles the turn")

    focus(b)
    time.sleep(.3)
    action("flip")
    wait(lambda: status()["progress"] > .15)
    ctl("dispatch", 'hl.dsp.window.fullscreen({action="set",layout_aware=false})')
    assert not status()["animating"] and card()["active"] == 1 and active() == b
    lua("hl.config({plugin={hyprflip={duration_ms=0}}})")
    assert ctl("hyprflip", "flip", success=False).startswith("error:")
    ctl("dispatch", 'hl.dsp.window.fullscreen({action="unset",layout_aware=false})')
    visibility()
    lua("hl.config({plugin={hyprflip={duration_ms=1600}}})")
    time.sleep(.5)
    action("flip")
    ctl("reload")
    wait(lambda: not status()["animating"])
    assert card()["faces"] == [[a], [b, c]]
    visibility()
    check("fullscreen is explicit and configuration reload preserves the card")

    focus(c)
    action("flip")
    close(c)
    wait(lambda: not status()["animating"])
    assert card()["faces"] == [[a], [b]]
    focus(b)
    action("release")
    assert status()["containers"] == []
    assert all(not client(w)["hidden"] for w in (a, b))
    check("close during animation and releasing the last pane dissolve safely")

    pair(a, b)
    lua('hl.dispatch(hl.plugin.hy3.lock_tab("unlock"))')
    lua('hl.dispatch(hl.plugin.hy3.change_group("h"))')
    wait(lambda: not status()["containers"])
    assert all(not client(w)["hidden"] for w in (a, b))
    check("external tree edits relinquish ownership and keep windows accessible")

    pair(a, b)
    lua("hl.config({plugin={hyprflip={duration_ms=1600}}})")
    action("flip")
    ctl("plugin", "unload", str(core)); loaded.remove(core)
    assert all(not client(w)["hidden"] for w in (a, b))
    ctl("plugin", "load", str(core)); loaded.append(core)
    lua('hl.config({general={layout="hy3"}})')
    pair(a, b)
    action("flip")
    ctl("plugin", "unload", str(hy3)); loaded.remove(hy3)
    # Retained renderer objects are destroyed on the following frame, so an
    # immediate successful IPC reply alone cannot prove unload safety.
    time.sleep(.6)
    wait(lambda: status()["containers"] == [])
    assert not status()["animating"] and not status()["container_provider"]
    assert all(not client(w)["hidden"] for w in (a, b))
    check("either plugin can unload during a turn without stranding windows")

    ctl("plugin", "load", str(hy3)); loaded.append(hy3)
    assert status()["container_provider"] and not status()["containers"]
    pair(a, b)
    time.sleep(.6)
    capture("reloaded-provider.png")
    ctl("plugin", "unload", str(hy3)); loaded.remove(hy3)
    time.sleep(.6)
    assert not status()["containers"]
    assert all(not client(w)["hidden"] for w in (a, b))
    check("provider reload has fresh ownership and idle render-pass cleanup is safe")

    assert not ctl("configerrors").strip(), ctl("configerrors")
    (args.output / "report.json").write_text(json.dumps({"checks": checks}, indent=2))
    print(f"PASS {len(checks)} container checks", flush=True)
finally:
    if loaded:
        try:
            (args.output / "last-state.json").write_text(json.dumps({"status": status(), "clients": clients()}, indent=2))
        except Exception:
            pass
    for library in reversed(loaded):
        ctl("plugin", "unload", str(library), success=False)
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    config.write_text(original_config)
    ctl("reload", success=False)
    ctl("dispatch", "hl.dsp.focus({workspace=1})", success=False)
