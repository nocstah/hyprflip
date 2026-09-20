#!/usr/bin/env python3
"""Compare poses consumed by real render frames, at identical 600 ms timing.

This measures CPU frame timing and pose sampling, not GPU execution or scanout.
Only the disposable compositor's existing front/back fixtures are used.
"""
import argparse
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("session", type=Path)
parser.add_argument("--baseline", type=Path)
parser.add_argument("--plugin", type=Path, default=Path("build/hyprflip.so"))
parser.add_argument("--output", type=Path, default=Path("test-results/motion.json"))
args = parser.parse_args()
env = environment(args.session)

def ctl(*arguments):
    p = subprocess.run(["hyprctl", *arguments], env=env, capture_output=True, text=True, timeout=10)
    reply = p.stdout.strip()
    if p.returncode or reply.startswith("error") or "could not be loaded" in reply:
        raise AssertionError((arguments, reply, p.stderr))
    return reply

def state():
    return json.loads(ctl("hyprflip", "status"))

def wait_done():
    deadline = time.monotonic() + 3
    while state()["animating"]:
        if time.monotonic() > deadline:
            raise AssertionError("Animation stalled")
        time.sleep(.025)

def focus(address):
    ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')

def percentile(values, fraction):
    return sorted(values)[round((len(values) - 1) * fraction)]

probe = args.session.parent / "motion-probe.so"
shutil.copy2(Path("build/motion_probe.so"), probe)
library = args.session.parent / "motion-hyprflip.so"
assert not any(p["name"].startswith("hyprflip") for p in json.loads(ctl("-j", "plugin", "list")))
windows = json.loads(ctl("-j", "clients"))
a = next(w["address"] for w in windows if w["class"] == "hyprflip-front")
b = next(w["address"] for w in windows if w["class"] == "hyprflip-back")
report = {}
loaded = False
ctl("plugin", "load", str(probe))
try:
    for name, source in (("before", args.baseline), ("after", args.plugin)):
        if source is None:
            continue
        shutil.copy2(source, library)
        ctl("plugin", "load", str(library)); loaded = True
        ctl("repl", "hl.config({plugin={hyprflip={duration_ms=600,notifications=false}}})")
        focus(a); ctl("hyprflip", "mark"); focus(b); ctl("hyprflip", "pair")
        time.sleep(1)
        runs = []
        for run in range(12):
            ctl("hyprflip-motion-probe", "start")
            ctl("hyprflip", "flip")
            assert state()["animating"], state()
            wait_done()
            frames = json.loads(ctl("hyprflip-motion-probe", "stop"))
            active = [f for f in frames if f["state"]["animating"]]
            if not active:
                raise SystemExit("No rendered animation frames: the parent display must be awake and the nested output visible. Previous results are preserved.")
            assert len(active) >= 15, f"Only {len(active)} frames in a 600 ms turn"
            runs.append(frames)
            time.sleep(.05)
        errors, gaps, costs = [], [], []
        for frames in runs:
            active = [f for f in frames if f["state"]["animating"]]
            costs.extend(f["cpu_render_ms"] for f in active)
            for left, right in zip(active, active[1:]):
                elapsed = right["ms"] - left["ms"]
                movement = 600 * (right["state"]["progress"] - left["state"]["progress"])
                errors.append(abs(movement - elapsed))
                gaps.append(elapsed)
        report[name] = {
            "flips": len(runs), "frames": sum(len(r) for r in runs),
            "pose_clock_error_p95_ms": percentile(errors, .95),
            "pose_clock_error_mean_ms": statistics.mean(errors),
            "frame_gap_median_ms": statistics.median(gaps),
            "frame_gap_p95_ms": percentile(gaps, .95),
            "cpu_render_p95_ms": percentile(costs, .95), "runs": runs,
        }
        print(name, json.dumps({k: v for k, v in report[name].items() if k != "runs"}), flush=True)
        ctl("hyprflip", "unpair")
        ctl("plugin", "unload", str(library)); loaded = False
        time.sleep(.6)
    # A frame's pose must track that frame's timestamp, including dropped frames.
    assert report["after"]["pose_clock_error_p95_ms"] < 2, report["after"]["pose_clock_error_p95_ms"]
finally:
    if loaded:
        ctl("hyprflip", "finish")
        if state()["pairs"]:
            ctl("hyprflip", "unpair")
        ctl("plugin", "unload", str(library))
    ctl("plugin", "unload", str(probe))
# Do not overwrite a successful comparison when an interrupted/invisible test
# output prevents another run from completing.
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2))
