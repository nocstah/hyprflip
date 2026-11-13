#!/usr/bin/env python3
"""Card keys from a window in no card: with plugin:hyprflip:nearby_card (on by default) flip, face, unfold and
fullscreen act on the one card shown on the focused window's workspace, and the focus stays where it is. Off, or
with two cards there, they act on nothing. The move keys of examples/containers-navigation.lua and Super+J of
examples/containers-setup.lua stay the focused window's own there, as Hyprland's keys, and act on a card only from
inside it. Only the Hyprflip core is loaded. Start the session with --notify-recorder."""
import argparse
import json
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
notify_log = Path(env.pop('notify_log'))
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

    # The shipped move keys and Super+J, each run as its bound function. They are the
    # focused window's own: beside the card they do for that window what Hyprland does,
    # and only from inside the card do they act on the card.
    ipc.call('repl', '_G.nearby_keys = {}\n'
                     'package.preload["hypr.hyprflip-preferences"] = function() return true end')
    spy = ('local hl = setmetatable({bind = function(key, fn) _G.nearby_keys[key] = fn end,'
           ' unbind = function() end}, {__index=hl})\n')
    for module in ('containers-navigation.lua', 'containers-setup.lua'):
        ipc.call('repl', spy + (project / 'examples' / module).read_text())
    # As Omarchy sets it: without it dwindle redraws each split from the tile's shape, and togglesplit shows nothing.
    ipc.call('eval', 'hl.config({dwindle={preserve_split=true}})')

    def key(name):
        ipc.call('repl', '_G.nearby_keys[' + json.dumps(name) + ']()')
        time.sleep(.3)

    def client(address): return ipc.windows()[address]
    def on(workspace, *windows): return all(client(x)['workspace']['id'] == workspace for x in windows)
    def refusals():
        # The card actions' own refusals; Hyprflip's other notices name neither phrase.
        return [line for line in notify_log.read_text().splitlines() if 'as a unit' in line or 'Hyprflip container' in line]

    faces = card(one)['faces']
    focus(herdr)
    herdr_x, card_x = client(herdr)['at'][0], card(one)['box'][0]
    assert herdr_x != card_x, 'the window and the card stand side by side'
    # Toward the card. Hyprland swaps no window with a card's locked group, so the
    # window stays; what matters is that the key no longer asks the card to move.
    key('SUPER + SHIFT + ' + ('RIGHT' if herdr_x < card_x else 'LEFT')); settle()
    assert not refusals(), refusals()
    assert card(one)['faces'] == faces and on(int(PLACE), herdr, front, back) and active() == herdr
    passed('Super+Shift+arrow from beside the card stays that window\'s key: the card is not asked to move')

    key('SUPER + SHIFT + ALT + code:12')
    wait(lambda: on(3, herdr))
    assert on(int(PLACE), front, back) and card(one)['faces'] == faces
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{herdr}",workspace="{PLACE}",follow=false}})')
    wait(lambda: on(int(PLACE), herdr)); settle()
    passed('Super+Shift+Alt+3 from beside the card moves that window alone, and the card stays')

    companion = spawn('companion', '777700')
    focus(companion); ipc.action('mark'); focus(front); ipc.action('attach horizontal'); settle()
    faces = card(one)['faces']
    assert len(faces[card(one)['active']]) == 2, faces
    focus(herdr)
    size = client(herdr)['size']
    key('SUPER + J')
    wait(lambda: client(herdr)['size'] != size); settle()
    assert card(one)['faces'] == faces and active() == herdr
    passed('Super+J from beside a card with a two-app face turns that window\'s split, not the face')

    focus(front)
    def stacked(): return client(front)['at'][0] == client(companion)['at'][0]
    was = stacked()
    key('SUPER + J')
    wait(lambda: stacked() != was); settle()
    assert card(one)['faces'] == faces
    passed('Super+J inside the card still turns its face between beside and stacked')
    focus(herdr)

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
