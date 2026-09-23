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
import shutil
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path, required=True)
demo_flags = parser.add_mutually_exclusive_group()
demo_flags.add_argument("--containers", action="store_true", help="Open an interactive hy3 card demo")
demo_flags.add_argument("--native-cards", action="store_true", help="Open an interactive dwindle card demo using only the core")
args = parser.parse_args()
demo = args.containers or args.native_cards
root = args.directory.resolve()
# sockaddr_un.sun_path is 108 bytes including NUL. Hyprland's signature and
# socket filename need room too; a long test path otherwise silently truncates.
if len(os.fsencode(str(root))) > 18:
    raise SystemExit("Use a short temporary path (at most 18 bytes), e.g. /tmp/hf-test")
root.mkdir(parents=True, exist_ok=True)
if (root / "session.json").exists():
    raise SystemExit("This directory already has a session. Close it first or choose a fresh /tmp path.")
project = Path(__file__).resolve().parent.parent
demo_libraries = ([project / "build/hyprflip.so"] if args.native_cards else
                  [project / "build/containers/provider/upstream/libhy3.so",
                   project / "build/containers/core/hyprflip.so"])
if demo and any(not library.exists() for library in demo_libraries):
    raise SystemExit("Build first: make test" if args.native_cards else "Build first: ./scripts/build-containers")
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
base_config = '''hl.monitor({output="",mode="1280x800@60",position="auto",scale=1})
hl.config({
    general={gaps_in=6,gaps_out=12,border_size=2,layout="dwindle"},
    decoration={rounding=12,blur={enabled=true,size=3,passes=2},shadow={enabled=true}},
    animations={enabled=true},
    misc={disable_hyprland_logo=true,force_default_wallpaper=0},
    input={follow_mouse=0},
    debug={disable_logs=false,enable_stdout_logs=true}
})
'''
config.write_text(base_config)
processes = []
stopping = False
def stop(signum, frame):
    global stopping
    stopping = True
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

def ctl(*arguments):
    result = subprocess.run(["hyprctl", *arguments], env=env, capture_output=True, text=True, timeout=6)
    output = result.stdout.strip()
    if result.returncode or output.startswith("error") or "could not be loaded" in output or "Lua error" in output:
        raise RuntimeError(f"{arguments}: {output} {result.stderr}")
    return output

