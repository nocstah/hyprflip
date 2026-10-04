#!/usr/bin/env python3
"""Whole-card fullscreen for native dwindle and floating cards."""
import argparse
import json
import shlex
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
parser.add_argument('--protocol', type=Path, help='wlr-virtual-pointer-unstable-v1.xml for real pointer checks')
args = parser.parse_args()
root = args.session.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library = root / 'fullscreen-hyprflip.so'
loaded, output, pointer = False, None, None
FULL = 'hl.dsp.window.fullscreen({mode="fullscreen"})'
MAXIMIZE = 'hl.dsp.window.fullscreen({mode="maximized"})'


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
    app = 'hyprflip-fullscreen-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
               'sh', '-c', 'printf "\\n  %s\\n" "$1"; exec cat', 'pane', name]
    processes.append(subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def card():
    cards = ipc.status()['containers']
    assert len(cards) == 1, cards
    return cards[0]


def monitor():
    m = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    return m['x'], m['y'], round(m['width'] / m['scale']), round(m['height'] / m['scale'])


def point(target):
    """Move the real (virtual) pointer to the middle of a pane."""
    x, y, width, height = box(target)
    for _ in range(3):
        pos = ipc.data('-j', 'cursorpos')
        pointer.stdin.write(f'move {x + width / 2 - pos["x"]} {y + height / 2 - pos["y"]}\n'); pointer.stdin.flush()
        assert pointer.stdout.readline().strip() == 'ok'
        time.sleep(.05)
    wait(lambda: ipc.data('-j', 'activewindow')['address'] == target)


def box(address):
    win = ipc.windows()[address]
    return (*win['at'], *win['size'])


def inside(inner, outer):
    return (inner[0] >= outer[0] and inner[1] >= outer[1] and
            inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3])


