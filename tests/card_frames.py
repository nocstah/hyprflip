#!/usr/bin/env python3
"""Card frame input, gap parity and unload checks in a disposable compositor.

Requires a fresh nested_session.py (without --containers), foot, grim, wtype,
ImageMagick, wayland-scanner and Wayland client development headers.
Pass --protocol from the matching Hyprland source for real mouse input checks.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from control import environment

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
from workflow import Hyprctl

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--protocol', type=Path, required=True)
parser.add_argument('--captures', type=Path, required=True)
args = parser.parse_args()
root = args.session.parent
env = environment(args.session)
ipc = Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
args.captures.mkdir(parents=True, exist_ok=True)
loaded, processes, checks = [], [], []
output = None


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.03)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name, color='20323a'):
    app = 'hyprflip-frame-' + name
    process = subprocess.Popen([
        'foot', '--config', '/dev/null', '--app-id', app, '--title', name,
        '--override', f'colors-dark.background={color}', '--override', 'font=monospace:size=16',
        'sh', '-c', 'printf "\\n  %s\\n\\n  Hyprflip card preview\\n\\n  Real windows. Shared card.\\n" "$1"; exec cat', 'frame', name],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(w['class'] == app for w in ipc.windows().values()))
    return next(a for a, w in ipc.windows().items() if w['class'] == app)


def card(): return ipc.status()['containers'][0]
def frame(): return ipc.status()['card_frames'][0]
def config_eval(value): ipc.call('eval', value)
def setting(value): config_eval('hl.config({plugin={hyprflip={' + value + '}}})')
def capture(name):
    time.sleep(.12)
    subprocess.run(['grim', '-l', '1', '-o', output, str(args.captures / (name + '.png'))],
                   env=env, check=True, capture_output=True, timeout=8)


def focused_outline(address, name):
    ipc.focus(address)
    capture(name)
    window = ipc.windows()[address]
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    x = round((window['at'][0] + window['size'][0] / 2 - monitor['x']) * monitor['scale'])
    y = round((window['at'][1] - 1 - monitor['y']) * monitor['scale'])
    pixel = subprocess.check_output(['magick', str(args.captures / (name + '.png')),
                                     '-crop', f'1x1+{x}+{y}', '-depth', '8', 'rgb:-'], timeout=8)
    assert max(abs(a-b) for a,b in zip(pixel, (36,93,168))) < 12, (name, pixel, x, y)


def ring(): return ipc.status()['card_rings'][0]


def accent_ring(name):
    # The reported box is the ring's inner edge; its stroke lies just outside.
    wait(lambda: ipc.status()['card_rings'])
    assert ring()['color'] == '#F78DBB' and ring()['focused'], ring()
    capture(name)
    x, y, w, h = ring()['box']
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    px = round((x - 1 - monitor['x']) * monitor['scale'])
    py = round((y + h / 2 - monitor['y']) * monitor['scale'])
    pixel = subprocess.check_output(['magick', str(args.captures / (name + '.png')),
                                     '-crop', f'1x1+{px}+{py}', '-depth', '8', 'rgb:-'], timeout=8)
    assert max(abs(a-b) for a,b in zip(pixel, (247,141,187))) < 12, (name, pixel, px, py)


def gap(a, b, axis=0):
    windows = ipc.windows()
    left, right = sorted((windows[a], windows[b]), key=lambda w: w['at'][axis])
    return right['at'][axis] - left['at'][axis] - left['size'][axis] - 4  # two 2px borders


def click(expected_change=True, drag=False, button=272, modified=False):
    before = frame()['active'], frame()['unfolded']
    x, y, w, h = frame()['button']
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={int(x+w/2)},y={int(y+h/2)}}})')
    held = None
    if modified:
        held = subprocess.Popen(['wtype', '-M', 'ctrl', '-s', '700', '-m', 'ctrl'], env=env)
        time.sleep(.15)
    pointer = subprocess.Popen([str(root / 'frame-pointer'), str(button)], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert pointer.stdout.readline().strip() == 'down'
    assert (frame()['active'], frame()['unfolded']) == before, 'Action ran on press'
    pointer.communicate('d' if drag else '\n', timeout=5)
    assert pointer.returncode == 0
    if held: held.wait(timeout=3)
    time.sleep(.1)
    if expected_change: wait(lambda: (frame()['active'], frame()['unfolded']) != before)
    else: assert (frame()['active'], frame()['unfolded']) == before


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without --containers'
    for kind, filename in (('client-header', 'frame-pointer-protocol.h'), ('private-code', 'frame-pointer-protocol.c')):
        subprocess.run(['wayland-scanner', kind, str(args.protocol), str(root / filename)], check=True)
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True))
    subprocess.run(['cc', '-o', str(root / 'frame-pointer'), '-I' + str(root),
                    str(project / 'tests/frame_pointer.c'), str(root / 'frame-pointer-protocol.c'), *flags], check=True)
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('frame-' + source.name)
        shutil.copy2(source, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    base = original.replace('layout="dwindle"', 'layout="hy3"') + '''
hl.config({animations={enabled=false},general={gaps_in=14,gaps_out=24}})
if hl.plugin.hyprflip then hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}}) end
'''
    config.write_text(base)
    ipc.call('reload')
    assert not ipc.call('configerrors')
    existing = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in existing)
    config_eval(f'hl.monitor({{output="{output}",mode="1600x1000@60",position="2000x0",scale=1}})')
    base += f'hl.monitor({{output="{output}",mode="1600x1000@60",position="2000x0",scale=1}})\n'
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=61})')
    a, b, c = [spawn(name, color) for name, color in (('Mail', '20323a'), ('Messages', '302c40'), ('Notes', '263830'))]
    assert gap(b, c) == 28, ipc.windows()
    ipc.focused((a, 'mark'), (b, 'pair'), (c, 'mark'), (b, 'attach horizontal'))
    assert gap(b, c) == 28
    assert len(ipc.status()['card_frames']) == 1
    capture('tiled-dark')
    setting('card_frame=false'); assert not ipc.status()['card_frames']
    capture('classic-tabs')
    assert not ipc.status()['card_rings']
    setting('accent_ring=true,accent_color="#F78DBB"')
    accent_ring('classic-accent-ring')
    setting('card_frame=true'); assert len(ipc.status()['card_frames']) == 1
    accent_ring('frame-accent-ring')
    assert ring()['box'][1] < frame()['box'][1], 'the ring surrounds the frame header'
    setting('accent_ring=false'); assert not ipc.status()['card_rings']
    passed('accent ring surrounds Classic and framed cards in the theme accent and turns off cleanly')
    click(); click()
    for kwargs in ({'drag': True}, {'button': 273}, {'modified': True}): click(False, **kwargs)
    passed('compact frame clicks flip once on release; right-click, modifiers and drag-out do not flip')
    probe = root / 'frame-probe.so'
    shutil.copy2(project / 'build/containers/core/motion_probe.so', probe)
    ipc.call('plugin', 'load', str(probe))
    try:
        time.sleep(.4)
        ipc.call('hf-motion-probe', 'start')
        for _ in range(40):
            ipc.status(); time.sleep(.025)
        frames = [f for f in ipc.data('hf-motion-probe', 'stop') if f['monitor'] == output]
        assert len(frames) < 15, len(frames)
        passed(f'status polling does not cause idle redraws ({len(frames)} rendered frames during 40 polls)')
    finally:
        ipc.call('plugin', 'unload', str(probe))
    ipc.focus(b); ipc.action('unfold')
    assert gap(a, b) == 28 and gap(b, c) == 28
    capture('unfolded-dark'); click()
    assert not card()['unfolded']
    passed('Fold restores the folded card and unfolded gaps match regular tiling')
    ipc.focus(b); ipc.action('floating')
    assert card()['floating'] and gap(b, c) == 28
    capture('floating-dark')
    ipc.action('layout vertical'); assert gap(b, c, 1) == 28
    ipc.action('layout horizontal')
    passed('tiled and floating faces use the same 28px empty gap in both axes')

    config.write_text(base + 'hl.workspace_rule({workspace="61",gaps_in={top=7,right=11,bottom=13,left=17}})\n')
    ipc.call('reload')
    errors = ipc.call('configerrors'); assert not errors, errors
    ipc.focus(b)
    ipc.action('layout vertical'); assert gap(b, c, 1) == 20, ipc.windows()
    ipc.action('layout horizontal'); assert gap(b, c) == 28
    ipc.action('floating'); assert not card()['floating'] and gap(b, c) == 28
    ipc.action('layout vertical'); assert gap(b, c, 1) == 20
    ipc.action('layout horizontal')
    passed('directional workspace overrides produce matching tiled/floating gaps (28px horizontal, 20px vertical)')

    config_eval('hl.config({group={groupbar={text_color="rgba(182028ff)",font_size=14}},general={col={active_border="rgba(245da8ff)",inactive_border="rgba(6f777eff)"}}})')
    focused_outline(c, 'tiled-light-other-focus')
    focused_outline(b, 'tiled-light')
    config_eval(f'hl.monitor({{output="{output}",mode="1000x1400@60",position="2000x0",scale=1.25}})')
    ipc.focus(b); ipc.action('layout vertical')
    focused_outline(c, 'portrait-other-focus')
    focused_outline(b, 'portrait-scaled')
    passed('classic tabs remain available; light text theme and fractional-scale portrait frames render')

    ipc.focus(b); ipc.action('unpair')
    assert not ipc.status()['card_frames']
    config.write_text(base.replace('layout="hy3"', 'layout="dwindle"'))
    ipc.call('reload')
    ipc.focused((a, 'mark'), (b, 'pair'))
    assert len(ipc.status()['pairs']) == 1 and not ipc.status()['containers']
    capture('native-pair'); click(); click()
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    assert not ipc.status()['card_frames']
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    assert len(ipc.status()['card_frames']) == 1
    passed('native pairs share the Flip control and fullscreen round trips restore their header')

    occluder = spawn('Cover', '283448')
    ipc.call('dispatch', 'hl.dsp.window.float({action="float"})')
    x, y, w, h = frame()['button']
    ipc.call('dispatch', 'hl.dsp.window.resize({x=260,y=180})')
    ipc.call('dispatch', f'hl.dsp.window.move({{x={int(x-40)},y={int(y-10)}}})')
    click(False)
    capture('covered-control')
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{occluder}"}})')
    wait(lambda: occluder not in ipc.windows())
    passed('a floating app covering the button receives the click without flipping the card underneath')

    core = loaded.pop()
    ipc.call('plugin', 'unload', str(core))
    assert set(ipc.windows()[a]['grouped']) == {a, b}
    capture('native-restored-tabs')
    ipc.call('plugin', 'load', str(core)); loaded.append(core)
    ipc.action(f'adopt {a} {b}')
    assert len(ipc.status()['card_frames']) == 1
    ipc.focus(a); ipc.action('unpair')
    ipc.focused((a, 'mark'), (b, 'pair'))
    config_eval('hl.config({animations={enabled=true}})')
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{b}"}})')
    wait(lambda: b not in ipc.windows())
    for target in reversed(loaded): ipc.call('plugin', 'unload', str(target))
    loaded.clear()
    time.sleep(.4)
    assert a in ipc.windows() and c in ipc.windows()
    passed('unload restores native group tabs, reload/adopt restores the frame, and close-during-unload leaves surviving apps usable')
finally:
    for process in reversed(processes):
        if process.poll() is None: process.terminate()
        process.wait(timeout=5)
    config.write_text(original)
    ipc.call('reload')
    for target in reversed(loaded): ipc.call('plugin', 'unload', str(target))
    if output: ipc.call('output', 'remove', output)
    (root / 'card-frames-results.json').write_text(json.dumps(checks, indent=2) + '\n')
