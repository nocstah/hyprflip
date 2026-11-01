#!/usr/bin/env python3
"""Cards addressed by id, as another program drives them: a quiet restore beside a
working tile, then turning, parking and bringing the card back without taking the
focus. Only the Hyprflip core is loaded (native dwindle cards)."""
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
args = parser.parse_args()
root = args.session.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library = root / 'card-id-hyprflip.so'
loaded, output = False, None


class Lister:
    """A menu that keeps what it was offered and chooses nothing."""
    def __init__(self): self.offered = []
    def choose(self, prompt, choices):
        self.offered = [c.value for c in choices]
        raise w.SetupError('listed')


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
    app = 'hyprflip-card-id-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
               'sh', '-c', 'printf "\\n  %s\\n" "$1"; exec cat', 'pane', name]
    processes.append(subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def active(): return ipc.data('-j', 'activewindow').get('address')
def workspace(): return ipc.data('-j', 'activeworkspace')['id']
def card(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)


def restore(front, back, quiet=True):
    box = ipc.windows()[front]
    reply = ipc.action(f'restore {"quiet " if quiet else ""}tiled 0 0 {box["at"][0]} {box["at"][1]} '
                       f'{box["size"][0]} {box["size"][1]} front horizontal {front} {front}:1 back horizontal {back} {back}:1')
    assert reply == 'ok: ok', reply
    return next(c for c in ipc.status()['containers'] if front in c['faces'][0])['id']


def visible(id):
    c, windows = card(id), ipc.windows()
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (c['unfolded'] or side == c['active']), (c, windows[address])


def apart(a, b):
    """Two [x, y, w, h] boxes that do not overlap."""
    return a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def refused(action):
    before = ipc.status()
    try:
        reply = ipc.action(action)
        raise AssertionError((action, reply))
    except w.SetupError as error:
        reply = str(error)
    after = ipc.status()
    assert after['containers'] == before['containers'] and after['pairs'] == before['pairs'], action
    return reply


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + f'''
hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})
hl.workspace_rule({{workspace="71",monitor="{output}"}})
hl.workspace_rule({{workspace="72",monitor="{output}"}})
hl.config({{general={{gaps_in=14,gaps_out=24}},decoration={{inactive_opacity=0.8}},animations={{enabled=false}},
    plugin={{hyprflip={{duration_ms=0,notifications=false}}}}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=71})')
    assert [p['name'] for p in ipc.data('-j', 'plugin', 'list')] == ['hyprflip']

    # The terminal someone types in, and the two apps a program puts beside it as one card.
    term = spawn('terminal')
    front, back = spawn('browser'), spawn('notes')
    ipc.focus(term)
    id = restore(front, back)
    made = card(id)
    assert made['faces'] == [[front], [back]] and made['active'] == 0, made
    assert made['native_group'] and not made['floating'], made
    assert made['workspace'] == {'id': 71, 'name': '71', 'special': False}, made
    assert active() == term and workspace() == 71
    visible(id)
    t = ipc.windows()[term]
    assert apart([*t['at'], *t['size']], made['box']), (t, made)
    passed('a quiet restore builds a tiled card beside a working tile and leaves the focus and the workspace alone')

    ipc.focused((front, 'unpair'))
    wait(lambda: not ipc.status()['containers'])
    ipc.focus(back)
    id = restore(front, back)
    assert card(id)['active'] == 0 and active() == front
    visible(id)
    passed('a quiet restore that takes in the focused app moves the focus to the shown side, never a hidden one')

    ipc.focus(term)
    ipc.action(f'card {id} show back')
    assert card(id)['active'] == 1 and active() == term
    visible(id)
    assert ipc.action(f'card {id} show back') == 'ok: ok' and card(id)['active'] == 1
    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=120}}})')
    ipc.action(f'card {id} flip')
    wait(lambda: not ipc.status()['animating'])
    assert ipc.status()['last_fallback'] == '', ipc.status()['last_fallback']
    assert card(id)['active'] == 0 and active() == term
    visible(id)
    # With the focus on the card, a turn by id carries it to the other side, as a keyboard flip does.
    ipc.focus(front)
    ipc.action(f'card {id} flip')
    wait(lambda: not ipc.status()['animating'])
    assert card(id)['active'] == 1 and active() == back
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0}}})')
    passed('show and flip by id turn a card without taking the focus, and carry it along when it was on the card')

    ipc.focus(term)
    ipc.action(f'card {id} workspace special:park silent')
    parked = card(id)
    assert parked['workspace']['special'] and parked['workspace']['name'] == 'special:park', parked
    members = [a for face in parked['faces'] for a in face]
    windows = ipc.windows()
    assert all(windows[a]['workspace']['name'] == 'special:park' for a in members), windows
    assert active() == term and workspace() == 71
    # Another open card, so Find has something to list: the parked card is not in it.
    chat, mail = spawn('chat'), spawn('mail')
    ipc.focused((chat, 'mark'), (mail, 'pair'))
    lister = Lister()
    try: w.Find(ipc, lister).prepare()
    except w.SetupError: pass
    assert lister.offered and not set(lister.offered) & set(members), lister.offered
    ipc.focus(term)
    ipc.action(f'card {id} workspace 71 silent')
    home = card(id)
    assert home['workspace'] == {'id': 71, 'name': '71', 'special': False}, home
    assert active() == term and workspace() == 71
    visible(id)
    passed('a card parks on a special workspace and comes back without taking the focus; parked, Find leaves it out')

    ipc.action(f'card {id} workspace 72')
    shown = card(id)
    assert workspace() == 72 and active() == shown['faces'][shown['active']][0], shown
    ipc.action(f'card {id} workspace name:parked silent')
    assert card(id)['workspace']['name'] == 'parked', card(id)
    ipc.call('dispatch', 'hl.dsp.focus({workspace=71})')
    ipc.focus(term)
    ipc.action(f'card {id} workspace 71 silent')
    assert card(id)['workspace']['id'] == 71 and active() == term
    visible(id)
    passed('a card follows to a numbered workspace when asked, and moves silently to a named one and back')

    for action in ('card 9999 flip', 'card 0 flip', 'card x flip', f'card {id}', f'card {id} show', f'card {id} show sideways',
                   f'card {id} flip now', f'card {id} workspace', f'card {id} workspace 0', f'card {id} workspace +1',
                   f'card {id} workspace previous', f'card {id} workspace special:bad/name', f'card {id} workspace 72 loud',
                   f'card {id} workspace 72 silent now', 'restore quiet', 'restore quiet sideways 0 0 0 0 1 1'):
        refused(action)
    pair = next(p for p in ipc.status()['pairs'] if p['front'] == chat)
    assert 'multi-app' in refused(f'card {pair["id"]} workspace 72')
    ipc.action(f'card {pair["id"]} show back')
    assert next(p for p in ipc.status()['pairs'] if p['id'] == pair['id'])['current'] == mail and active() == term
    passed('card actions refuse unknown ids and malformed input without changing any card; a pair turns by id but moves only as windows')

    assert not ipc.call('configerrors')
    released = [a for face in card(id)['faces'] for a in face]
    ipc.call('plugin', 'unload', str(library)); loaded = False
    windows = ipc.windows()
    for address in released:
        assert windows[address]['acceptsInput'] and not windows[address]['grouped'], windows[address]
    # A pair is a Hyprland group: unloading unlocks it and leaves it as it is.
    assert sorted(windows[chat]['grouped']) == sorted([chat, mail]), windows[chat]
    passed('unloading releases every app of the moved card; the pair stays an ordinary Hyprland group')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    if output: ipc.call('output', 'remove', output)
    (root / 'card-id-results.json').write_text(json.dumps(checks, indent=2))
