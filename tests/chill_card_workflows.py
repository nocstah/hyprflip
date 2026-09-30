#!/usr/bin/env python3
"""Chill mode on a workspace holding a native dwindle card, in a disposable compositor."""
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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--engine', type=Path, required=True, help="Omachill's chillmode.lua with the Hyprflip guard")
args = parser.parse_args()
root = args.session.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library = root / 'chill-card-hyprflip.so'
loaded = False
WS = 91


def lua(code): return ipc.call('repl', code)


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name):
    app = 'hyprflip-chill-card-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, 'sh', '-c', 'exec cat'],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def card():
    cards = ipc.status()['containers']
    assert len(cards) == 1, cards
    return cards[0]


def members(): return [x for face in card()['faces'] for x in face]
def tagged(address): return any(t.rstrip('*') == 'chillmode' for t in ipc.windows()[address]['tags'])
def protect(): return lua(f'return hl.plugin.hyprflip.chill_blocked({WS})') == 'true'
def chilled(): return lua(f'return #hl.get_windows({{workspace={WS}}}) > 0 and chillmode.state ~= nil') and all(
    ipc.windows()[x]['floating'] for x in members())


def visible_boxes():
    c, windows = card(), ipc.windows()
    return [(*windows[x]['at'], *windows[x]['size']) for side, face in enumerate(c['faces'])
            for x in face if c['unfolded'] or side == c['active']]


def inside(inner, outer):
    return (inner[0] >= outer[0] - 1 and inner[1] >= outer[1] - 1 and
            inner[0] + inner[2] <= outer[0] + outer[2] + 1 and inner[1] + inner[3] <= outer[1] + outer[3] + 1)


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    config.write_text(original + '''
hl.config({general={gaps_in=14,gaps_out=24},animations={enabled=false},
    plugin={hyprflip={duration_ms=0,notifications=false}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={WS}}})')
    home = root / 'chill-home'; (home / '.local/state').mkdir(parents=True, exist_ok=True)
    engine = root / 'chill-card-engine.lua'
    engine.write_text(args.engine.read_text().replace('os.getenv("HOME")', json.dumps(str(home))))
    lua('CHILLMODE_OPTS={auto=false,notify=false,keybind="",key_hide="",key_restore="",hide=false}; '
        f'dofile({json.dumps(str(engine))})')

    a, b, c = [spawn(name) for name in ('front', 'back', 'notes')]
    ipc.focused((a, 'mark'), (b, 'card'))
    ipc.focused((c, 'mark'), (b, 'attach horizontal'))
    neighbor = spawn('neighbor')
    assert card()['faces'] == [[a], [b, c]] and card()['native_group']
    tile = tuple(card()['box'])
    assert not protect() and lua(f'return hl.plugin.hyprflip.protects_workspace({WS})') == 'true'
    passed('a workspace with only native cards is open to Chill; older engines still see it protected')

    lua(f'chillmode.toggle({WS})')
    wait(lambda: card()['floating'] and ipc.windows()[neighbor]['floating'])
    chilled_box = tuple(card()['box'])
    # Omachill pulls each tile in by 10% of its own size on every side.
    expected = (tile[0] + tile[2] * .1, tile[1] + tile[3] * .1, tile[2] * .8, tile[3] * .8)
    assert all(abs(p - q) <= 3 for p, q in zip(chilled_box, expected)), (chilled_box, expected)
    assert all(tagged(x) for x in members()) and tagged(neighbor)
    back = visible_boxes()
    assert len(back) == 2 and all(inside(x, chilled_box) for x in back), (back, chilled_box)
    passed('Chill floats the card in place as one window, tagged on every app of both faces')

    ipc.focus(b); ipc.action('flip')
    assert card()['active'] == 0 and tuple(card()['box']) == chilled_box
    front = visible_boxes()
    assert len(front) == 1 and inside(front[0], chilled_box)
    ipc.action('flip')
    assert card()['active'] == 1 and tuple(card()['box']) == chilled_box and visible_boxes() == back
    passed('both faces share the chilled frame; flipping keeps its size and place')

    ipc.action('unfold'); assert card()['unfolded'] and card()['floating']
    assert len(visible_boxes()) == 3
    ipc.action('unfold'); assert not card()['unfolded']
    passed('a chilled card unfolds and folds as a floating card')

    lua(f'chillmode.toggle({WS})')
    wait(lambda: not card()['floating'] and not ipc.windows()[neighbor]['floating'])
    assert not any(tagged(x) for x in members() + [neighbor])
    restored = tuple(card()['box'])
    assert all(abs(p - q) <= 4 for p, q in zip(restored, tile)), (restored, tile)
    assert card()['faces'] == [[a], [b, c]]
    passed('leaving Chill tiles the card back into its slot as one tile')

    ipc.focus(b); ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    assert protect()
    lua(f'chillmode.toggle({WS})')
    time.sleep(.2)
    assert not card()['floating'] and card()['fullscreen']
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    assert not protect()
    passed('a fullscreen card keeps its workspace out of Chill until it leaves fullscreen')

    extra = spawn('extra')
    lua(f'chillmode.toggle({WS})')
    wait(lambda: card()['floating'] and ipc.windows()[extra]['floating'])
    ipc.action(f'mark {extra}'); ipc.focused((b, 'attach horizontal'))
    assert card()['faces'][1] == [b, c, extra] and card()['floating']
    wait(lambda: tagged(extra) or True)
    ipc.focus(extra); ipc.action('release')
    assert card()['faces'][1] == [b, c] and card()['floating']
    lua(f'chillmode.toggle({WS})')
    wait(lambda: not card()['floating'])
    passed('chilled apps join and leave a chilled card while it stays chilled')

    ipc.call('plugin', 'unload', str(library)); loaded = False
    for x in (a, b, c):
        assert not ipc.windows()[x]['grouped']
    passed('unloading releases the apps of a card that was chilled')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    try: lua('if chillmode and chillmode.unload then chillmode.unload() end')
    except Exception: pass
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    (root / 'chill-card-results.json').write_text(json.dumps(checks, indent=2))
