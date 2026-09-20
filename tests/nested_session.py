#!/usr/bin/env python3
"""A disposable Wayland-nested Hyprland. Never opens a DRM/logind session.

Keeps compositor and clients alive until interrupted; prints a connection file
for integration.py. All configuration and output stay in the supplied directory.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path, required=True)
args = parser.parse_args()
root = args.directory.resolve()
# sockaddr_un.sun_path is 108 bytes including NUL. Hyprland's signature and
# socket filename need room too; a long test path otherwise silently truncates.
if len(os.fsencode(str(root))) > 18:
    raise SystemExit("Use a short temporary path (at most 18 bytes), e.g. /tmp/hf-test")
root.mkdir(parents=True, exist_ok=True)
for directory in ("runtime", "config", "cache", "data", "state"):
    (root / directory).mkdir(mode=0o700, exist_ok=True)
runtime = root / "runtime"
env = os.environ.copy()
parent = Path(env.get("WAYLAND_DISPLAY", "wayland-1"))
if not parent.is_absolute():
    parent = Path(env["XDG_RUNTIME_DIR"]) / parent
if not parent.exists():
    raise SystemExit("A running parent Wayland compositor is required")
env.update(
    WAYLAND_DISPLAY=str(parent), XDG_RUNTIME_DIR=str(runtime),
    XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"),
    XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"),
    LIBSEAT_BACKEND="hyprflip-test-no-physical-session", AQ_DRM_DEVICES="/dev/null",
    HYPRLAND_NO_SD_VARS="1", HYPRLAND_NO_SD_NOTIFY="1", HYPRLAND_NO_CRASHREPORTER="1",
)
for key in ("HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
    env.pop(key, None)
config = root / "hyprland.lua"
config.write_text('''hl.monitor({output="",mode="1280x800@60",position="auto",scale=1})
hl.config({
    general={gaps_in=6,gaps_out=12,border_size=2,layout="dwindle"},
    decoration={rounding=12,blur={enabled=true,size=3,passes=2},shadow={enabled=true}},
    animations={enabled=true},
    misc={disable_hyprland_logo=true,force_default_wallpaper=0},
    input={follow_mouse=0},
    debug={disable_logs=false,enable_stdout_logs=true}
})
''')
processes = []
stopping = False
def stop(signum, frame):
    global stopping
    stopping = True
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
try:
    with (root / "compositor.log").open("wb") as log:
        compositor = subprocess.Popen(["Hyprland", "--config", str(config)], env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
    processes.append(compositor)
    deadline = time.monotonic() + 20
    socket = None
    while time.monotonic() < deadline:
        if compositor.poll() is not None:
            raise RuntimeError("Nested compositor exited: see compositor.log")
        sockets = list(runtime.glob("hypr/*/.socket.sock"))
        displays = [p for p in runtime.glob("wayland-*") if not p.name.endswith(".lock")]
        if sockets and displays:
            socket = sockets[-1]
            env.update(HYPRLAND_INSTANCE_SIGNATURE=socket.parent.name, WAYLAND_DISPLAY=displays[-1].name)
            break
        time.sleep(.1)
    if socket is None:
        raise RuntimeError("Timed out waiting for nested compositor")
    connection = {k: env[k] for k in ("XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    (root / "session.json").write_text(json.dumps(connection))
    time.sleep(1)
    for face, color in (("front", "173746"), ("back", "482d48")):
        with (root / f"{face}.log").open("wb") as log:
            process = subprocess.Popen([
                "foot", "--app-id", f"hyprflip-{face}", "--title", f"Hyprflip {face}",
                "--override", f"colors-dark.background={color}", "--override", "font=monospace:size=20",
                "sh", "-c", f"printf '\\n  HYPRFLIP — {face.upper()}\\n\\n  Readable text, real application.\\n\\n  LEFT                         RIGHT\\n'; exec cat"
            ], env=env, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
    print(f"READY {root / 'session.json'}", flush=True)
    while not stopping and compositor.poll() is None:
        time.sleep(.2)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    (root / "session.json").unlink(missing_ok=True)
