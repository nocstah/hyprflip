#!/usr/bin/env python3
"""Multi-app cards on unmodified dwindle, with only the Hyprflip core loaded."""
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
args = parser.parse_args()
root = args.session.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library = root / 'dwindle-hyprflip.so'
loaded, output = False, None


class Menu:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        assert answer in [choice.value for choice in choices], (prompt, answer, choices)
        return answer


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name, minimum=None):
    app = 'hyprflip-dwindle-' + name
    color = '173746' if name == 'front' else '482d48' if name == 'back' else '4b352b'
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
               '--override', 'colors-dark.background=' + color,
               'sh', '-c', 'printf "\\n  %s\\n\\n  Dwindle card — live pane\\n" "$1"; exec cat', 'pane', name]
    if minimum:
        control = root / (app + '.control')
        control.write_text('minimum %d %d' % minimum)
        command = ['python3', str(project / 'tests/gtk_fixture.py'), app, str(control)]
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def card():
    cards = ipc.status()['containers']
    assert len(cards) == 1, cards
    return cards[0]


def visible():
    c, windows = card(), ipc.windows()
    assert c['native_group']
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (c['unfolded'] or side == c['active']), (c, windows[address])
        for a, b in zip(face, face[1:]):
            a, b = windows[a], windows[b]
            assert a['at'][0] + a['size'][0] <= b['at'][0] or a['at'][1] + a['size'][1] <= b['at'][1], (a, b)


def geometry(address):
    win = ipc.windows()[address]
    return win['at'], win['size']


