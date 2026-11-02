#!/usr/bin/env python3
"""Send hyprctl arguments to an explicitly selected disposable test session."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

def environment(connection):
    data = json.loads(Path(connection).read_text())
    runtime = Path(data["XDG_RUNTIME_DIR"]).resolve()
    if not runtime.is_relative_to(Path("/tmp")) or data["HYPRLAND_INSTANCE_SIGNATURE"] == os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise RuntimeError("Tests must target a disposable session under /tmp, never the live desktop")
    return os.environ | data

def session_windows(env, seconds=15):
    """Waits for the session's own two windows, which tests/nested_session.py opens a second
    after it writes session.json. A suite started straight after loses the keyboard to them."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        reply = subprocess.run(["hyprctl", "-j", "clients"], env=env, capture_output=True, text=True, timeout=8)
        if {"hyprflip-front", "hyprflip-back"} <= {window["class"] for window in json.loads(reply.stdout)}:
            return
        time.sleep(.05)
    raise AssertionError("The session's own two windows did not open: use a fresh nested session")

if __name__ == "__main__":
    env = environment(sys.argv[1])
    raise SystemExit(subprocess.run(["hyprctl", *sys.argv[2:]], env=env).returncode)