def fills(area, strict=True):
    """The visible face (or both, unfolded) tiles the area; hidden panes take no input."""
    c, windows = card(), ipc.windows()
    shown = [x for side, face in enumerate(c['faces']) for x in face if c['unfolded'] or side == c['active']]
    hidden = [x for face in c['faces'] for x in face if x not in shown]
    assert any(windows[x]['fullscreen'] for x in shown), [windows[x] for x in shown]
    assert not any(windows[x]['fullscreen'] for x in hidden)
    focused = ipc.data('-j', 'activewindow')['address']
    assert focused in shown and windows[focused]['fullscreen'], (focused, shown)
    for x in shown:
        assert windows[x]['acceptsInput'], windows[x]
        assert inside(box(x), area), (box(x), area)
    for x in hidden:
        assert not windows[x]['acceptsInput'], windows[x]
    if strict:
        # Panes reach every edge of the fullscreen area (within a border).
        boxes = [box(x) for x in shown]
        assert min(b[0] for b in boxes) - area[0] <= 3 and min(b[1] for b in boxes) - area[1] <= 3, (boxes, area)
        assert area[0] + area[2] - max(b[0] + b[2] for b in boxes) <= 3, (boxes, area)
        assert area[1] + area[3] - max(b[1] + b[3] for b in boxes) <= 3, (boxes, area)
    return [box(x) for x in shown]


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    # A headless output keeps the geometry independent of the desktop that
    # hosts the nested session (see TESTING.md for NVIDIA desktops).
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + f'''
hl.monitor({{output="{output}",mode="1280x800@60",position="2000x0",scale=1}})
hl.workspace_rule({{workspace="81",monitor="{output}"}})
hl.config({{general={{gaps_in=14,gaps_out=24}},animations={{enabled=false}},
    plugin={{hyprflip={{duration_ms=0,notifications=false}}}}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=81})')
    assert ipc.status()['fullscreen_focus'], 'focus hook not installed'

    a, b, c = [spawn(name) for name in ('front', 'back', 'notes')]
    ipc.focused((a, 'mark'), (b, 'card'))
    ipc.focused((c, 'mark'), (b, 'attach horizontal'))
    assert card()['faces'] == [[a], [b, c]] and card()['native_group']
    neighbor = spawn('neighbor')
    tile = tuple(card()['box'])
    before = {x: box(x) for x in (a, b, c, neighbor)}
    screen = monitor()

    ipc.focus(b); ipc.call('dispatch', FULL)
    back = fills(screen)
    assert not ipc.windows()[neighbor]['acceptsInput']
    # Panes meet at one 2px accent divider: no borders, no gap.
    assert back[1][0] - (back[0][0] + back[0][2]) == 2, back
    ipc.call('eval', 'hl.config({plugin={hyprflip={accent_color="#FF0000"}}})')
    dividers = ipc.status()['card_dividers']
    assert len(dividers) == 1 and dividers[0]['color'] == '#FF0000', dividers
    assert dividers[0]['box'] == [back[0][0] + back[0][2], screen[1], 2, screen[3]], (dividers, back)
    passed('fullscreen fills the monitor with every app on the visible face')

    for policy in (2, 1, 0):  # exit_fullscreen, take_over, ignore
        ipc.call('eval', f'hl.config({{misc={{on_focus_under_fullscreen={policy}}}}})')
        for target in (c, b):
            ipc.focus(target)
            now = fills(screen); assert now == back, (policy, target, now, back)
    passed('focus moves between panes of a fullscreen card under every focus-under-fullscreen policy')

    if args.protocol:
        ipc.call('eval', 'hl.config({misc={on_focus_under_fullscreen=2},input={follow_mouse=1}})')
        for kind, filename in (('client-header', 'frame-pointer-protocol.h'), ('private-code', 'frame-pointer-protocol.c')):
            subprocess.run(['wayland-scanner', kind, str(args.protocol), str(root / filename)], check=True)
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True))
        subprocess.run(['cc', '-o', str(root / 'fullscreen-pointer'), '-I' + str(root),
                        str(project / 'tests/frame_pointer.c'), str(root / 'frame-pointer-protocol.c'), *flags], check=True)
        pointer = subprocess.Popen([str(root / 'fullscreen-pointer'), '--stream'], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert pointer.stdout.readline().strip() == 'ready'
        for target in (c, b, c, b):
            point(target)
            # Fullscreen follows the pointer, so the toggle acts on the card.
            assert fills(screen) == back and ipc.windows()[target]['fullscreen']
        passed('the pointer reaches every pane of a fullscreen card')

    ipc.action('flip')
    assert card()['active'] == 0 and ipc.data('-j', 'activewindow')['address'] == a
    front = fills(screen)
    assert len(front) == 1 and front[0][2] >= screen[2] - 4, front
    ipc.action('flip')
    assert fills(screen) == back
    passed('flipping a fullscreen card keeps it fullscreen and switches the whole face')

    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=120}}})')
    for mode in w.TRANSITIONS:
        ipc.call('eval', f'hl.config({{plugin={{hyprflip={{transition="{mode}"}}}}}})')
        source = card()['active']; ipc.action('flip'); wait(lambda: not ipc.status()['animating'])
        assert card()['active'] == 1 - source
        wait(lambda: not any(ipc.windows()[x]['fullscreen'] == 0 for x in [ipc.data('-j', 'activewindow')['address']]))
        time.sleep(.3); fills(screen)
    ipc.action('peek'); wait(lambda: not ipc.status()['animating'])
    peeking = card()['active']
    ipc.action('peek end'); wait(lambda: not ipc.status()['animating'])
    assert card()['active'] == 1 - peeking
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0}}})')
    time.sleep(.3); fills(screen)
    passed('all transitions and peek run while fullscreen')

    if card()['active'] != 1: ipc.action('flip')
    ipc.action('unfold'); assert card()['unfolded']
    assert len(fills(screen)) == 3 and len(ipc.status()['card_dividers']) == 2
    for target in (a, c, b) if pointer else ():
        point(target)
        assert len(fills(screen)) == 3
    ipc.action('layout vertical'); fills(screen)
    ipc.action('layout horizontal'); fills(screen)
    ipc.action('unfold'); assert not card()['unfolded']
    assert fills(screen) == back
    passed('unfolding and face layout changes work inside a fullscreen card')

    ipc.call('dispatch', FULL)
    assert not any(ipc.windows()[x]['fullscreen'] for x in (a, b, c))
    assert tuple(card()['box']) == tile
    assert all(box(x) == before[x] for x in (b, c, neighbor)), ({x: box(x) for x in (b, c, neighbor)}, before)
    assert not ipc.status()['card_dividers']
    passed('leaving fullscreen restores the card tile and its neighbor exactly')

    ipc.focus(c); ipc.call('dispatch', MAXIMIZE)
    work = tuple(card()['box'])
    assert work != tile and inside(work, screen), (work, screen)
    fills(work, strict=False)
    ipc.call('dispatch', MAXIMIZE)
    assert tuple(card()['box']) == tile
    passed('maximize fills the work area with the whole card')

    extra, spare = spawn('extra'), spawn('spare')
    ipc.focus(b); ipc.call('dispatch', FULL); back = fills(screen)
    # Marking by address does not focus the app, which would end fullscreen.
    ipc.action(f'mark {extra}'); ipc.focused((b, 'attach horizontal'))
    assert card()['faces'][1] == [b, c, extra] and card()['fullscreen'], card()
    assert len(fills(screen)) == 3 and len(ipc.status()['card_dividers']) == 2
    ipc.focus(b); ipc.action(f'replace {extra} {spare}')
    assert card()['faces'][1] == [b, c, spare] and card()['fullscreen']
    assert len(fills(screen)) == 3
    ipc.focus(spare); ipc.action('release')
    assert card()['faces'][1] == [b, c] and card()['fullscreen']
    assert fills(screen) == back
    passed('apps join, replace and leave a fullscreen card without leaving fullscreen')

    ipc.call('eval', 'hl.config({plugin={hyprflip={fullscreen_divider=0}}})'); ipc.action('finish')
    now = fills(screen)
    assert now[1][0] == now[0][0] + now[0][2] and not ipc.status()['card_dividers'], now
    ipc.call('eval', 'hl.config({plugin={hyprflip={fullscreen_divider=4,divider_color="#00FF00"}}})'); ipc.action('finish')
    now = fills(screen)
    divider = ipc.status()['card_dividers']
    assert now[1][0] - (now[0][0] + now[0][2]) == 4 and divider[0]['box'][2] == 4 and divider[0]['color'] == '#00FF00', (now, divider)
    ipc.call('eval', 'hl.config({plugin={hyprflip={fullscreen_divider=2,divider_color=""}}})'); ipc.action('finish')
    assert fills(screen) == back and ipc.status()['card_dividers'][0]['color'] == '#FF0000'
    passed('divider width and color follow their settings; zero lets apps touch')

    ipc.call('dispatch', FULL)
    for x in (extra, spare):
        ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{x}"}})')
    wait(lambda: not any(x in ipc.windows() for x in (extra, spare)))
    tile = tuple(card()['box'])
    ipc.focus(b); ipc.action('fullscreen')
    assert ipc.windows()[b]['fullscreen'] == 2 and ipc.windows()[b]['fullscreenClient'] == 0, ipc.windows()[b]
    assert fills(screen) == back
    ipc.action('flip'); fills(screen)
    assert ipc.windows()[a]['fullscreen'] == 2 and ipc.windows()[a]['fullscreenClient'] == 0
    ipc.action('flip'); ipc.focus(c); fills(screen)
    assert ipc.windows()[c]['fullscreenClient'] == 0
    ipc.action('fullscreen')
    assert not any(ipc.windows()[x]['fullscreen'] for x in (a, b, c)) and tuple(card()['box']) == tile
    ipc.focus(b); ipc.call('dispatch', FULL)
    assert ipc.windows()[b]['fullscreenClient'] == 2, 'app fullscreen sync was not restored'
    ipc.call('dispatch', FULL)
    ipc.focus(b); ipc.action('fullscreen'); ipc.call('dispatch', FULL)
    assert not any(ipc.windows()[x]['fullscreen'] for x in (a, b, c)) and tuple(card()['box']) == tile
    passed('the card fullscreen action fills the screen without telling apps, and either toggle leaves')

    ipc.action('floating'); assert card()['floating']
    floated = tuple(card()['box'])
    ipc.call('dispatch', FULL); fills(screen)
    ipc.focus(b); fills(screen)
    ipc.call('dispatch', FULL)
    assert tuple(card()['box']) == floated and card()['floating'], (card()['box'], floated)
    ipc.action('floating'); assert not card()['floating']
    passed('floating cards fullscreen as a whole and return to their floating frame')

    ipc.focus(a)
    ipc.call('dispatch', FULL); fills(screen)
    ipc.call('plugin', 'unload', str(library)); loaded = False
    for address in (a, b, c):
        assert not ipc.windows()[address]['grouped']
    passed('unloading during fullscreen releases every app')
finally:
    if pointer:
        try: pointer.communicate('quit\n', timeout=3)
        except Exception: pointer.kill()
    for process in processes:
        if process.poll() is None: process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    if output:
        try: ipc.call('output', 'remove', output)
        except Exception: pass
    (root / 'fullscreen-results.json').write_text(json.dumps(checks, indent=2))
