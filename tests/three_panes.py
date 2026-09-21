#!/usr/bin/env python3
"""Exercise three-pane cards, size rollback and guided creation in isolation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import time

from control import environment
from setup_test import Picker, setup

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
p.add_argument('--hyprglass', type=Path)
args = p.parse_args()
env = environment(args.session)
project, root = Path(__file__).resolve().parent.parent, args.session.parent
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, loaded, checks = {}, [], []
output = None
completed = False
artifacts = project / 'test-results/three-panes'
artifacts.mkdir(parents=True, exist_ok=True)


def wait(fn):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.025)
    raise AssertionError('State did not settle: ' + json.dumps(ipc.status()))


def lua(code): return ipc.call('repl', code)
def active(): return ipc.data('-j', 'activewindow').get('address')
def card(): return ipc.status()['containers'][0]
def passed(name): checks.append(name); print('PASS', name, flush=True)
def pair(a, b): ipc.focus(a); ipc.action('mark'); ipc.focus(b); ipc.action('pair')
def attach(app, anchor, axis):
    ipc.focus(app); ipc.action('mark'); ipc.focus(anchor); ipc.action('attach ' + axis)
def edit(anchor, *answers):
    flow = setup.Edit(ipc, Picker(*answers))
    flow.apply(flow.prepare(anchor))
def visible():
    current, windows = card(), ipc.windows()
    for side, face in enumerate(current['faces']):
        for app in face:
            assert windows[app]['acceptsInput'] == (current['unfolded'] or side == current['active'])
def aligned(face, axis):
    windows = ipc.windows()
    assert all(windows[a]['size'][axis] > 40 for a in face)
    assert max(windows[a]['at'][1-axis] for a in face) - min(windows[a]['at'][1-axis] for a in face) <= 2
    for a, b in zip(face, face[1:]):
        assert windows[a]['at'][axis] + windows[a]['size'][axis] <= windows[b]['at'][axis]
def ratios(face, axis):
    windows = ipc.windows()
    total = sum(windows[a]['size'][axis] for a in face)
    return [windows[a]['size'][axis] / total for a in face]
def capture(name):
    time.sleep(.4)
    subprocess.run(['grim', '-o', output, str(artifacts / (name + '.png'))], env=env,
                   check=True, capture_output=True, timeout=6)
def spawn(name, minimum=None):
    app = 'hyprflip-three-' + name
    if minimum:
        control = root / (app + '.command')
        control.write_text('minimum ' + ' '.join(map(str, minimum)))
        command = ['python', str(project / 'tests/gtk_fixture.py'), app, str(control)]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                   '--override', 'colors-dark.background=17212b', '--override', 'colors-dark.foreground=d6e3ed',
                   'sh', '-c', 'printf "\\n  %s\\n\\n  Three apps share this face.\\n" "$1"; exec cat', 'fixture', name]
    proc = subprocess.Popen(command, env=env | {'GDK_BACKEND': 'wayland', 'GSK_RENDERER': 'cairo'},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes[app] = proc
    wait(lambda: any(w['class'] == app for w in ipc.windows().values()))
    return next(a for a, w in ipc.windows().items() if w['class'] == app)


try:
    assert not ipc.data('-j', 'plugin', 'list')
    libraries = [project / 'build/containers/provider/upstream/libhy3.so', project / 'build/hyprflip.so']
    if args.hyprglass: libraries.append(args.hyprglass)
    for source in libraries:
        library = root / ('three-' + source.name)
        shutil.copy2(source, library)
        ipc.call('plugin', 'load', str(library)); loaded.append(library)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    assert ipc.status()['container_max_panes'] == 3
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=30})')
    lua('hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    apps = [spawn(name) for name in ('Front', 'Mail', 'Chat', 'Notes', 'Terminal', 'Preview')]
    spare = spawn('Extra')
    ipc.move(spare, 32)
    a, b, c, d, e, f = apps
    for transform in (0, 1):
        axis = 'horizontal' if transform == 0 else 'vertical'
        lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5,transform={transform}}})')
        pair(a, b); attach(c, b, axis)
        ipc.focus(b)
        ipc.call('dispatch', f'hl.dsp.window.resize({{x={100 if transform == 0 else 0},y={100 if transform else 0},relative=true}})')
        time.sleep(.3)
        before = ratios([b, c], transform)
        # An opposite H/V argument must not unexpectedly rearrange an existing split.
        attach(d, b, 'vertical' if transform == 0 else 'horizontal')
        time.sleep(.3)
        assert card()['faces'] == [[a], [b, c, d]]
        aligned([b, c, d], transform)
        assert abs(ratios([b, c], transform)[0] - before[0]) < .025
        attach(e, a, axis); edit(a, 'add', f)
        assert card()['faces'] == [[a, e, f], [b, c, d]] and active() == f
        aligned([a, e, f], transform)
        passed(f'rotation {transform}: both faces accept three apps and retain their axis and relative sizes')

        before = deepcopy(card())
        ipc.focus(spare); ipc.action('mark'); ipc.focus(f)
        try: ipc.action('attach')
        except setup.SetupError as error: assert 'three apps' in str(error)
        else: raise AssertionError('A fourth pane must be refused')
        assert card() == before and ipc.status()['marked'] == spare
        ipc.action('cancel')
        for side in card()['faces']:
            for app in side:
                ipc.focus(app); ipc.action('flip'); ipc.action('flip')
                assert active() == app
                visible()
        ipc.focus(a); capture(f'rotation-{transform}-front')
        ipc.focus(b); capture(f'rotation-{transform}-back')
        passed(f'rotation {transform}: fourth app is refused and all six apps retain per-face focus and input ownership')

        ipc.action('workspace 31')
        assert all(ipc.windows()[app]['workspace']['id'] == 31 for app in apps)
        assert active() == b
        ipc.action('workspace 30')
        ipc.action('unfold'); assert card()['unfolded']; visible()
        unfolded = ipc.windows()
        assert abs(unfolded[a]['at'][transform] - unfolded[b]['at'][transform]) <= 2
        assert unfolded[a]['at'][1-transform] + unfolded[a]['size'][1-transform] <= unfolded[b]['at'][1-transform]
        capture(f'rotation-{transform}-unfolded')
        for side in (0, 1):
            for index in (0, 1, 2):
                face = card()['faces'][side]
                target = face[index]
                anchor = next(app for app in face if app != target)
                ipc.focus(anchor); edit(anchor, 'release:' + target)
                assert target not in card()['faces'][side] and active() == anchor and card()['unfolded']
                assert ipc.windows()[target]['acceptsInput']
                edit(anchor, 'add', target)
                assert len(card()['faces'][side]) == 3 and active() == target and card()['unfolded']
                aligned(card()['faces'][side], transform); visible()
        ipc.focus(a); ipc.action('unfold')
        assert not card()['unfolded'] and active() == a
        ipc.action('unpair')
        passed(f'rotation {transform}: moving, unfolding and removing every pane position preserve all remaining apps')

    # Create a three-app reverse face, with a remote third app and cancellation
    # at its picker. All selections must precede imports and any card mutation.
    ipc.focus(a)
    before = deepcopy(ipc.status())
    flow = setup.Setup(ipc, Picker(b, c, 'workspace:32', None))
    try: flow.prepare(a)
    except setup.Cancelled: pass
    else: raise AssertionError('Cancelling the third picker must abort')
    assert ipc.status() == before and ipc.windows()[spare]['workspace']['id'] == 32
    flow = setup.Setup(ipc, Picker(b, c, 'workspace:32', spare))
    flow.apply(flow.prepare(a))
    assert card()['faces'] == [[a], [b, c, spare]] and active() == a and not card()['unfolded']
    assert ipc.windows()[spare]['workspace']['id'] == 30
    visible()
    processes['hyprflip-three-Extra'].terminate()
    wait(lambda: spare not in ipc.windows())
    assert card()['faces'] == [[a], [b, c]]
    ipc.action('flip'); ipc.action('flip'); assert active() == a
    ipc.action('unpair')
    passed('guided creation can import a third app; Escape is inert and a hidden pane closing preserves the card')

    # At 2560 logical pixels, two panes fit a 930px minimum and three cannot.
    lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5,transform=0}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=33})')
    big, back = spawn('Minimum', (900, 550)), spawn('Minimum back')
    pair(big, back)
    companion = spawn('Minimum companion')
    attach(companion, big, 'horizontal')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=34})')
    third = spawn('Refused third')
    ipc.focus(big)
    before = deepcopy(card())
    flow = setup.Edit(ipc, Picker('add', 'workspace:34', third))
    try: flow.apply(flow.prepare(big))
    except setup.SetupError as error: assert 'too small' in str(error), str(error)
    else: raise AssertionError('A third pane below the application minimum must fail')
    assert card()['faces'] == before['faces'] and active() == big and not card()['unfolded']
    assert ipc.windows()[third]['workspace']['id'] == 34 and ipc.status()['marked'] is None
    time.sleep(.3)
    assert ipc.windows()[big]['size'][0] >= 930
    visible(); ipc.action('unpair')
    passed('a real size-limited third-app import rolls back to its workspace and restores the two-app card')

    # Three across normally unfolds into two rows. A tall application's minimum
    # can require the side-by-side fallback, which still must remain usable.
    ipc.call('dispatch', 'hl.dsp.focus({workspace=35})')
    tall, reverse = spawn('Tall minimum', (300, 850)), spawn('Tall reverse')
    pair(tall, reverse)
    for name in ('Tall companion', 'Tall third'):
        extra = spawn(name)
        attach(extra, tall, 'horizontal')
    ipc.focus(tall); ipc.action('unfold')
    assert card()['unfolded']
    time.sleep(.3)
    windows = ipc.windows()
    assert windows[tall]['size'][1] >= 880
    assert windows[tall]['at'][1] == windows[reverse]['at'][1]
    assert windows[reverse]['at'][0] > windows[tall]['at'][0]
    visible(); ipc.action('unfold'); ipc.action('unpair')
    passed('three-pane unfolding prefers readable rows/columns and falls back to the other axis when minimum sizes require it')
    completed = True
finally:
    if loaded:
        ipc.action('finish')
        for current in list(ipc.status()['containers']):
            ipc.focus(current['current']); ipc.action('unpair')
    for proc in processes.values():
        if proc.poll() is None: proc.terminate()
    for proc in processes.values():
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)
    # Keep Hyprglass alive until the core and layout are unloaded.
    if len(loaded) >= 2:
        for library in (loaded[1], loaded[0], *loaded[2:]):
            ipc.call('plugin', 'unload', str(library))
    config.write_text(original); ipc.call('reload')
    if output: ipc.call('output', 'remove', output)
    assert not ipc.call('configerrors')
    (artifacts / 'results.json').write_text(json.dumps({'completed': completed, 'count': len(checks),
                                                     'checks': checks}, indent=2) + '\n')
