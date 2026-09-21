#!/usr/bin/env python3
"""Check a workspace-only container trial alongside native pairs and Hyprglass."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("session", type=Path)
parser.add_argument("--hyprglass", type=Path, required=True)
parser.add_argument("--all-workspaces", action="store_true", help="Also check expanding the trial to all normal workspaces")
args = parser.parse_args()
env = environment(args.session)
project = Path(__file__).resolve().parent.parent
root = args.session.parent
config = root / "hyprland.lua"
original = config.read_text()
processes = []
checks = []


def ctl(*arguments):
    result = subprocess.run(["hyprctl", *arguments], env=env, capture_output=True, text=True, timeout=8)
    output = result.stdout.strip()
    if result.returncode or output.startswith("error") or "could not be loaded" in output or "Lua error" in output:
        raise AssertionError((arguments, output, result.stderr))
    return output


def wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.04)
    raise AssertionError("Condition did not settle")


def status():
    return json.loads(ctl("hyprflip", "status"))


def windows():
    return json.loads(ctl("-j", "clients"))


def focus(address):
    ctl("dispatch", f'hl.dsp.focus({{window="address:{address}"}})')


def key(name):
    subprocess.run(["wtype", "-M", "logo", "-M", "ctrl", "-M", "alt", "-k", name],
                   env=env, check=True, timeout=5)
    time.sleep(.12)


def passed(name):
    checks.append(name)
    print("PASS", name, flush=True)


try:
    assert not json.loads(ctl("-j", "plugin", "list")), "Use a fresh nested fixture session"
    for source, name in ((project / "build/hyprflip.so", "hyprflip.so"),
                         (project / "build/containers/provider/upstream/libhy3.so", "libhy3.so"),
                         (args.hyprglass, "hyprglass.so")):
        shutil.copy2(source, root / name)
    core = (project / "examples/hyprflip.lua").read_text().replace(
        'os.getenv("HOME") .. "/.local/lib/hyprflip/hyprflip.so"', json.dumps(str(root / "hyprflip.so")))
    trial = (project / "examples/containers-trial.lua").read_text().replace(
        'os.getenv("HOME") .. "/.local/lib/hyprflip/containers/libhy3.so"', json.dumps(str(root / "libhy3.so")))
    pilot_config = (original + "\n" + core + "\n" +
                     '\n'.join(f'hl.workspace_rule({{workspace="{n}",layout="dwindle"}})' for n in (1, 3, 5)) +
                     "\n" + trial + "\n" +
                     f'hl.plugin.load({json.dumps(str(root / "hyprglass.so"))})\n' +
                     'if hl.plugin.hyprglass then hl.plugin.hyprglass.config({enabled=true,manage_window_blur=true}) end\n' +
                     'hl.config({input={resolve_binds_by_sym=true}})\n')
    config.write_text(pilot_config)
    ctl("reload")
    wait(lambda: len(json.loads(ctl("-j", "plugin", "list"))) == 3)
    assert not ctl("configerrors")
    ctl("dispatch", "hl.dsp.focus({workspace=1})")
    a, b = [w["address"] for w in windows() if w["class"] in ("hyprflip-front", "hyprflip-back")]
    focus(a); key("m"); focus(b); key("p")
    assert len(status()["pairs"]) == 1 and not status()["containers"]
    key("f"); wait(lambda: not status()["animating"])
    assert status()["pairs"][0]["current"] == b
    passed("existing shortcuts still create and flip a native dwindle pair")

    ctl("dispatch", "hl.dsp.focus({workspace=8})")
    for number in range(3):
        app_id = f"hyprflip-trial-{number}"
        process = subprocess.Popen(["foot", "--config", "/dev/null", "--app-id", app_id,
                                    "--override", "colors-dark.alpha=0.8", "sh", "-c", "exec cat"],
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        processes.append(process)
        wait(lambda: any(w["class"] == app_id for w in windows()))
    panes = [next(w["address"] for w in windows() if w["class"] == f"hyprflip-trial-{n}") for n in range(3)]
    front, back, notes = panes
    for address in panes:
        ctl("dispatch", f'hl.dsp.window.tag({{tag="hyprglass_enabled",window="address:{address}"}})')
    focus(front); key("m"); focus(back); key("p")
    key("f"); wait(lambda: not status()["animating"])
    focus(notes); key("m"); focus(back); key("h")
    assert len(status()["containers"]) == 1
    assert [len(face) for face in status()["containers"][0]["faces"]] == [1, 2]
    layouts = {w["id"]: w["tiledLayout"] for w in json.loads(ctl("-j", "workspaces"))}
    assert layouts[1] == "dwindle" and layouts[8] == "hy3", layouts
    passed("workspace 8 alone uses hy3; mark, pair and horizontal attach shortcuts work")

    ctl("repl", "hl.config({plugin={hyprflip={duration_ms=1200,notifications=false}}})")
    time.sleep(.5)
    ctl("hyprflip", "flip")
    assert status()["animating"], status()
    assert any("hyprglass_disabled" in w["tags"] for w in windows() if w["address"] in panes)
    wait(lambda: status()["progress"] > .62)
    subprocess.run(["grim", str(root / "glass-container.png")], env=env, check=True, timeout=8)
    wait(lambda: not status()["animating"])
    assert not status()["last_fallback"], status()
    assert all("hyprglass_disabled" not in w["tags"] for w in windows() if w["address"] in panes)
    passed("container GPU flip suppresses then restores Hyprglass")

    ctl("reload"); assert not ctl("configerrors")
    assert len(status()["pairs"]) == 1 and len(status()["containers"]) == 1
    focus(status()["containers"][0]["current"])
    if status()["containers"][0]["active"] == 0:
        key("f"); wait(lambda: not status()["animating"])
    focus(notes); key("e")
    assert all(notes not in face for face in status()["containers"][0]["faces"])
    key("m"); focus(back); key("v")
    assert [len(face) for face in status()["containers"][0]["faces"]] == [1, 2]
    passed("config reload preserves both backends; release and vertical attach shortcuts work")

    if args.all_workspaces:
        before = status()
        native = before["pairs"][0]
        # Ungroup while dwindle still owns the native group. In this pinned
        # hy3, ungrouping after a layout switch can leave an expired target.
        focus(native["current"]); key("u")
        assert not status()["pairs"]
        assert all(w["acceptsInput"] for w in windows() if w["address"] in (native["front"], native["back"]))
        config.write_text(pilot_config.replace('local trial_workspace = "8"', 'local trial_workspace = nil'))
        ctl("reload"); assert not ctl("configerrors")
        wait(lambda: all(w["tiledLayout"] == "hy3" for w in json.loads(ctl("-j", "workspaces")) if w["id"] > 0))
        assert not status()["pairs"]
        assert status()["containers"] == before["containers"]
        passed("expanding to all normal workspaces preserves the card and both ungrouped native apps")

        # Re-pairing after the switch upgrades the former native pair.
        focus(native["front"]); key("m"); focus(native["back"]); key("p")
        assert not status()["pairs"] and len(status()["containers"]) == 2
        converted = next(c for c in status()["containers"] if native["front"] in c["faces"][0])
        assert converted["faces"] == [[native["front"]], [native["back"]]]
        focus(native["front"]); key("f"); wait(lambda: not status()["animating"])
        assert next(c for c in status()["containers"] if c["id"] == converted["id"])["current"] == native["back"]
        passed("a former native pair upgrades to a working container without losing either app")

        for workspace in (3, 5, 11):
            ctl("dispatch", f"hl.dsp.focus({{workspace={workspace}}})")
            assert json.loads(ctl("-j", "activeworkspace"))["tiledLayout"] == "hy3"
        process = subprocess.Popen(["foot", "--config", "/dev/null", "--app-id", "hyprflip-trial-pad", "sh", "-c", "exec cat"],
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        wait(lambda: any(w["class"] == "hyprflip-trial-pad" for w in windows()))
        pad = next(w["address"] for w in windows() if w["class"] == "hyprflip-trial-pad")
        ctl("dispatch", 'hl.dsp.window.move({window="address:' + pad + '",workspace="special:trial-pad",follow=false})')
        assert next(w for w in json.loads(ctl("-j", "workspaces")) if w["name"] == "special:trial-pad")["tiledLayout"] == "dwindle"
        assert len(status()["containers"]) == 2
        passed("new workspaces override saved dwindle settings; special scratchpads remain dwindle")

        focus(back)
        ctl("hyprflip", "workspace", "3")
        wait(lambda: all(w["workspace"]["id"] == 3 for w in windows() if w["address"] in panes))
        key("f"); wait(lambda: not status()["animating"])
        before = status()
        ctl("reload"); assert not ctl("configerrors")
        assert status()["containers"] == before["containers"]
        assert len(status()["containers"]) == 2
        passed("whole-card moves and reload work after enabling containers everywhere")

    key("u")
    assert len(status()["containers"]) == int(args.all_workspaces)
    assert len(status()["pairs"]) == int(not args.all_workspaces)
    assert all(w["acceptsInput"] for w in windows() if w["address"] in panes)
    passed("unpair restores ordinary panes without affecting the other pair")
finally:
    try:
        # Keep Hyprglass mapped while the other layouts/plugins tear down.
        # A bulk unload crashed during hy3's layout removal after Hyprglass
        # had already unloaded in this installed Hyprglass build.
        config.write_text(original + f'\nhl.plugin.load({json.dumps(str(root / "hyprglass.so"))})\n')
        ctl("reload"); assert not ctl("configerrors")
        config.write_text(original)
        ctl("reload"); assert not ctl("configerrors")
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        output = project / ("test-results/all-workspaces.json" if args.all_workspaces else "test-results/trial.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps({"checks_passed": checks, "count": len(checks)}, indent=2) + "\n")
print(f"{len(checks)} workspace trial checks passed", flush=True)