def focus(address):
    ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')

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
    if demo:
        for source in demo_libraries:
            library = root / source.name
            shutil.copy2(source, library)
            ctl("plugin", "load", str(library))
        config.write_text((base_config if args.native_cards else base_config.replace('layout="dwindle"', 'layout="hy3"')) + '''
if hl.plugin.hyprflip then
    hl.config({plugin={hyprflip={duration_ms=420,notifications=true}}})
    local function run(action, argument)
        return function()
            local plugin = hl.plugin.hyprflip
            if plugin and plugin[action] then plugin[action](argument) end
        end
    end
    hl.bind("F8", run("flip"), {description="Demo: flip card"})
    hl.bind("F6", run("mark"), {description="Demo: mark window"})
    hl.bind("F7", run("card"), {description="Demo: pair marked window"})
    hl.bind("SHIFT + F7", run("attach", "horizontal"), {description="Demo: attach pane beside"})
    hl.bind("CTRL + SHIFT + F7", run("attach", "vertical"), {description="Demo: attach pane below"})
    hl.bind("SHIFT + F6", run("release"), {description="Demo: release focused pane"})
    hl.bind("SHIFT + F8", run("unpair"), {description="Demo: dissolve card"})
end
''')
        ctl("reload")
        if error := ctl("configerrors"):
            raise RuntimeError(error)
        ctl("repl", "hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})")
    faces = [("front", "173746"), ("back", "482d48")]
    if demo:
        faces.append(("notes", "4b352b"))
    for face, color in faces:
        content = {
            "front": """  HYPRFLIP CONTAINER DEMO

  F8  Flip to two companion panes.
      Press again during a turn to reverse it.

  Click either back pane, type something,
  then flip away and back. Focus returns there.

  F6              Mark a window
  F7              Pair with the marked window
  Shift + F7      Attach marked window beside
  Ctrl+Shift+F7   Attach marked window below
  Shift + F6      Release the focused pane
  Shift + F8      Dissolve the whole card

  These shortcuts work inside this demo only.
  Stop the launcher with Ctrl+C when finished.
""",
            "back": """  COMPANION TERMINAL

  This pane shares the back with notes.
  Click here and use this shell.

  F8 flips the entire face.
  Shift + F6 releases this pane.
""",
            "notes": """  SECOND COMPANION PANE

  Click here, then press F8 twice.
  Keyboard focus should return here.

  Try releasing and reattaching this pane:
    Shift + F6  Release
    F6          Mark it
    Click the other back pane
    Shift + F7  Attach beside it again

  This is also a normal interactive shell.
""",
        }
        if args.native_cards:
            content.update(front="""  HYPRFLIP ON DWINDLE

  One tile. Two faces. Three live apps.
  Core plugin only. No extra layout plugin.

  F8               Flip the card
  F6               Mark a window
  F7               Pair with the marked window
  Shift + F7       Add a pane beside
  Ctrl+Shift+F7    Add a pane below
  Shift + F6       Release a pane
  Shift + F8       Ungroup the card

  Click either back pane and type.
  Flip away and back: focus returns there.

  Demo shortcuts apply in this window only.
  Stop the launcher with Ctrl+C.
""", back="""  TERMINAL

  A live app on the back.
  Shares this face with
  Notes.

  F8 flips the whole card.

  Use this shell normally.
  Your apps stay running.
""", notes="""  NOTES

  Two apps on one face.
  Both stay interactive.

  F8         Flip
  Shift+F6   Release pane
  F6         Mark pane
  Shift+F7   Add beside

  Flip away and back:
  focus returns here.
""")
        command = ["sh", "-c", f"printf '\\n  HYPRFLIP — {face.upper()}\\n\\n  Readable text, real application.\\n\\n  LEFT                         RIGHT\\n'; exec cat"]
        if demo:
            welcome = root / f"{face}.txt"
            welcome.write_text("\n" + content[face] + "\n")
            command = ["bash", "--noprofile", "--norc", "-c",
                       'cat -- "$1"; exec bash --noprofile --norc', "hyprflip-demo", str(welcome)]
        with (root / f"{face}.log").open("wb") as log:
            process = subprocess.Popen([
                "foot", *(["--config", "/dev/null"] if demo else []),
                "--app-id", f"hyprflip-{face}", "--title", f"Hyprflip {face}",
                "--override", f"colors-dark.background={color}", "--override",
                f"font=monospace:size={16 if demo else 20}", *command
            ], env=env | ({"PS1": "\\w > "} if demo else {}), stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
    if demo:
        deadline = time.monotonic() + 8
        addresses = {}
        while time.monotonic() < deadline:
            addresses = {w["class"]: w["address"] for w in json.loads(ctl("-j", "clients"))}
            if all(f"hyprflip-{face}" in addresses for face, _ in faces):
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Demo terminals did not open; check the pane logs")
        front, back, notes = (addresses[f"hyprflip-{name}"] for name in ("front", "back", "notes"))
        focus(front); ctl("hyprflip", "mark")
        focus(back); ctl("hyprflip", "card"); ctl("hyprflip", "flip")
        focus(notes); ctl("hyprflip", "mark")
        focus(back); ctl("hyprflip", "attach"); ctl("hyprflip", "flip")
        ctl("repl", "hl.config({plugin={hyprflip={duration_ms=420,notifications=true}}})")
        print("DEMO: click inside the window, then press F8 to flip. Stop this launcher with Ctrl+C to exit.", flush=True)
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