def capture(name):
    subprocess.run(['grim', '-o', output, str(root / (name + '.png'))], env=env, check=True, timeout=10)


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
hl.config({{general={{gaps_in=14,gaps_out=24}},animations={{enabled=false}},
    plugin={{hyprflip={{duration_ms=0,notifications=false}}}}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=71})')
    assert ipc.status()['native_cards'] and not ipc.status()['hy3_provider']
    assert [p['name'] for p in ipc.data('-j', 'plugin', 'list')] == ['hyprflip']
    front, back = [spawn('minimum-' + name) for name in ('front', 'back')]
    ipc.focused((front, 'mark'), (back, 'card'))
    wide = spawn('minimum-wide', (850, 200))
    # Before grouping, the incoming tile takes half of the workspace. Its
    # minimum cannot fit half of the card's current width, but it can fit
    # after dwindle removes that tile and gives the space back to the card.
    assert card()['box'][2] / 2 < 850
    ipc.focused((wide, 'mark'), (back, 'attach horizontal'))
    assert card()['faces'] == [[front], [back, wide]]
    assert ipc.windows()[wide]['size'][0] >= 850
    visible()
    ipc.action('unpair')
    for address in (front, back, wide):
        ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda: not any(a in ipc.windows() for a in (front, back, wide)))
    passed('tiled attachment checks app minimum sizes after the incoming tile releases its space')

    a, b, c = [spawn(name) for name in ('front', 'back', 'notes')]
    ipc.focus(a)
    setup = w.Setup(ipc, Menu(b, c, 'create'))
    setup.apply(setup.prepare(a))
    assert card()['faces'] == [[a], [b, c]] and not card()['floating']; visible()
    neighbor = spawn('neighbor')
    neighbor_box = geometry(neighbor)
    ipc.focus(b)
    ipc.action('layout horizontal')
    windows = ipc.windows()
    assert windows[c]['at'][0] - windows[b]['at'][0] - windows[b]['size'][0] - 4 == 28, windows
    capture('dwindle-back')
    passed('guided creation uses one native dwindle tile; panes retain desktop gaps beside a neighbor')

    for mode in w.TRANSITIONS:
        ipc.call('eval', f'hl.config({{animations={{enabled=true}},plugin={{hyprflip={{duration_ms=120,transition="{mode}"}}}}}})')
        source = card()['active']; ipc.action('flip'); wait(lambda: not ipc.status()['animating'])
        assert card()['active'] == 1 - source; visible()
        assert geometry(neighbor) == neighbor_box
    ipc.action('peek'); wait(lambda: not ipc.status()['animating'])
    ipc.action('peek end'); wait(lambda: not ipc.status()['animating']); visible()
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0}}})')
    ipc.focus(a); ipc.action('unfold'); visible(); capture('dwindle-unfolded')
    assert card()['unfolded'] and geometry(neighbor) == neighbor_box
    ipc.action('unfold')
    passed('all transitions, peek and unfold preserve the neighboring tile and exclusive face input')

    for side, anchor in enumerate((a, b)):
        ipc.focus(anchor)
        if len(card()['faces'][side]) > 1: ipc.action('layout vertical')
        while len(card()['faces'][side]) < 5:
            extra = spawn(f'face-{side}-pane-{len(card()["faces"][side])}')
            ipc.focused((extra, 'mark'), (anchor, 'attach vertical'))
            visible()
    assert list(map(len, card()['faces'])) == [5, 5]
    extra = spawn('overflow')
    before = deepcopy(card())
    try:
        ipc.focused((extra, 'mark'), (b, 'attach vertical'))
        raise AssertionError('Sixth pane was accepted')
    except w.SetupError:
        assert card()['faces'] == before['faces']
        assert not ipc.windows()[extra]['grouped']
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{extra}"}})')
    passed('both faces accept five panes and refuse a sixth without altering membership')

    ipc.focus(b)
    flow = w.Edit(ipc, Menu('layout', 'layout balance'))
    flow.apply(flow.prepare(b)); visible()
    ipc.action('workspace 72'); visible()
    assert all(ipc.windows()[x]['workspace']['id'] == 72 for face in card()['faces'] for x in face)
    ipc.action('floating'); assert card()['floating']; visible()
    ipc.action('floating'); assert not card()['floating']; visible()
    ipc.call('reload'); visible()
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})'); visible()
    passed('editing, whole-card workspace moves, floating, reload and fullscreen retain all ten panes')

    for face in card()['faces']:
        w.Setup(ipc, Menu()).restore_ratios({'windows': face, 'axis': 'vertical',
                                           'ratios': [.3, .25, .2, .15, .1]})
    recipe = w.Saved.capture(card(), ipc.windows())
    recipe['workspace'] = 72
    store = w.RecipeStore(env)
    store.update('Dwindle', recipe, store.read().get('Dwindle'))
    members = [x for face in card()['faces'] for x in face]
    ipc.action('unpair')
    flow = w.Saved(ipc, Menu())
    plan = flow.prepare_named('Dwindle', recipe, 72, ipc.data('-j', 'activewindow').get('address'))
    flow.apply(plan); visible()
    assert [x for face in card()['faces'] for x in face] == members
    assert not card()['floating']
    for layout in card()['layouts']:
        assert all(abs(actual - expected) < .003 for actual, expected in
                   zip(layout['ratios'], [.3, .25, .2, .15, .1]))
    passed('saved ten-app cards reopen on dwindle with the same apps and unequal pane proportions')

    closing_side = 1 - card()['active']
    closing = card()['faces'][closing_side][-1]
    assert not ipc.windows()[closing]['acceptsInput']
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{closing}"}})')
    wait(lambda: closing not in ipc.windows()); visible()
    assert len(card()['faces'][closing_side]) == 4 and len(card()['faces'][1 - closing_side]) == 5
    remaining = [x for face in card()['faces'] for x in face]
    assert not ipc.call('configerrors')
    ipc.call('plugin', 'unload', str(library)); loaded = False
    for address in remaining:
        window = ipc.windows()[address]
        assert window['acceptsInput'] and not window['grouped']
    passed('closing a hidden pane repairs its face; unloading releases every remaining app')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    if output: ipc.call('output', 'remove', output)
    (root / 'dwindle-results.json').write_text(json.dumps(checks, indent=2))
