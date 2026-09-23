#!/usr/bin/env python3
"""Application-constrained unfold on laptop-sized disposable dwindle outputs."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--library', type=Path, default=project / 'build/hyprflip.so')
args = parser.parse_args()
root = args.session.parent
env = environment(args.session) | {'GDK_SCALE': '1', 'GSK_RENDERER': 'cairo', 'GDK_BACKEND': 'wayland'}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library = root / 'unfold-hyprflip.so'
loaded, output = False, None

def wait(predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('Unfold test did not settle')

def card():
    cards = ipc.status()['containers']
    assert len(cards) == 1, cards
    return cards[0]

def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)

def spawn(name, minimum):
    app = 'hyprflip-unfold-' + name
    control = root / (app + '.control')
    control.write_text('minimum %d %d' % minimum)
    process = subprocess.Popen(['python3', str(project / 'tests/gtk_fixture.py'), app, str(control)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app), control

def geometry(members):
    windows = ipc.windows()
    return {a: (windows[a]['at'], windows[a]['size']) for a in members}

try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without demo flags'
    shutil.copy2(args.library, library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    for width, height in ((1440, 900), (1280, 800)):
        for frame in (False, True):
            config.write_text(original + f'''
hl.monitor({{output="{output}",mode="{width}x{height}@60",position="2000x0",scale=1}})
hl.workspace_rule({{workspace="81",monitor="{output}"}})
hl.config({{general={{gaps_in=6,gaps_out=10,border_size=2}},animations={{enabled=false}},
    plugin={{hyprflip={{duration_ms=0,notifications=false,card_gap=12,card_frame={str(frame).lower()}}}}}}})
''')
            ipc.call('reload'); assert not ipc.call('configerrors')
            ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
            ipc.call('dispatch', 'hl.dsp.focus({workspace=81})')
            front, front_control = spawn('front', (800, 150))
            back, _ = spawn('back', (430, 460))
            ipc.focused((front, 'mark'), (back, 'card'))
            extra, _ = spawn('extra', (430, 460))
            ipc.focused((extra, 'mark'), (back, 'attach horizontal'))
            ipc.focus(front)
            members = [front, back, extra]
            folded = deepcopy(card())
            before = geometry(members)
            ipc.action('unfold')
            assert card()['unfolded']
            windows = ipc.windows()
            assert all(windows[a]['acceptsInput'] for a in members)
            assert card()['faces'] == folded['faces'] and card()['layouts'] == folded['layouts']
            assert windows[back]['at'][1] > windows[front]['at'][1]
            assert windows[back]['size'][1] > windows[front]['size'][1]
            assert windows[back]['size'][1] >= 460 and windows[extra]['size'][1] >= 460
            assert windows[front]['size'][1] >= 150
            assert windows[front]['at'][1] + windows[front]['size'][1] + 16 == windows[back]['at'][1]
            assert windows[back]['at'][0] + windows[back]['size'][0] + 16 == windows[extra]['at'][0]
            subprocess.run(['grim', '-o', output, str(root / f'unfold-{width}-{height}-{frame}.png')],
                           env=env, check=True, timeout=8)
            ipc.action('unfold')
            assert not card()['unfolded'] and geometry(members) == before
            assert card()['layouts'] == folded['layouts']
            passed(f'{width}x{height}, frame={frame}: unequal faces unfold within the tile and fold back to the exact saved arrangement')

            # Both axes really are impossible now. Refuse without altering
            # the existing folded card, focus, proportions or app processes.
            front_control.write_text('minimum 800 460')
            time.sleep(.25)
            ipc.focus(front)
            unchanged = deepcopy(card())
            try:
                ipc.action('unfold')
            except w.SetupError:
                pass
            else:
                raise AssertionError('Unfold accepted impossible app minima')
            assert card() == unchanged
            assert ipc.data('-j', 'activewindow')['address'] == front
            ipc.action('unpair')
            for address in members:
                ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
            wait(lambda: not any(a in ipc.windows() for a in members))
    passed('impossible application sizes keep the folded card, focus and proportions intact')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    for process in processes:
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill()
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        finally:
            config.write_text(original)
            ipc.call('reload')
    if output: ipc.call('output', 'remove', output)
    (root / 'unfold-results.json').write_text(json.dumps(checks, indent=2) + '\n')
