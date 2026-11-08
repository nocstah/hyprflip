#!/usr/bin/env python3
"""A saved card whose apps have minimum sizes, restored in a disposable compositor.

Saved cards used to be rebuilt pane by pane inside the front app's tile, so a
floating card failed whenever that tile was narrower than one app's minimum
size. The core's restore now grows a floating card to fit its apps, keeps it
on its screen, and names the app that cannot fit when no card would.
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


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError('Timed out')
def passed(message): checks.append(message); print('PASS', message, flush=True)
def spawn(name, minimum=None):
    app = 'hyprflip-fit-' + name
    if minimum:
        control = root / (app + '.control'); control.write_text('minimum %d %d' % minimum)
        command = ['python3', str(project / 'tests/gtk_fixture.py'), app, str(control)]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', app, 'cat']
    processes.append(subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)
def restore(box, front, back):
    face = lambda side, panes: f'{side} horizontal {panes[0][0]} ' + ' '.join(f'{a}:{r}' for a, r in panes)
    return ipc.batch(['hyprflip restore quiet floating 0 0 ' + ' '.join(map(str, box)) + ' ' +
                      face('front', front) + ' ' + face('back', back)])[-1]
def cards(): return ipc.status()['containers']
def release():
    for c in cards(): ipc.focused((c['current'], 'unpair'))
    wait(lambda: not cards())


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without --containers'
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    source = project / 'build/hyprflip.so'; target = root / ('fit-' + source.name)
    shutil.copy2(source, target); ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original + f'\nhl.monitor({{output="{output}",mode="1920x1080@60",position="4000x0",scale=1}})\n'
                      'hl.workspace_rule({workspace="51",monitor="' + output + '"})\n')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=51})')
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    left, top = monitor['x'], monitor['y']
    right, bottom = left + monitor['width'], top + monitor['height']

    front, other, third = spawn('front'), spawn('other'), spawn('third')
    wide = spawn('wide', (700, 300))
    reply = restore([left + 50, top + 50, 300, 400], [(front, 1)], [(wide, 1)])
    assert reply.startswith('ok'), reply
    (card,) = cards(); x, y, width, height = card['box']
    assert width >= 700 and left <= x and x + width <= right and top <= y and y + height <= bottom, card
    assert card['faces'] == [[front], [wide]], card
    passed('a floating card restored from a box narrower than an app grows to fit it, on screen')

    release()
    reply = restore([right - 120, top + 60, 300, 400], [(front, 1)], [(wide, 1)])
    assert reply.startswith('ok'), reply
    (card,) = cards(); x, y, width, height = card['box']
    assert width >= 700 and left <= x and x + width <= right and abs(y - (top + 60)) <= 4, card
    passed('a card that would grow past the screen edge is moved back onto the screen, and only across')

    release()
    # An update puts a floating card back exactly where it was, even partly off its screen.
    saved = [right - 400, top + 60, 800, 400]
    reply = restore(saved, [(front, 1)], [(wide, 1)])
    assert reply.startswith('ok'), reply
    (card,) = cards()
    assert all(abs(p - q) <= 4 for p, q in zip(card['box'], saved)), (saved, card)
    passed('a card that fits its apps as given stays exactly where it was asked to be')

    release()
    # The fixture needs 700 px of a 20% share: 3500 px, wider than the 1920 px screen.
    reply = restore([left + 50, top + 50, 600, 400], [(front, 1)], [(wide, .2), (other, .8)])
    assert reply.startswith('error: ') and 'needs at least' in reply and 'screen has' in reply, reply
    assert 'hyprflip-fit-wide' in reply, reply
    assert not cards(), cards()
    assert all(a in ipc.windows() for a in (front, wide, other)), 'Apps closed'
    passed('a card that cannot fit the screen is refused with the app and sizes named, apps left open')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    for library in reversed(loaded):
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    if output: ipc.call('output', 'remove', output)
    (root / 'fit-results.json').write_text(json.dumps(checks, indent=2))
