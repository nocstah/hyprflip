#!/usr/bin/env python3
"""Describe open native cards for the core's restore action, and put a restored
tiled card back in its tile. Used by scripts/install.py."""
import json
import subprocess


def ctl(*args):
    p = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout.strip()


def describe(card):
    """A native card as the core's restore action expects it."""
    x, y, width, height = card["box"]
    line = [("floating" if card.get("floating") else "tiled"), str(card["active"]), str(int(bool(card.get("unfolded")))),
            f"{x:.12g}", f"{y:.12g}", f"{width:.12g}", f"{height:.12g}"]
    for name, face, layout in zip(("front", "back"), card["faces"], card["layouts"]):
        line += [name, layout["axis"], layout["focused"]] + [f"{w}:{r:.12g}" for w, r in zip(face, layout["ratios"])]
    return " ".join(line)


def settle(line, ctl=ctl):
    """Return a restored tiled card to its saved tile.

    While a tiled card is briefly separate tiles, dwindle can reflow the
    workspace: a card beside a neighbour may come back stacked under it. Undo
    that with dwindle's own controls, keeping a step only if it brings the
    card closer to where it was, then restore its size.
    """
    parts = line.split()
    if parts[0] != "tiled":
        return
    target = [float(v) for v in parts[3:7]]
    members = {token.split(":")[0] for token in parts if ":" in token}

    def card():
        return next((c for c in json.loads(ctl("hyprflip", "status")).get("containers", [])
                     if {a for face in c["faces"] for a in face} == members), None)

    def distance():
        found = card()
        return sum(abs(p - q) for p, q in zip(found["box"], target)) if found else None

    best = distance()
    if best is None or best <= 4:
        return
    ctl("dispatch", f'hl.dsp.focus({{window="address:{card()["current"]}"}})')
    for message in ("togglesplit", "swapsplit"):
        ctl("dispatch", f'hl.dsp.layout("{message}")')
        now = distance()
        if now is not None and now < best - 1:
            best = now
        else:
            ctl("dispatch", f'hl.dsp.layout("{message}")')
    x, y, width, height = card()["box"]
    if abs(target[2] - width) > 2 or abs(target[3] - height) > 2:
        ctl("dispatch", f'hl.dsp.window.resize({{x={round(target[2] - width)},y={round(target[3] - height)},relative=true}})')
