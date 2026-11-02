#!/usr/bin/env python3
"""Cards addressed by id, as another program drives them: a quiet restore beside a
working tile, then turning, parking, swapping and ungrouping cards without taking the
focus or moving the pointer. Only the Hyprflip core is loaded (native dwindle cards)."""
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


def tiles(number=None):
    """[x, y, w, h] of every window, or of the windows on one numbered workspace."""
    return {a: [*win['at'], *win['size']] for a, win in ipc.windows().items()
            if number is None or win['workspace']['id'] == number}


def tile(address): return tiles()[address]


def pointer():
    at = ipc.data('-j', 'cursorpos')
    return at['x'], at['y']


def rest(over):
    """Leaves the pointer off-centre over a tile, where a warp to any window's centre shows."""
    x, y, width, height = tile(over)
    point = x + width // 4, y + height // 3
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={point[0]},y={point[1]}}})')
    assert pointer() == point, (over, point, pointer())
    return point


def still(action, over, settle=lambda: time.sleep(.1)):
    """An action by id, sent while the pointer rests over a tile: the pointer stays there."""
    before = rest(over)
    reply = ipc.action(action)
    during = pointer()
    settle()
    after = pointer()
    print('pointer', before, during, after, action.split(' front ')[0], flush=True)
    assert before == during == after, (action, before, during, after)
    return reply


def batch(over, *commands):
    """Commands in one hyprctl batch, as card mode swaps cards, sent while the pointer rests over a tile."""
    before = rest(over)
    result = subprocess.run(['hyprctl', '--batch', ' ; '.join(commands)], env=env, capture_output=True,
                            text=True, timeout=8)
    time.sleep(.1)
    after = pointer()
    print('pointer', before, after, 'batch of', len(commands), flush=True)
    assert not result.returncode and before == after, (result.returncode, before, after)
    return [reply.strip() for reply in result.stdout.strip().split('\n\n\n')]


def direction(of, beside):
    """The side of the tile `beside` that the box `of` lies on, as dwindle's preselect names it."""
    if of[0] >= beside[0] + beside[2]: return 'r'
    if of[0] + of[2] <= beside[0]: return 'l'
    return 'd' if of[1] >= beside[1] + beside[3] else 'u'


def restore(front, back, over):
    box = ipc.windows()[front]
    reply = still(f'restore quiet tiled 0 0 {box["at"][0]} {box["at"][1]} {box["size"][0]} {box["size"][1]} '
                  f'front horizontal {front} {front}:1 back horizontal {back} {back}:1', over)
    assert reply == 'ok: ok', reply
    return next(c for c in ipc.status()['containers'] if front in c['faces'][0])['id']


def visible(id):
    c, windows = card(id), ipc.windows()
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (c['unfolded'] or side == c['active']), (c, windows[address])


