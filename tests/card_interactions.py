#!/usr/bin/env python3
"""Real window drags, five-app faces and spacing in a disposable compositor."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from control import environment
from setup_test import setup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--protocol', type=Path, required=True)
parser.add_argument('--captures', type=Path, required=True)
args = parser.parse_args()
project, root = Path(__file__).resolve().parents[1], args.session.parent
env = environment(args.session)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, loaded, checks = [], [], []
pointer = held = output = None
args.captures.mkdir(parents=True, exist_ok=True)


def wait(fn):
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.025)
    raise AssertionError(ipc.status())


def lua(value): return ipc.call('eval', value)
def setting(value): lua('hl.config({plugin={hyprflip={' + value + '}}})')
def card(): return ipc.status()['containers'][0]
def passed(name): checks.append(name); print('PASS', name, flush=True)
def capture(name):
    time.sleep(.15)
    subprocess.run(['grim', '-o', output, str(args.captures / (name + '.png'))],
                   env=env, check=True, capture_output=True, timeout=7)


def spawn(name, minimum=None):
    app = 'hyprflip-interaction-' + name
    if minimum:
        control = root / (app + '.command')
        control.write_text('minimum ' + ' '.join(map(str, minimum)))
        command = ['python3', str(project / 'tests/gtk_fixture.py'), app, str(control)]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                   '--override', 'colors-dark.background=20323a', '--override', 'font=monospace:size=16',
                   'sh', '-c', 'printf "\\n  %s\\n\\n  Hyprflip interaction preview\\n" "$1"; exec cat', 'fixture', name]
    proc = subprocess.Popen(command, env=env | {'GDK_BACKEND': 'wayland', 'GSK_RENDERER': 'cairo'},
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(proc)
    wait(lambda: any(w['class'] == app for w in ipc.windows().values()))
    return next(a for a, w in ipc.windows().items() if w['class'] == app)


def floating(app):
    ipc.focus(app)
    ipc.call('dispatch', 'hl.dsp.window.float({action="float"})')
    ipc.call('dispatch', 'hl.dsp.window.resize({x=440,y=300,exact=true})')
    ipc.call('dispatch', 'hl.dsp.window.move({x=2080,y=580})')


def gap(face, axis=0):
    windows = ipc.windows()
    ordered = sorted((windows[a] for a in face), key=lambda w: w['at'][axis])
    return [b['at'][axis] - a['at'][axis] - a['size'][axis] - 4
            for a, b in zip(ordered, ordered[1:])]


def send(command):
    pointer.stdin.write(command + '\n'); pointer.stdin.flush()
    assert pointer.stdout.readline().strip() == 'ok'


def begin(app):
    global pointer, held
    ipc.focus(app)
    w = ipc.windows()[app]
    x, y = (round(w['at'][i] + w['size'][i] / 2) for i in (0, 1))
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x},y={y}}})')
    held = subprocess.Popen(['wtype', '-M', 'logo', '-s', '20000', '-m', 'logo'], env=env)
    wait(lambda: ipc.data('hf-motion-probe', 'input')['mods'] == 64)
    pointer = subprocess.Popen([str(root / 'interaction-pointer'), '--stream'], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert pointer.stdout.readline().strip() == 'ready'
    send('down')
    for _ in range(3): send('move 12 0'); time.sleep(.025)
    assert ipc.data('hf-motion-probe', 'input')['drag'], 'Native window drag did not start'


def hover(side=None):
    wait(lambda: ipc.status()['drop_targets'])
    targets = ipc.status()['drop_targets']
    target = next(t for t in targets if side is None or t['side'] == side)
    x, y, w, h = target['zone']
    for _ in range(3):
        pos = ipc.data('-j', 'cursorpos')
        send(f'move {x+w/2-pos["x"]} {y+h/2-pos["y"]}')
        time.sleep(.06)
    wait(lambda: any(t['hovered'] for t in ipc.status()['drop_targets']))
    return next(t for t in ipc.status()['drop_targets'] if t['hovered'])


def end():
    global pointer, held
    if pointer:
        send('up')
        pointer.communicate('quit\n', timeout=3)
        pointer = None
    if held:
        held.terminate(); held.wait(timeout=3); held = None
    time.sleep(.18)


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh disposable session'
    for kind, filename in (('client-header', 'frame-pointer-protocol.h'), ('private-code', 'frame-pointer-protocol.c')):
        subprocess.run(['wayland-scanner', kind, str(args.protocol), str(root / filename)], check=True)
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True))
    subprocess.run(['cc', '-o', str(root / 'interaction-pointer'), '-I' + str(root),
                    str(project / 'tests/frame_pointer.c'), str(root / 'frame-pointer-protocol.c'), *flags], check=True)
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('interaction-' + source.name)
        shutil.copy2(source, target); ipc.call('plugin', 'load', str(target)); loaded.append(target)
    probe = root / 'interaction-probe.so'
    shutil.copy2(project / 'build/containers/core/motion_probe.so', probe)
    ipc.call('plugin', 'load', str(probe))
    base = original.replace('layout="dwindle"', 'layout="hy3"') + '''
hl.config({animations={enabled=false},general={gaps_in=14,gaps_out=24}})
-- The nested backend can retain a modifier when its parent loses focus.
-- Use only the fixture's virtual keyboard, never the user's real keyboard.
hl.device({name="wl_keyboard",enabled=false})
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), {mouse=true})
if hl.plugin.hyprflip then hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}}) end
'''
    config.write_text(base); ipc.call('reload'); assert not ipc.call('configerrors')
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=81})')
    a, b, c = [spawn(name) for name in ('Mail', 'Messages', 'Notes')]
    assert gap([b, c]) == [28]
    ipc.focused((a, 'mark'), (b, 'pair'), (c, 'mark'), (b, 'attach horizontal'))
    assert gap([b, c]) == [28]
    assert ipc.status()['container_max_panes'] == 5
    setting('card_frame=false,card_gap=12')
    assert not ipc.status()['card_frames'] and gap([b, c]) == [12]
    capture('classic-compact')
    passed('classic tabs and compact spacing apply to existing hy3 cards')

    outsider = spawn('Drag this app'); floating(outsider)
    before = deepcopy(card()['faces'])
    begin(outsider); hover(); capture('drop-preview-classic')
    subprocess.run(['wtype', '-k', 'Escape'], env=env, check=True)
    assert not ipc.status()['drop_targets']
    send('move 1 0'); end()
    assert card()['faces'] == before
    begin(outsider); hover(); send('move 0 200'); end()
    assert card()['faces'] == before
    passed('Escape and releasing outside the target leave membership unchanged')

    begin(outsider); hover(); end()
    wait(lambda: outsider in card()['faces'][1])
    assert len(card()['faces'][1]) == 3 and not ipc.windows()[outsider]['floating']
    assert gap(card()['faces'][1]) == [12, 12]
    passed('a native Super-drag adds a floating outside app to the visible tiled face')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=82})')
    too_big = spawn('Too wide for this split', (1300, 200)); floating(too_big)
    ipc.move(too_big, 81)
    ipc.focus(b)
    before = deepcopy(card())
    begin(too_big); hover(); end()
    assert card()['faces'] == before['faces'] and ipc.windows()[too_big]['floating']
    for s in (0, 1):
        assert all(abs(x-y) < .002 for x, y in zip(card()['layouts'][s]['ratios'], before['layouts'][s]['ratios']))
    ipc.move(too_big, 82)
    passed('a drop below app minimum sizes restores the incoming float and original pane proportions')
    setting('card_frame=true')
    for name in ('Fourth app', 'Fifth app'):
        incoming = spawn(name); floating(incoming)
        begin(incoming); hover(); end()
        wait(lambda: incoming in card()['faces'][1])
    assert len(card()['faces'][1]) == 5 and gap(card()['faces'][1]) == [12]*4
    capture('five-apps')
    incoming = spawn('Sixth app'); floating(incoming)
    before = deepcopy(card()['faces'])
    begin(incoming); assert not hover()['allowed']; capture('full-face'); end()
    assert card()['faces'] == before and ipc.windows()[incoming]['floating']
    passed('frame appearance accepts fourth and fifth apps; a sixth is clearly refused without changing the card')
    ipc.move(incoming, 82)
    ipc.focus(b); ipc.action('unfold')
    assert card()['unfolded']
    incoming = spawn('Front companion'); floating(incoming)
    begin(incoming); assert hover(0)['side'] == 0; capture('unfolded-drop'); end()
    wait(lambda: incoming in card()['faces'][0])
    assert len(card()['faces'][1]) == 5 and card()['unfolded']
    ipc.focus(a); ipc.action('unfold')
    passed('unfolded targets name and attach to the chosen face, leaving the other face intact')

    ipc.focus(a); ipc.action('floating')
    incoming = spawn('Floating companion'); floating(incoming)
    begin(incoming); hover(); end()
    wait(lambda: incoming in card()['faces'][0])
    assert card()['floating'] and len(card()['faces'][0]) == 3
    assert gap(card()['faces'][0]) == [12, 12]
    ipc.focus(a); ipc.action('layout vertical'); assert gap(card()['faces'][0], 1) == [12, 12]
    ipc.action('layout horizontal'); ipc.action('unfold')
    windows = ipc.windows()
    assert windows[a]['at'][1] + windows[a]['size'][1] < windows[b]['at'][1]
    capture('floating-unfolded-rows')
    ipc.action('unfold')
    passed('floating cards keep compact gaps on both axes and unfold large rows above one another')
    setting('card_gap=-1'); assert gap(card()['faces'][0]) == [28, 28]
    setting('card_gap=12,drag_to_add=false')
    outsider = spawn('Disabled drag'); floating(outsider)
    before = deepcopy(card()['faces'])
    begin(outsider); assert not ipc.status()['drop_targets']; end()
    assert card()['faces'] == before
    passed('desktop spacing is reversible and drag-to-add can be disabled')
    setting('drag_to_add=true')
    begin(outsider); hover()
    core = loaded.pop(); ipc.call('plugin', 'unload', str(core)); end()
    assert all(a in ipc.windows() for a in [app for face in before for app in face])
    passed('unloading during a drag removes the target and leaves every app available')
finally:
    end()
    for process in reversed(processes):
        if process.poll() is None: process.terminate()
        process.wait(timeout=5)
    config.write_text(original)
    ipc.call('reload')
    ipc.call('plugin', 'unload', str(probe))
    for target in reversed(loaded): ipc.call('plugin', 'unload', str(target))
    if output: ipc.call('output', 'remove', output)
    (root / 'card-interaction-results.json').write_text(json.dumps(checks, indent=2) + '\n')
