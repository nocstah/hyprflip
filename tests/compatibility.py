#!/usr/bin/env python3
"""Real GTK Wayland/XWayland, popups, rotation and Hyprglass checks."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from control import environment

p = argparse.ArgumentParser()
p.add_argument("session", type=Path)
p.add_argument("--plugin", type=Path, default=Path("build/hyprflip.so"))
p.add_argument("--hyprglass", type=Path)
p.add_argument("--output", type=Path, default=Path("test-results"))
args = p.parse_args()
env = environment(args.session)
args.output.mkdir(parents=True, exist_ok=True)
processes = []
checks = []
loaded = False
glass = False
def ctl(*a, fail=False):
    r = subprocess.run(["hyprctl", *a], env=env, text=True, capture_output=True, timeout=6)
    text = r.stdout.strip()
    if not fail and (r.returncode or text.startswith("error") or "could not be loaded" in text):
        raise AssertionError((a, text, r.stderr))
    return text
def lua(s): return ctl("repl", s)
def status(): return json.loads(ctl("hyprflip", "status"))
def action(s): return ctl("hyprflip", s)
def focus(address): ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')
def wait(fn, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn(): return
        time.sleep(.03)
    raise AssertionError("Timed out")
def windows(): return json.loads(ctl("-j", "clients"))
def check(name): checks.append(name); print("PASS", name, flush=True)
def capture(name): subprocess.run(["grim", str(args.output / name)], env=env, check=True, timeout=6)
def settings(): lua('hl.config({plugin={hyprflip={duration_ms=1200,notifications=false}}})')
try:
    assert "hyprflip" not in ctl("plugin", "list")
    ctl("plugin", "load", str(args.plugin.resolve())); loaded = True
    settings()
    ctl("dispatch", "hl.dsp.focus({workspace=4})")
    display = lua('return os.getenv("DISPLAY")')
    addresses = []
    controls = []
    for backend in ("wayland", "x11"):
        name = "hyprflip-compat-" + backend
        command = args.session.parent / (name + ".command")
        command.write_text(""); controls.append(command)
        process = subprocess.Popen(["python", str(Path(__file__).with_name("gtk_fixture.py")), name, str(command)],
            env=env | {"GDK_BACKEND": backend, "GSK_RENDERER": "cairo", "DISPLAY": display},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        processes.append(process)
        wait(lambda: any(w["title"] == name for w in windows()))
        addresses.append(next(w["address"] for w in windows() if w["title"] == name))
    a,b = addresses
    assert next(w for w in windows() if w["address"] == b)["xwayland"]
    focus(a); action("mark"); focus(b); action("pair"); time.sleep(1)
    action("flip"); assert status()["animating"]
    wait(lambda: not status()["animating"])
    assert status()["pairs"][0]["current"] == b
    check("Wayland and XWayland pair animates")
    action("flip"); action("finish")
    controls[0].write_text("popup"); time.sleep(.3)
    reply = ctl("hyprflip", "flip", fail=True)
    assert not status()["animating"]
    assert reply.startswith("error:") or "Popup" in status()["last_fallback"]
    controls[0].write_text("dismiss"); time.sleep(.3)
    check("popup switches instantly or safely defers to active grab")
    focus(a)
    controls[0].write_text("modal"); time.sleep(.4)
    assert ctl("hyprflip", "flip", fail=True).startswith("error:")
    controls[0].write_text("dismiss"); time.sleep(.3); focus(a)
    check("modal child is not treated as a paired window")

    for transform in (0,1,3):
        lua(f'hl.monitor({{output="WAYLAND-1",mode="1280x800@60",position="0x0",scale=1.6,transform={transform}}})')
        time.sleep(1)
        focus(status()["pairs"][0]["current"])
        action("flip"); assert status()["animating"],status()
        wait(lambda: status()["progress"]>.22)
        capture(f"scale-1.6-rotation-{transform}-outgoing.png")
        wait(lambda: status()["progress"]>.63)
        capture(f"scale-1.6-rotation-{transform}-incoming.png")
        wait(lambda: not status()["animating"])
        assert not status()["last_fallback"]
        check(f"fractional scale 1.6, monitor transform {transform}")
    lua('hl.monitor({output="WAYLAND-1",mode="1280x800@60",position="0x0",scale=1,transform=0})')
    time.sleep(1)
    focus(status()["pairs"][0]["current"])
    if args.hyprglass:
        ctl("plugin", "load", str(args.hyprglass.resolve())); glass=True
        lua('hl.plugin.hyprglass.config({enabled=true,manage_window_blur=true})')
        settings(); time.sleep(.5)
        focus(status()["pairs"][0]["current"])
        action("flip"); assert status()["animating"]
        assert any("hyprglass_disabled" in w["tags"] for w in windows() if w["address"] in addresses)
        time.sleep(.35); capture("hyprglass-flip.png")
        wait(lambda: not status()["animating"])
        assert not status()["last_fallback"]
        assert all("hyprglass_disabled" not in w["tags"] for w in windows() if w["address"] in addresses)
        ctl("plugin", "unload", str(args.hyprglass.resolve())); glass=False
        check("Hyprglass loaded and enabled during GPU flip")
    action("unpair")
    assert not ctl("configerrors").strip()
finally:
    if glass: ctl("plugin", "unload", str(args.hyprglass.resolve()), fail=True)
    if loaded: ctl("plugin", "unload", str(args.plugin.resolve()), fail=True)
    ctl("reload", fail=True)
    ctl("dispatch", "hl.dsp.focus({workspace=1})", fail=True)
    for process in processes: process.terminate()
    for process in processes:
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill()
    (args.output / "compatibility.json").write_text(json.dumps({"checks_passed":checks,"count":len(checks)},indent=2)+"\n")
print(f"{len(checks)} compatibility checks passed",flush=True)
