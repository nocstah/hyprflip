#!/usr/bin/env python3
"""Cards with three to six faces, in a disposable compositor with only the core loaded.

A card turns to its next face on each flip and comes round to the front again.
`card <id> show <n>` turns straight to a face. Attaching as a new face adds one,
up to six, taking the last app off a face removes it, and unfolding lays every
face out side by side. With animations on, a six-face card slides round all its
faces: frames captured mid-slide show faces 5 and 6, which the transition reads
from texture units of their own, and a plain flip of another card afterwards
still draws.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment
from PIL import Image

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
def spawn(name, colour=None):
    app = 'hyprflip-face-' + name
    look = ['--override', f'colors-dark.background={colour}'] if colour else []
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', *look, '--app-id', app, '--title', app, 'cat'],
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
def by_id(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)
def setting(**values): ipc.call('eval', 'hl.config({plugin={hyprflip={' + ','.join(f'{k}={v}' for k, v in values.items()) + '}}})')
def rgb(colour): return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))
def near(a, b, tolerance=40): return all(abs(x - y) <= tolerance for x, y in zip(a, b))
def turned(action, id, goal):
    """An animated turn: it starts with no fallback, ends on its face, and Hyprland still answers.
    `face <n>` acts on the focused card, so the app the card shows takes the focus first."""
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{by_id(id)["current"]}"}})')
    reply = ipc.action(action); assert reply.startswith('ok'), (action, reply)
    s = ipc.status()
    assert s['animating'] and s['last_fallback'] == '', (action, s['animating'], s['last_fallback'])
    wait(lambda: not ipc.status()['animating'], 'the turn: ' + action)
    s = ipc.status()
    assert by_id(id)['active'] == goal and s['last_fallback'] == '', (action, by_id(id)['active'], s['last_fallback'])
    assert ipc.data('-j', 'monitors'), 'Hyprland stopped answering'
def shot(name):
    path = root / (name + '.png')
    subprocess.run(['grim', '-l', '0', '-o', output, str(path)], env=env, check=True, timeout=8)
    return Image.open(path).convert('RGB')
def seen(image, id, colours):
    """The colours, of those given, along the middle row of a card."""
    x, y, width, height = by_id(id)['box']
    pixels, row = image.load(), round(y + height / 2 - top)
    found = {pixels[round(px - left), row] for px in range(round(x) + 8, round(x + width) - 8, 4)}
    return {c for c in colours if any(near(p, rgb(c)) for p in found)}
def at_face(id, side):
    """`card <id> show` turns at once, with no transition."""
    assert ipc.action(f'card {id} show {side + 1}').startswith('ok')
    wait(lambda: by_id(id)['active'] == side and not ipc.status()['animating'], f'face {side + 1}')
def midway(action, id, name, progress=.45):
    """A frame captured partway through a slow turn, which then finishes at once."""
    reply = ipc.action(action); assert reply.startswith('ok'), (action, reply)
    assert ipc.status()['last_fallback'] == '', ipc.status()['last_fallback']
    wait(lambda: ipc.status()['progress'] >= progress, 'the turn to get going: ' + action)
    image = shot(name)
    ipc.action('finish'); wait(lambda: not ipc.status()['animating'], 'the turn to end')
    return image


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session'
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    source = project / 'build/hyprflip.so'; target = root / ('faces-' + source.name)
    shutil.copy2(source, target); ipc.call('plugin', 'load', str(target)); loaded.append(target)
    # Windows and workspaces do not animate: no turn falls back while an app is still on its way.
    config.write_text(original + f'\nhl.monitor({{output="{output}",mode="1920x1080@60",position="4000x0",scale=1}})\n'
                      'hl.workspace_rule({workspace="52",monitor="' + output + '"})\n'
                      'hl.animation({leaf="windows",enabled=false})\nhl.animation({leaf="workspaces",enabled=false})\n')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=52})')
    status = ipc.status()
    assert status.get('container_max_faces') == 6, status.get('container_max_faces')
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    left, top = monitor['x'], monitor['y']

    a, b, c3, d, e = (spawn(n) for n in ('a', 'b', 'c', 'd', 'e'))
    reply = restore([left + 100, top + 100, 800, 600], [[a], [b, c3], [d]])
    assert reply.startswith('ok'), reply
    c = card()
    assert c['faces'] == [[a], [b, c3], [d]] and c['active'] == 0 and len(c['layouts']) == 3, c
    passed('a card restores with three faces, the second holding two apps')

    # An update takes cards apart and restores them from card_restore.describe.
    import card_restore
    line = card_restore.describe(c)
    assert ipc.action(f'card {c["id"]} ungroup').startswith('ok'); wait(lambda: not cards(), 'ungroup')
    reply = ipc.batch(['hyprflip restore quiet ' + line])[-1]
    assert reply.startswith('ok'), (reply, line)
    c = card()
    assert c['faces'] == [[a], [b, c3], [d]], c
    passed('a three-face card survives the description an update restores it from')

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

    fifth, sixth = spawn('f'), spawn('g')
    ipc.focused((fifth, 'mark'), (e, 'attach face'))
    wait(lambda: len(card()['faces']) == 5, 'the fifth face')
    assert card()['active'] == 4, card()
    ipc.focused((sixth, 'mark'), (fifth, 'attach face'))
    wait(lambda: len(card()['faces']) == 6, 'the sixth face')
    c = card()
    assert c['faces'][4:] == [[fifth], [sixth]] and c['active'] == 5, c
    assert len(c['layouts']) == 6 and len(c['names']) == 6, c
    passed('a fifth and a sixth face join the same way, and the card turns to each')

    spare = spawn('h')
    try:
        ipc.focused((spare, 'mark'), (sixth, 'attach face'))
        raise AssertionError('A seventh face was accepted')
    except w.SetupError as error:
        assert 'already has 6 faces' in str(error), error
    assert len(card()['faces']) == 6
    passed('a seventh face is refused, naming the limit')

    c = card()
    assert ipc.action(f"card {c['id']} show 5").startswith("ok"); wait(lambda: card()['active'] == 4, 'show 5')
    assert ipc.action(f"card {c['id']} show 6").startswith("ok"); wait(lambda: card()['active'] == 5, 'show 6')
    try:
        ipc.call('hyprflip', f'card {c["id"]} show 7'); raise AssertionError('show 7 was accepted')
    except w.SetupError as error:
        assert 'face number from 1 to 6' in str(error), error
    passed('card <id> show turns to the fifth and sixth faces and refuses a seventh')

    line = card_restore.describe(c)
    assert line.count(' face ') == 4, line
    assert ipc.action(f'card {c["id"]} ungroup').startswith('ok'); wait(lambda: not cards(), 'ungroup')
    reply = ipc.batch(['hyprflip restore quiet ' + line])[-1]
    assert reply.startswith('ok'), (reply, line)
    c = card()
    assert c['faces'] == [[a], [b, c3], [d], [e], [fifth], [sixth]] and c['active'] == 5, c
    passed('a six-face card survives the description an update restores it from')

    ipc.focused((sixth, 'release'))
    wait(lambda: len(card()['faces']) == 5, 'the sixth face to go')
    ipc.focused((fifth, 'release'))
    wait(lambda: len(card()['faces']) == 4, 'the fifth face to go')
    assert card()['faces'] == [[a], [b, c3], [d], [e]], card()

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

    # Six faces in motion. Solid colours tell the faces apart in captured frames.
    for process in processes:
        process.terminate()
    wait(lambda: not any(win['class'].startswith('hyprflip-face-') for win in ipc.windows().values()), 'the apps to close')
    COLOURS = ['c04040', '40a040', 'c0a020', '4060c0', 'a040a0', '40b0b0']
    PLAIN = ['e0e0e0', '604020']
    six = [spawn(f'six{i}', colour) for i, colour in enumerate(COLOURS)]
    plain = [spawn(f'plain{i}', colour) for i, colour in enumerate(PLAIN)]
    assert restore([left + 40, top + 140, 1100, 700], [[x] for x in six]).startswith('ok')
    assert restore([left + 1200, top + 140, 680, 700], [[x] for x in plain]).startswith('ok')
    wait(lambda: len(cards()) == 2, 'both cards')
    sid = next(c['id'] for c in cards() if c['faces'][0] == [six[0]])
    pid = next(c['id'] for c in cards() if c['faces'][0] == [plain[0]])
    assert by_id(sid)['active'] == 0 and len(by_id(sid)['faces']) == 6
    time.sleep(.3)
    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=400,transition="slide"}}})')
    turned('face 4', sid, 3)            # three faces on
    turned(f'card {sid} flip', sid, 4)  # 4 to 5
    turned(f'card {sid} flip', sid, 5)  # 5 to 6
    turned(f'card {sid} flip', sid, 0)  # 6 round to 1
    turned('face 6', sid, 5)            # 1 back to 6, the short way
    turned('face 3', sid, 2)            # 6 on round to 3
    turned('face 6', sid, 5)            # 3 past 4 and 5 to 6
    passed('a six-face card slides round every face, flips 4 to 5 to 6 and 6 round to 1, and jumps three faces, '
           'with no fallback and Hyprland still answering')

    setting(duration_ms=2400)
    at_face(sid, 4)
    frame = midway(f'card {sid} flip', sid, 'six-5-6')
    assert by_id(sid)['active'] == 5
    assert {COLOURS[4], COLOURS[5]} <= seen(frame, sid, COLOURS), seen(frame, sid, COLOURS)
    frame = midway(f'card {sid} flip', sid, 'six-6-1')
    assert by_id(sid)['active'] == 0 and ipc.status()['last_fallback'] == ''
    assert {COLOURS[5], COLOURS[0]} <= seen(frame, sid, COLOURS), seen(frame, sid, COLOURS)
    passed('frames mid-slide show face 5 beside face 6, and face 6 beside face 1 as the card comes round')

    setting(duration_ms=420)
    at_face(sid, 4)
    box = by_id(sid)['box']
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={round(box[0] + box[2] / 2)},y={round(box[1] + box[3] / 2)}}})')
    def swipe(*moves):
        assert ipc.action('swipe begin 3').startswith('ok')
        for dx, ms in moves: assert ipc.action(f'swipe move {dx} {ms}').startswith('ok')
        assert ipc.action('swipe end').startswith('ok')
        wait(lambda: not ipc.status()['swiping'] and not ipc.status()['animating'], 'the swipe to settle')
        assert ipc.status()['last_fallback'] == '', ipc.status()['last_fallback']
        return by_id(sid)['active']
    assert swipe(*[(-120, 40)] * 6) == 5
    assert swipe(*[(120, 40)] * 6) == 4
    assert swipe(*[(-120, 40)] * 6) == 5 and swipe(*[(-120, 40)] * 6) == 0
    passed('three-finger swipes go from face 5 to 6, back, and from 6 round to 1')

    # Super+Ctrl+Alt+1 to 4 stay the face keys: examples/containers-setup.lua binds them to the plugin's Lua
    # face(n), which reaches faces 5 and 6 too. Simulated keys do not reach bindings in a nested session.
    for n, goal in ((4, 3), (1, 0), (5, 4), (6, 5)):
        ipc.call('dispatch', f'hl.dsp.focus({{window="address:{by_id(sid)["current"]}"}})')
        ipc.call('eval', f'hl.plugin.hyprflip.face({n})')
        wait(lambda: by_id(sid)['active'] == goal and not ipc.status()['animating'], f'face({n})')
        assert ipc.status()['last_fallback'] == '', ipc.status()['last_fallback']
    passed("the face keys' Lua face(n) turns a six-face card to faces 4 and 1, and face(5) and face(6) to the others")

    # The slides bound textures to units 5 and 6; another card's plain flip still draws its own faces.
    setting(duration_ms=2400, transition='"flip"')
    frame = midway(f'card {pid} flip', pid, 'plain-flip', progress=.3)
    x, y, width, height = by_id(pid)['box']
    centre = frame.load()[round(x + width / 2 - left), round(y + height / 2 - top)]
    assert near(centre, rgb(PLAIN[0])), centre
    assert not seen(frame, pid, COLOURS), seen(frame, pid, COLOURS)
    assert by_id(pid)['active'] == 1 and ipc.status()['last_fallback'] == ''
    time.sleep(.3)
    rest = shot('plain-rest')
    assert near(rest.load()[round(x + width / 2 - left), round(y + height / 2 - top)], rgb(PLAIN[1])), 'the back'
    passed('after the slides, a plain flip of another card draws its own faces and ends on its back')
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
