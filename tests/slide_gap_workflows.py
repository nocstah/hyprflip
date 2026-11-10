#!/usr/bin/env python3
"""A tiled card's faces slide inside the card, so the gap beside it holds while they slide.

A tile and a tiled card side by side on a 3840x2160 output at scale 1.5, with the pilot desktop's gaps_in 8,
gaps_out 18 and 2 px borders. The card's layout slot also holds the gaps_in towards the tile; a turn drawn in
the slot slid the faces into that space and halved the gap until the slide ended. Frames are captured mid-slide
both ways for a three-face card (the strip) with the card right and then left of the tile, with and without a
card frame, and for a two-face card with the slide transition. Every column between the two border boxes must
show only the background, as it does at rest. Window and workspace animations are off: no frame catches a tile
on its way, and no turn falls back to an instant switch while the workspace slides in. Only the Hyprflip core is
loaded. --plugin runs the suite against another build, such as an older one.
"""
import argparse
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--plugin', type=Path, default=project / 'build/hyprflip.so')
args = parser.parse_args()
root = args.session.parent
env = environment(args.session)
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
library = root / 'slide-gap-hyprflip.so'
captures = root / 'slide-gap'
processes, checks, loaded = {}, [], None
PLACE = '30'
COLORS = {'tile': '203040', 'a': 'c04040', 'b': '40a040', 'c': 'c0a020', 'd': '4060c0', 'e': 'a040a0'}
LOOK = '''
hl.config({general={gaps_in=8,gaps_out=18,border_size=2},decoration={shadow={enabled=false}},dwindle={force_split=2},
  cursor={no_warps=true}})
hl.animation({leaf="windows",enabled=false})
hl.animation({leaf="workspaces",enabled=false})
'''


def wait(fn, seconds=8, what='condition'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for ' + what)


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name):
    app = 'hyprflip-gap-' + name
    processes[name] = subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                                        '--override', f'colors-dark.background={COLORS[name]}', 'sh', '-c', 'exec cat'],
                                       env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()), what=app)
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def rgb(name): return tuple(int(COLORS[name][i:i + 2], 16) for i in (0, 2, 4))
def near(a, b, tolerance=12): return all(abs(x - y) <= tolerance for x, y in zip(a, b))
def card(): (c,) = ipc.status()['containers']; return c
def focus(address): ipc.call('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
def setting(**values): ipc.call('eval', 'hl.config({plugin={hyprflip={' + ','.join(f'{k}={v}' for k, v in values.items()) + '}}})')


def settled():
    """Waits until two reads of the windows' boxes 150 ms apart agree. Layout animations are off."""
    boxes = lambda: {a: (x['at'], x['size']) for a, x in ipc.windows().items()}
    for _ in range(20):
        first = boxes(); time.sleep(.15)
        if first == boxes(): return
    raise AssertionError('The layout did not settle')


def restore(names):
    addresses = [ids[n] for n in names]
    words = ['front', 'back', 'face']
    x, y = ipc.windows()[addresses[0]]['at']; width, height = ipc.windows()[addresses[0]]['size']
    line = ' '.join(f'{word} horizontal {a} {a}:1' for word, a in zip(words, addresses))
    reply = ipc.batch([f'hyprflip restore quiet tiled 0 0 {x} {y} {width} {height} ' + line])[-1]
    assert reply.startswith('ok'), reply
    wait(lambda: len(ipc.status()['containers']) == 1, what='the card')


def gap(image, boxes, scale, origin, background):
    """The gap between the two border boxes in logical px, and its pixels on five rows that show anything but
    the background, leaving out a pixel at each edge for antialiasing."""
    (left, (lw, lh)), (right, (_, rh)) = sorted(boxes, key=lambda b: b[0][0])
    border = 2
    start = math.ceil((left[0] + lw + border - origin[0]) * scale) + 1
    end = math.floor((right[0] - border - origin[0]) * scale) - 1
    top = max(left[1], right[1]) + 40
    bottom = min(left[1] + lh, right[1] + rh) - 40
    pixels = image.load()
    rows = [round((top + (bottom - top) * k / 4 - origin[1]) * scale) for k in range(5)]
    width = right[0] - border - (left[0] + lw + border)
    return width, [(x, y) for y in rows for x in range(start, end) if not near(pixels[x, y][:3], background)]


def turns(label, names, flips):
    """Captures each turn mid-slide and returns the gap's width and the frames where it is not clear.
    `flips` holds (face to start from, action): one turn each way."""
    c = card()
    tile = ipc.windows()[ids['tile']]
    shown = ipc.windows()[c['faces'][c['active']][0]]
    boxes = [(tile['at'], tile['size']), (shown['at'], shown['size'])]
    rest = shot(f'{label}-rest')
    # The background, read halfway down the middle of the gap at rest (Hyprland's own notices cover the top).
    left, right = sorted((tile, shown), key=lambda win: win['at'][0])
    middle = ((left['at'][0] + left['size'][0] + right['at'][0]) / 2, shown['at'][1] + shown['size'][1] / 2)
    background = rest.load()[round((middle[0] - origin[0]) * scale), round((middle[1] - origin[1]) * scale)][:3]
    width, dirty = gap(rest, boxes, scale, origin, background)
    assert width == 16 and not dirty, (label, width, dirty[:5])
    faces = {rgb(n) for n in names}
    bad = []
    for start, word in flips:
        for progress in (.3, .65):
            assert ipc.action(f"card {c['id']} show {start + 1}").startswith('ok')
            wait(lambda: card()['active'] == start and not ipc.status()['animating'], what='the starting face')
            focus(card()['faces'][start][0])
            reply = ipc.action(word.format(id=c['id'])); assert reply.startswith('ok'), reply
            wait(lambda: ipc.status()['progress'] >= progress, what='the slide: ' + ipc.status()['last_fallback'])
            image = shot(f'{label}-{start}-{word.split()[-1]}-{progress}')
            ipc.action('finish'); wait(lambda: not ipc.status()['animating'], what='the turn to end')
            pixels = image.load()
            row = round((shown['at'][1] + shown['size'][1] / 2 - origin[1]) * scale)
            first = round((shown['at'][0] - origin[0]) * scale)
            last = round((shown['at'][0] + shown['size'][0] - origin[0]) * scale)
            # Turning faces are drawn a little darker.
            seen = {f for f in faces for x in range(first, last, 4) if near(pixels[x, row][:3], f, 40)}
            assert len(seen) >= 2, (label, word, progress, 'not mid-slide')
            _, dirty = gap(image, boxes, scale, origin, background)
            if dirty: bad.append((start, word, progress, len(dirty), dirty[0]))
    assert ipc.action(f"card {c['id']} show front").startswith('ok')
    return width, bad


def shot(name):
    # The pointer waits in the outer gap above the tiles, where no window takes the focus from it.
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={origin[0] + 200},y={origin[1] + 4}}})')
    path = captures / (name + '.png')
    subprocess.run(['grim', '-l', '0', '-o', output, str(path)], env=env, check=True, timeout=8)
    return Image.open(path).convert('RGB')