def loose(addresses, place):
    """Windows out of any card or group, taking input, on the workspace named `place`."""
    windows = ipc.windows()
    for address in addresses:
        win = windows[address]
        assert not win['grouped'] and win['acceptsInput'] and win['workspace']['name'] == place, win


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
    session_windows(env)
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + f'''
hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})
hl.workspace_rule({{workspace="71",monitor="{output}"}})
hl.workspace_rule({{workspace="72",monitor="{output}"}})
hl.workspace_rule({{workspace="73",monitor="{output}"}})
hl.config({{general={{gaps_in=14,gaps_out=24}},decoration={{inactive_opacity=0.8}},animations={{enabled=false}},
    plugin={{hyprflip={{duration_ms=0,notifications=false}}}}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=71})')
    assert [p['name'] for p in ipc.data('-j', 'plugin', 'list')] == ['hyprflip']
    assert ipc.status()['card_ungroup'] is True

    # The terminal someone types in, and the two apps a program puts beside it as one card.
    # Each action by id below is sent while the pointer rests off-centre over a tile, and
    # must leave it there.
    term = spawn('terminal')
    front, back = spawn('browser'), spawn('notes')
    ipc.focus(term)
    # Positive control: here a focus dispatch warps the pointer to the window's centre, even
    # onto the window that already has the focus, so a pointer left resting below means
    # that nothing warped it.
    rest(term)
    assert active() == term
    ipc.focus(term)
    x, y, width, height = tile(term)
    centre = pointer()
    assert abs(centre[0] - (x + width / 2)) <= 1 and abs(centre[1] - (y + height / 2)) <= 1, (centre, tile(term))
    rest(term)
    passed('a focus dispatch warps the pointer to the centre of the window it focuses, even one already focused')
    id = restore(front, back, term)
    made = card(id)
    assert made['faces'] == [[front], [back]] and made['active'] == 0, made
    assert made['native_group'] and not made['floating'], made
    assert made['workspace'] == {'id': 71, 'name': '71', 'special': False}, made
    assert active() == term and workspace() == 71
    visible(id)
    t = ipc.windows()[term]
    assert apart([*t['at'], *t['size']], made['box']), (t, made)
    passed('a quiet restore builds a tiled card beside a working tile and leaves the focus, the workspace and the pointer alone')

    ipc.focused((front, 'unpair'))
    wait(lambda: not ipc.status()['containers'])
    ipc.focus(back)
    id = restore(front, back, term)
    assert card(id)['active'] == 0 and active() == front
    visible(id)
    passed('a quiet restore that takes in the focused app moves the focus to the shown side, never a hidden one, and never the pointer')

    ipc.focus(term)
    still(f'card {id} show back', term)
    assert card(id)['active'] == 1 and active() == term
    visible(id)
    assert still(f'card {id} show back', term) == 'ok: ok' and card(id)['active'] == 1
    assert still(f'card {id} show front', term) == 'ok: ok' and card(id)['active'] == 0 and active() == term
    still(f'card {id} show back', term)
    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=120}}})')
    turned = lambda: wait(lambda: not ipc.status()['animating'])
    still(f'card {id} flip', term, turned)
    assert ipc.status()['last_fallback'] == '', ipc.status()['last_fallback']
    assert card(id)['active'] == 0 and active() == term
    visible(id)
    # With the focus on the card, a turn by id carries it to the other side, as a keyboard flip does.
    ipc.focus(front)
    still(f'card {id} flip', term, turned)
    assert card(id)['active'] == 1 and active() == back
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0}}})')
    passed('show and flip by id turn a card without taking the focus or moving the pointer, and carry the focus along when it was on the card')

    ipc.focus(term)
    still(f'card {id} workspace special:park silent', term)
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
    still(f'card {id} workspace 71 silent', term)
    home = card(id)
    assert home['workspace'] == {'id': 71, 'name': '71', 'special': False}, home
    assert active() == term and workspace() == 71
    visible(id)
    passed('a card parks on a special workspace and comes back without taking the focus or moving the pointer; parked, Find leaves it out')

    ipc.action(f'card {id} workspace 72')
    shown = card(id)
    assert workspace() == 72 and active() == shown['faces'][shown['active']][0], shown
    # Alone on this workspace, the card leaves from under the resting pointer.
    still(f'card {id} workspace name:parked silent', shown['faces'][shown['active']][0])
    assert card(id)['workspace']['name'] == 'parked', card(id)
    ipc.call('dispatch', 'hl.dsp.focus({workspace=71})')
    ipc.focus(term)
    still(f'card {id} workspace 71 silent', term)
    assert card(id)['workspace']['id'] == 71 and active() == term
    visible(id)
    passed('a card follows to a numbered workspace when asked, and moves silently to a named one and back without moving the pointer')

    for action in ('card 9999 flip', 'card 0 flip', 'card x flip', f'card {id}', f'card {id} show', f'card {id} show sideways',
                   f'card {id} flip now', f'card {id} workspace', f'card {id} workspace 0', f'card {id} workspace +1',
                   f'card {id} workspace previous', f'card {id} workspace special:bad/name', f'card {id} workspace 72 loud',
                   f'card {id} workspace 72 silent now', 'card 9999 ungroup', f'card {id} ungroup now', 'restore quiet',
                   'restore quiet sideways 0 0 0 0 1 1'):
        refused(action)
    assert 'card <id> ungroup' in refused(f'card {id}') and '|ungroup|' in refused('ungroup')
    pair = next(p for p in ipc.status()['pairs'] if p['front'] == chat)
    assert 'multi-app' in refused(f'card {pair["id"]} workspace 72')
    ipc.action(f'card {pair["id"]} show back')
    assert next(p for p in ipc.status()['pairs'] if p['id'] == pair['id'])['current'] == mail and active() == term
    passed('card actions refuse unknown ids and malformed input without changing any card; a pair turns by id but moves only as windows')

    assert still(f'card {pair["id"]} ungroup', term) == 'ok: ok'
    assert not any(p['id'] == pair['id'] for p in ipc.status()['pairs'])
    loose((chat, mail), '71')
    assert active() == term and workspace() == 71
    # Paired again for the unload check at the end.
    ipc.focused((chat, 'mark'), (mail, 'pair'))
    ipc.focus(term)
    passed('ungroup by id leaves a pair as two loose windows, with the focus and the pointer where they were')

    # Card mode swaps cards beside the tile someone works in: one batch parks the
    # leaving card, preselects its side of that tile and brings the next card in.
    ipc.call('dispatch', 'hl.dsp.focus({workspace=73})')
    herdr = spawn('herdr')
    a1, a2, b1, b2 = [spawn(name) for name in ('browser-a', 'notes-a', 'browser-b', 'notes-b')]
    ipc.focus(herdr)
    first, second = restore(a1, a2, herdr), restore(b1, b2, herdr)
    for parking in (first, second):
        still(f'card {parking} workspace special:park silent', herdr)
    # Away from the resting pointer, so the swap keeps the tile only if its preselect holds.
    ipc.call('dispatch', 'hl.dsp.layout("preselect r")')
    still(f'card {first} workspace 73 silent', herdr)
    leaving, neighbour = card(first)['box'], tile(herdr)
    assert direction(leaving, neighbour) == 'r' and active() == herdr, (leaving, neighbour)
    replies = batch(herdr, f'hyprflip card {first} workspace special:park silent',
                    f'dispatch hl.dsp.layout("preselect {direction(leaving, neighbour)}")',
                    f'hyprflip card {second} workspace 73 silent')
    assert replies == ['ok: ok', 'ok', 'ok: ok'], replies
    assert tile(herdr) == neighbour and card(second)['box'] == leaving, (tile(herdr), neighbour, card(second), leaving)
    assert card(first)['workspace']['name'] == 'special:park' and card(second)['workspace']['id'] == 73
    assert active() == herdr and workspace() == 73
    visible(second)
    passed('one batch swaps two cards beside a working tile: every move replies ok, and the tile, the focus and the pointer stay')

    before = tiles(73)
    replies = batch(herdr, 'dispatch hl.dsp.layout("preselect r")', 'hyprflip card 9999 workspace 73 silent')
    assert replies[0] == 'ok' and replies[1].startswith('error: No card has id 9999'), replies
    ipc.call('dispatch', 'hl.dsp.layout("preselect x")')
    assert tiles(73) == before and active() == herdr, (tiles(73), before)
    # A preselect left behind would put the next tile to the right of the working tile;
    # cleared, it opens on the pointer's half of it.
    rest(herdr)
    probe = spawn('probe')
    assert tile(probe)[:2] == neighbour[:2], (tile(probe), neighbour)
    processes[-1].terminate()
    wait(lambda: probe not in ipc.windows())
    assert tiles(73) == before, (tiles(73), before)
    passed('a refused unpark in a batch, followed by preselect x, leaves the layout as it was')

    ipc.focused((b1, 'fullscreen'))
    wait(lambda: card(second)['fullscreen'])
    assert 'Leave fullscreen' in refused(f'card {second} ungroup')
    ipc.focused((b1, 'fullscreen'))
    wait(lambda: not card(second)['fullscreen'])
    ipc.focus(herdr)
    assert still(f'card {second} ungroup', herdr) == 'ok: ok'
    assert not any(c['id'] == second for c in ipc.status()['containers'])
    loose((b1, b2), '73')
    assert active() == herdr and workspace() == 73
    passed('ungroup by id refuses a fullscreen card, and out of fullscreen leaves its apps as loose tiles '
           'with the focus and the pointer where they were')

    assert still(f'card {first} ungroup', herdr) == 'ok: ok'
    assert not any(c['id'] == first for c in ipc.status()['containers'])
    loose((a1, a2), 'special:park')
    assert active() == herdr and workspace() == 73
    passed('ungroup by id leaves the apps of a parked card loose on its special workspace, and the focus and the pointer stay')

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
