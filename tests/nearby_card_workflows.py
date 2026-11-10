#!/usr/bin/env python3
"""Card keys from a window in no card: with plugin:hyprflip:nearby_card (on by default) flip, face, unfold and
fullscreen act on the one card shown on the focused window's workspace, and the focus stays where it is. Off, or
with two cards there, they act on nothing. Only the Hyprflip core is loaded. Start the session with --notify-recorder."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
args = parser.parse_args()
root = args.session.parent
env = environment(args.session)
if 'notify_log' not in env:
    raise SystemExit('Start the nested session with --notify-recorder')
env.pop('notify_log')
ipc = w.Hyprctl(env)
library = root / 'nearby-hyprflip.so'
processes, checks, loaded = [], [], None
PLACE = '30'


def wait(fn, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.02)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name, color):
    app = 'hyprflip-nearby-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                                       '--override', f'colors-dark.background={color}', 'sh', '-c', 'exec cat'],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def active(): return ipc.data('-j', 'activewindow').get('address')
def card(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)
def settle(): wait(lambda: not ipc.status()['animating'])


def focus(address):
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: active() == address)


def build_card(front, back):
    focus(front); ipc.action('mark'); focus(back); ipc.action('card')
    settle()
    return next(c['id'] for c in ipc.status()['containers'] if any(back in face for face in c['faces']))


def act(action):
    return subprocess.run(['hyprctl', 'hyprflip', *action.split()], env=env, capture_output=True, text=True, timeout=8).stdout.strip()


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = library
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=0}}})')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={PLACE}}})')
    assert ipc.status()['nearby_card'] is True, 'nearby_card is on by default'
    passed('status says "nearby_card":true by default')

    herdr = spawn('herdr', '203040')
    front = spawn('front', '0a6f8f')
    back = spawn('back', 'c2601a')
    one = build_card(front, back)
    focus(herdr)
    assert card(one)['active'] == 0

    assert act('flip').startswith('ok'), act('flip')
    settle()
    assert card(one)['active'] == 1 and active() == herdr
    act('flip'); settle()
    assert card(one)['active'] == 0 and active() == herdr
    passed('flip from the window beside the card turns that card, and the focus stays beside it')

    assert act('face 2').startswith('ok'); settle()
    assert card(one)['active'] == 1 and active() == herdr
    act('face 1'); settle()
    passed('face <n> from beside the card shows that face of it')

    assert act('unfold').startswith('ok'); settle()
    assert card(one)['unfolded'] is True and active() == herdr
    act('unfold'); settle()
    assert card(one)['unfolded'] is False
    passed('unfold from beside the card unfolds and folds it')

    ipc.call('eval', 'hl.config({plugin={hyprflip={nearby_card=false}}})')
    assert ipc.status()['nearby_card'] is False
    act('flip'); time.sleep(.3)
    assert card(one)['active'] == 0 and active() == herdr
    focus(front); act('flip'); settle()
    assert card(one)['active'] == 1, 'inside the card the key works whatever the setting'
    act('flip'); settle()
    ipc.call('eval', 'hl.config({plugin={hyprflip={nearby_card=true}}})')
    passed('turned off, flip from beside the card does nothing, and inside the card it still turns')

    focus(herdr)
    other_front = spawn('other-front', '00aa00')
    other_back = spawn('other-back', 'aa00aa')
    two = build_card(other_front, other_back)
    focus(herdr)
    before = card(one)['active'], card(two)['active']
    act('flip'); time.sleep(.3)
    assert (card(one)['active'], card(two)['active']) == before and active() == herdr
    passed('with two cards on the workspace, flip from beside them turns neither')
    print(len(checks), 'checks passed')
finally:
    for process in processes: process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(loaded))
        except Exception: pass