output = None
try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    captures.mkdir(exist_ok=True)
    shutil.copy2(args.plugin, library)
    ipc.call('plugin', 'load', str(library)); loaded = library
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + LOOK + f'hl.monitor({{output="{output}",mode="3840x2160@60",position="4000x0",scale=1.5}})\n'
                      f'hl.workspace_rule({{workspace="{PLACE}",monitor="{output}"}})\n')
    ipc.call('reload'); assert not ipc.call('configerrors'), ipc.call('configerrors')
    setting(duration_ms=0, notifications='false', card_frame='false', transition='"flip"')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={PLACE}}})')
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    scale, origin = monitor['scale'], (monitor['x'], monitor['y'])

    ids = {'tile': spawn('tile')}
    for name in 'abc': ids[name] = spawn(name)
    restore('abc')
    settled()
    c, clients = card(), ipc.windows()
    tile, shown = clients[ids['tile']], clients[c['faces'][0][0]]
    assert tile['at'][0] < shown['at'][0], 'the card is right of the tile'
    assert c['box'][0] < shown['at'][0] - 2, ('the slot holds the gap towards the tile', c['box'], shown['at'])
    setting(duration_ms=2400)
    width, bad = turns('strip-right', 'abc', ((0, 'card {id} flip'), (0, 'face 3')))
    assert not bad, bad
    passed(f'a three-face card right of a tile slides its faces both ways and the {width} px gap beside it stays clear')

    setting(card_frame='true')
    settled()
    width, bad = turns('strip-framed', 'abc', ((0, 'card {id} flip'), (0, 'face 3')))
    assert not bad, bad
    setting(card_frame='false')
    passed('with a card frame the gap stays clear as well')

    focus(ids['tile']); ipc.call('dispatch', 'hl.dsp.layout("swapsplit")')
    wait(lambda: ipc.windows()[card()['faces'][0][0]]['at'][0] < ipc.windows()[ids['tile']]['at'][0], what='the swap')
    settled()
    width, bad = turns('strip-left', 'abc', ((0, 'card {id} flip'), (0, 'face 3')))
    assert not bad, bad
    passed(f'left of the tile, the {width} px gap on its other side stays clear too')

    for name in 'abc': processes.pop(name).terminate()
    wait(lambda: not ipc.status()['containers'], what='the card to close')
    focus(ids['tile'])
    for name in 'de': ids[name] = spawn(name)
    restore('de')
    settled()
    setting(transition='"slide"')
    width, bad = turns('slide-two', 'de', ((0, 'card {id} flip'), (1, 'card {id} flip')))
    assert not bad, bad
    passed(f'a two-face card with the slide transition keeps the {width} px gap clear both ways')
    print(len(checks), 'checks passed')
finally:
    for process in processes.values(): process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(loaded))
        except Exception: pass
    config.write_text(original)
    try: ipc.call('reload')
    except Exception: pass
