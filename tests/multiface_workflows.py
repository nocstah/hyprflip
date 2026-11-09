#!/usr/bin/env python3
"""Cards with three and four faces, in a disposable compositor with only the core loaded.

A card turns to its next face on each flip and comes round to the front again.
`card <id> show <n>` turns straight to a face. Attaching as a new face adds one,
taking the last app off a face removes it, and unfolding lays every face out side
by side.
"""
import argparse
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

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
args = p.parse_args()
root = args.session.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
processes, loaded, checks = [], [], []
output = None


def wait(fn, what='condition'):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError('Timed out waiting for ' + what)
def passed(message): checks.append(message); print('PASS', message, flush=True)
def spawn(name):
    app = 'hyprflip-face-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, '--title', app, 'cat'],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()), app)
    return next(a for a, win in ipc.windows().items() if win['class'] == app)
def cards(): return ipc.status()['containers']
def card():
    (c,) = cards(); return c
def restore(box, faces, active=0, mode='floating'):
    words = ['front', 'back'] + ['face'] * (len(faces) - 2)
    line = ' '.join(f'{word} horizontal {apps[0]} ' + ' '.join(f'{a}:1' for a in apps) for word, apps in zip(words, faces))
    return ipc.batch([f'hyprflip restore quiet {mode} {active} 0 ' + ' '.join(map(str, box)) + ' ' + line])[-1]
def shown(c):
    return [a for a in c['faces'][c['active']] if ipc.windows()[a]['hidden'] is False] if 'hidden' in next(iter(ipc.windows().values())) else c['faces'][c['active']]
def flip(c):
    before = c['active']
    reply = ipc.action(f"card {c['id']} flip"); assert reply.startswith("ok"), reply
    wait(lambda: card()['active'] != before, 'the flip')
    return card()


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session'
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    source = project / 'build/hyprflip.so'; target = root / ('faces-' + source.name)
    shutil.copy2(source, target); ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original + f'\nhl.monitor({{output="{output}",mode="1920x1080@60",position="4000x0",scale=1}})\n'
                      'hl.workspace_rule({workspace="52",monitor="' + output + '"})\n')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=52})')
    status = ipc.status()
    assert status.get('container_max_faces') == 4, status.get('container_max_faces')
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    left, top = monitor['x'], monitor['y']

    a, b, c3, d, e = (spawn(n) for n in ('a', 'b', 'c', 'd', 'e'))
    reply = restore([left + 100, top + 100, 800, 600], [[a], [b, c3], [d]])
    assert reply.startswith('ok'), reply
    c = card()
    assert c['faces'] == [[a], [b, c3], [d]] and c['active'] == 0 and len(c['layouts']) == 3, c
    passed('a card restores with three faces, the second holding two apps')

    order = []
    for _ in range(3):
        c = flip(c); order.append(c['active'])
    assert order == [1, 2, 0], order
    passed('each flip turns to the next face, and the last comes round to the front')

    assert ipc.action(f"card {c['id']} show 3").startswith("ok"); wait(lambda: card()['active'] == 2, 'show 3')
    assert ipc.action(f"card {c['id']} show front").startswith("ok"); wait(lambda: card()['active'] == 0, 'show front')
    try:
        ipc.call('hyprflip', f'card {c["id"]} show 4'); raise AssertionError('show 4 was accepted')
    except w.SetupError as error:
        assert 'face number from 1 to 3' in str(error), error
    passed('card <id> show turns straight to a numbered face and refuses one the card lacks')

    ipc.focused((e, 'mark'), (a, 'attach face'))
    wait(lambda: len(card()['faces']) == 4, 'the fourth face')
    c = card()
    assert c['faces'][3] == [e] and c['active'] == 3, c
    passed('attaching as a new face adds a fourth face and turns the card to it')

    spare = spawn('f')
    try:
        ipc.focused((spare, 'mark'), (e, 'attach face'))
        raise AssertionError('A fifth face was accepted')
    except w.SetupError as error:
        assert 'already has 4 faces' in str(error), error
    assert len(card()['faces']) == 4
    passed('a fifth face is refused, naming the limit')

    ipc.focused((d, 'release'))
    wait(lambda: len(card()['faces']) == 3, 'the face to go')
    c = card()
    assert c['faces'] == [[a], [b, c3], [e]], c
    assert d in ipc.windows() and not any(d in f for f in c['faces'])
    passed('releasing the only app of a face removes the face and leaves the app open')

    ipc.focused((a, 'unfold'))
    wait(lambda: card()['unfolded'], 'unfold')
    boxes = [ipc.windows()[x] for x in (a, b, e)]
    xs = sorted(win['at'][0] for win in boxes)
    assert xs[0] < xs[1] < xs[2], boxes
    assert all(not win.get('hidden', False) for win in boxes)
    passed('unfolding lays all three faces out side by side')
    ipc.focused((a, 'unfold'))
    wait(lambda: not card()['unfolded'], 'fold')

    ipc.focused((b, 'release'), (c3, 'release'))
    wait(lambda: len(card()['faces']) == 2, 'back to two faces')
    ipc.focused((a, 'release'))
    wait(lambda: not cards(), 'the card to dissolve')
    passed('a two-face card still dissolves when a face loses its last app')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    for library in reversed(loaded):
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    if output: ipc.call('output', 'remove', output)
    (root / 'multiface-results.json').write_text(json.dumps(checks, indent=2))
