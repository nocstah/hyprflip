#!/usr/bin/env python3
"""A covered card built in one restore (restore ... cover <address>), as a workspace
manager builds its card again under Herdr's window on a visit: the apps come from a
special workspace in the same batch, and the card may have one face of its own. The
card is founded on the cover, so it takes the cover's tile exactly, wherever dwindle
split to make room for the apps that came in; the keyboard stays on the cover and the
card shows it. Also each refusal's sentence, parking (which still takes a card of one
face of its own apart and leaves the cover in place), closes, and the face move of a
card with one face of its own. Only the Hyprflip core is loaded; no call may move the
pointer.

With --hooks-off, run it in a session whose Hyprland was started with
HYPRFLIP_CLOSE_HOOKS=0 in its environment: the restore does not depend on close
reasons, and closes read unknown."""
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
parser.add_argument('--hooks-off', action='store_true',
                    help='the session runs with HYPRFLIP_CLOSE_HOOKS=0: closes read unknown')
args = parser.parse_args()
root = args.session.parent
home = root / 'restore-cover'
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
env.pop('notify_log', None)
for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY'):
    env.pop(key, None)
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = {}, []
library = root / 'restore-cover-hyprflip.so'
loaded = False
PLACE, OTHER, PARK = 81, 82, 'special:park'


def wait(fn, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name):
    app = 'hyprflip-restore-cover-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
               'sh', '-c', 'printf "\\n  %s\\n" "$1"; exec cat', 'pane', name]
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    address = next(a for a, win in ipc.windows().items() if win['class'] == app)
    processes[address] = process
    return address


def press(key):
    subprocess.run(['wtype', '-M', 'logo', '-k', key, '-m', 'logo'], env=env, check=True, timeout=5)


def active(): return ipc.data('-j', 'activewindow').get('address')
def card(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)
def gone(id): return not any(c['id'] == id for c in ipc.status()['containers'])
def mark(): return ipc.status()['closes']['next']
def tile(address):
    win = ipc.windows()[address]
    return [*win['at'], *win['size']]
def same(a, b, slack=1): return all(abs(x - y) <= slack for x, y in zip(a, b))


def framing(card_box, window_box, slack=10):
    """The card's box is its shown window's box with the window's border, and at most a gap, round it."""
    edges = (window_box[0] - card_box[0], window_box[1] - card_box[1],
             card_box[0] + card_box[2] - window_box[0] - window_box[2],
             card_box[1] + card_box[3] - window_box[1] - window_box[3])
    return all(0 <= edge <= slack for edge in edges)


def apart(a, b):
    """Two [x, y, w, h] boxes that do not overlap."""
    return a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def pointer():
    at = ipc.data('-j', 'cursorpos')
    return at['x'], at['y']


def rest(over):
    """Leaves the pointer off-centre over a window, where a warp to any window's centre shows."""
    x, y, width, height = tile(over)
    point = x + width // 4, y + height // 3
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={point[0]},y={point[1]}}})')
    assert pointer() == point, (over, point, pointer())
    return point


def move(address, place):
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{address}",workspace="{place}",follow=false}})')
    wait(lambda: ipc.windows()[address]['workspace']['name'] == str(place))


def loose(address, place):
    """A window out of any card or group, taking input, on the workspace named `place`."""
    win = ipc.windows()[address]
    assert not win['grouped'] and win['acceptsInput'] and win['workspace']['name'] == str(place), win


def visible(id, cover):
    """Only the shown face takes input: the cover's when covered, else the face status calls active."""
    c, windows = card(id), ipc.windows()
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (not c['covered'] and side == c['active']), (c, windows[address])
    assert windows[cover]['acceptsInput'] == c['covered'], (c, windows[cover])


def shot(box, name):
    """The pixels inside a box, borders left out, once the screen has settled. Hyprland's own notifications, whose
    countdown bars change from frame to frame, are dismissed first."""
    wait(lambda: not ipc.status()['animating'])
    try: ipc.call('dismissnotify')
    except w.SetupError: pass
    time.sleep(.4)
    x, y, width, height = (round(v) for v in box)
    inset = 12
    path = home / (name + '.ppm')
    subprocess.run(['grim', '-t', 'ppm', '-g', f'{x + inset},{y + inset} {width - 2 * inset}x{height - 2 * inset}',
                    str(path)], env=env, check=True, capture_output=True, timeout=8)
    return path.read_bytes()


def line(box, faces, cover=None, active=0, mode='tiled', unfolded=0, tail=''):
    words = ['front', 'back'] + ['face'] * (len(faces) - 2)
    text = ' '.join(f'{word} horizontal {apps[0]} ' + ' '.join(f'{app}:1' for app in apps)
                    for word, apps in zip(words, faces))
    return (f'restore quiet {mode} {active} {unfolded} ' + ' '.join(str(round(v)) for v in box) + ' ' + text +
            (f' cover {cover}' if cover else '') + tail)


def build(faces, cover, active=0):
    """The batch a helper sends: the apps come to the cover's workspace, then the card is restored under the cover."""
    windows = ipc.windows()
    place = windows[cover]['workspace']['id']
    commands = [w.Unattended.move_command(a, place) for face in faces for a in face
                if windows[a]['workspace']['id'] != place]
    commands.append('hyprflip ' + line(tile(cover), faces, cover, active))
    before = pointer()
    replies = ipc.batch(commands)
    assert replies == ['ok'] * (len(commands) - 1) + ['ok: ok'], replies
    assert pointer() == before, (before, pointer())
    return next(c for c in ipc.status()['containers'] if c['cover'] == cover)['id']


def refused(action, sentence):
    """A restore the core refuses with this sentence, changing no card."""
    before = ipc.status()['containers']
    try:
        reply = ipc.action(action)
        raise AssertionError((action, reply))
    except w.SetupError as error:
        reply = str(error)
    assert reply == sentence, (action, reply, sentence)
    assert ipc.status()['containers'] == before, action


def lua_refused(*operations):
    """A keyboard action through the plugin's Lua functions that the core refuses, as the message it gives."""
    before = ipc.status()['containers']
    try:
        ipc.focused(*operations)
        raise AssertionError(operations)
    except w.SetupError as error:
        reply = str(error)
    assert ipc.status()['containers'] == before, operations
    return reply


def records(since, count):
    wait(lambda: mark() >= since + count)
    found = [r for r in ipc.status()['closes']['list'] if r['seq'] >= since]
    assert len(found) == count, found
    return found


def place(record, card_id, face, index, faces, cover=False, dissolved=False):
    got = tuple(record[k] for k in ('card', 'face', 'index', 'faces', 'cover', 'dissolved'))
    assert got == (card_id, face, index, faces, cover, dissolved), record


def why(record):
    """A key close reads requested by key, or unknown with the hooks off."""
    expected = ('unknown', None) if args.hooks_off else ('requested', 'key')
    assert (record['reason'], record['via']) == expected, record


def close_key(address):
    """Super+F9 on the window: hl.dsp.window.close() from a key bind."""
    ipc.focus(address)
    press('F9')
    wait(lambda: address not in ipc.windows())
    processes.pop(address, None)


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(mode=0o700, parents=True)
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    # Only the fixtures' virtual keyboard: the parent's keyboard can keep a modifier held. No card frame, so the
    # cover's window keeps exactly the box its tile had.
    config.write_text(original + '''
hl.device({name="wl_keyboard",enabled=false})
hl.config({input={resolve_binds_by_sym=true}})
hl.bind("SUPER + F9", hl.dsp.window.close())
hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false,card_frame=false}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={PLACE}}})')
    state = ipc.status()
    assert state['restore_cover'] is True and state['card_cover'] is True, state
    assert state['close_reasons'] is (not args.hooks_off), state['close_reasons']
    passed('status reports restore_cover' + (', with the close hooks off' if args.hooks_off else ''))

    # 1. One face of its own. Herdr's stand-in X alone on the workspace with the keyboard, the app waiting on
    # special:park; one batch brings the app and builds the card under X.
    x = spawn('herdr')
    a = spawn('app')
    move(a, PARK)
    ipc.focus(x)
    wait(lambda: active() == x)
    loose(x, PLACE)
    box = tile(x)
    rest(x)
    before = shot(box, 'one-before')
    one = build([[a]], x)
    c = card(one)
    assert (c['faces'], c['cover'], c['covered'], c['active'], len(c['names'])) == ([[a]], x, True, 0, 1), c
    assert framing(c['box'], box) and same(tile(x), box), (c['box'], tile(x), box)
    assert c['workspace']['id'] == PLACE and active() == x, (c, active())
    visible(one, x)
    assert shot(box, 'one-after') == before, 'the cover moved or changed size'
    passed('one batch brings an app from a special workspace and builds a card of one face of its own under the '
           'cover: status lists faces [[A]] with cover X, covered; the card takes X\'s tile exactly (grim shows X '
           'unchanged), the keyboard stays on X and the pointer does not move')
    assert ipc.action(f'card {one} flip') == 'ok: ok'
    wait(lambda: not card(one)['covered'])
    assert card(one)['active'] == 0
    visible(one, x)
    assert ipc.action(f'card {one} flip') == 'ok: ok'
    wait(lambda: card(one)['covered'])
    visible(one, x)
    assert ipc.action(f'card {one} show 1') == 'ok: ok'
    wait(lambda: not card(one)['covered'])
    visible(one, x)
    assert ipc.action(f'card {one} show cover') == 'ok: ok'
    wait(lambda: card(one)['covered'])
    visible(one, x)
    passed('a flip turns the card to A and back to the cover, and card show 1 shows A')

    # 1b. Founded on the cover: with the keyboard and the pointer on a neighbour Y, dwindle makes room for the app
    # beside Y; the card still takes X's tile, and Y gets its own back.
    assert ipc.action(f'card {one} ungroup') == 'ok: ok' and gone(one)
    move(a, PARK)
    y = spawn('neighbour')
    loose(y, PLACE)
    ipc.focus(y)
    wait(lambda: active() == y)
    boxes = {x: tile(x), y: tile(y)}
    rest(y)
    before = shot(boxes[x], 'beside-before')
    beside = build([[a]], x)
    c = card(beside)
    assert (c['faces'], c['cover'], c['covered']) == ([[a]], x, True), c
    assert framing(c['box'], boxes[x]) and same(tile(x), boxes[x]) and same(tile(y), boxes[y]), (c, tile(x), tile(y), boxes)
    assert apart(c['box'], tile(y)), (c['box'], tile(y))
    assert active() == y, active()
    assert shot(boxes[x], 'beside-after') == before, 'the cover moved or changed size'
    passed('with the keyboard and the pointer on a neighbour, the card still takes the cover\'s tile and the '
           'neighbour keeps its own; the keyboard stays on the neighbour')
    assert ipc.action(f'card {beside} ungroup') == 'ok: ok' and gone(beside)
    processes.pop(y).terminate()
    wait(lambda: y not in ipc.windows())

    # 2. Two faces of their own, the back requested.
    b = spawn('back')
    move(a, PARK); move(b, PARK)
    ipc.focus(x)
    wait(lambda: active() == x)
    box = tile(x)
    rest(x)
    before = shot(box, 'two-before')
    two = build([[a], [b]], x, active=1)
    c = card(two)
    assert (c['faces'], c['cover'], c['covered'], c['active'], len(c['names'])) == ([[a], [b]], x, True, 1, 2), c
    assert framing(c['box'], box) and same(tile(x), box) and active() == x, (c, tile(x), box, active())
    visible(two, x)
    assert shot(box, 'two-after') == before, 'the cover moved or changed size'
    assert ipc.action(f'card {two} show 2') == 'ok: ok'
    wait(lambda: not card(two)['covered'] and card(two)['active'] == 1)
    visible(two, x)
    assert ipc.action(f'card {two} show 1') == 'ok: ok'
    wait(lambda: not card(two)['covered'] and card(two)['active'] == 0)
    visible(two, x)
    assert ipc.action(f'card {two} show cover') == 'ok: ok'
    wait(lambda: card(two)['covered'])
    passed('the same with two faces of their own: built in one batch under the cover, which keeps its tile and the '
           'keyboard; status reports the requested back as the face to return to, and show turns to each face')
    assert ipc.action(f'card {two} ungroup') == 'ok: ok' and gone(two)
    processes.pop(b).terminate()
    wait(lambda: b not in ipc.windows())

    # 3. Refusals, each with its sentence. The app is on the workspace already.
    ipc.focus(x)
    loose(a, PLACE)
    box = tile(x)
    refused(line(box, [[a]], '0x1'), 'No window has address 0x1.')
    p, q = spawn('p'), spawn('q')
    pq = build([[p], [q]], x)
    assert ipc.action(f'card {pq} uncover') == 'ok: ok'
    refused(line(tile(a), [[a]], p), 'That window is already in a card, pair or group. Release it first.')
    assert ipc.action(f'card {pq} ungroup') == 'ok: ok'
    for window in (p, q):
        processes.pop(window).terminate()
        wait(lambda: window not in ipc.windows())
    parked = spawn('parked')
    move(parked, PARK)
    refused(line(box, [[a]], parked), 'Bring the card back from its special workspace before covering it.')
    move(parked, OTHER)
    refused(line(box, [[a]], parked), "Move the window to the card's workspace before covering the card with it.")
    processes.pop(parked).terminate()
    wait(lambda: parked not in ipc.windows())
    ipc.focus(x)
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    wait(lambda: ipc.windows()[x]['fullscreen'])
    refused(line(box, [[a]], x), 'Leave fullscreen before covering a card with that window.')
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    wait(lambda: not ipc.windows()[x]['fullscreen'])
    box = tile(x)
    refused(line(box, [[a]], x, unfolded=1), 'Fold the card before covering it.')
    refused(line(box, [[a]], x, mode='floating'), 'A covered card is restored tiled.')
    many = [[a]] + [[f'0x{n}'] for n in range(1, 6)]
    refused(line(box, many, x), 'A card has at most 6 faces, its cover included.')
    refused(f'restore quiet tiled 0 0 {" ".join(map(str, box))} front horizontal {a} {a}:1 face horizontal {a} {a}:1 '
            f'cover {x}', 'Each face needs an axis and a focused app address.')
    refused(line(box, [[a]], x, tail=f' {a}:1'), 'Invalid app in the card description.')
    refused(line(box, [[a]], x, tail=f' back horizontal {a} {a}:1'),
            'Use cover <0x address> once, after the faces, in a card description.')
    refused(line(box, [[a]], x, tail=f' front horizontal {a} {a}:1'),
            'Use cover <0x address> once, after the faces, in a card description.')
    refused(line(box, [[a]], x, active=1), "The shown face is not one of the card's faces.")
    refused(line(box, [[a]], x, tail=f' cover {x}'), 'Use cover <0x address> once, after the faces, in a card description.')
    refused(line(box, [[a]]), 'A card needs apps on both faces.')
    loose(x, PLACE); loose(a, PLACE)
    passed('restore with a cover refuses, each with its sentence: an unmapped cover, a cover in a card, on a special '
           'workspace or another workspace, a fullscreen cover, an unfolded or floating card, more than six faces '
           'with the cover, a face before the back, an app or a face after the cover, a second cover, and a shown face '
           'that is not one of the card\'s own; without a cover one face is refused as before')

    # 4. Parking still takes a card of one face of its own apart and leaves the cover in its tile; the same restore
    # with the cover builds it again from the parked app.
    move(a, PARK)
    ipc.focus(x)
    box = tile(x)
    rest(x)
    first = build([[a]], x)
    assert ipc.action(f'card {first} workspace {PARK} silent') == 'ok: ok'
    wait(lambda: gone(first))
    loose(x, PLACE)
    loose(a, PARK)
    assert same(tile(x), box) and active() == x, (tile(x), box, active())
    again = build([[a]], x)
    c = card(again)
    assert again != first and (c['faces'], c['cover'], c['covered']) == ([[a]], x, True), c
    assert framing(c['box'], box) and same(tile(x), box) and active() == x, (c, box, active())
    passed('parking a card of one face of its own takes it apart, its app out of sight and the cover in its tile '
           'with the keyboard; a second restore with the cover builds it again from the parked app, in the same tile')

    # 6. The face move on a card of one face of its own: the next face round the cover is the same face.
    a2 = spawn('second')
    move(a2, PARK)
    assert ipc.action(f'card {again} ungroup') == 'ok: ok' and gone(again)
    move(a, PARK)
    ipc.focus(x)
    rest(x)
    pair = build([[a, a2]], x)
    assert card(pair)['faces'] == [[a, a2]], card(pair)
    assert ipc.action(f'card {pair} show 1') == 'ok: ok'
    wait(lambda: not card(pair)['covered'])
    assert 'This card has one face of its own.' in lua_refused((a, 'other_side'))
    assert 'This card has one face of its own.' in lua_refused((a, f'other_side {a2}'))
    passed('moving an app to the other side of a card with one face of its own is refused with "This card has one '
           'face of its own."')
    assert ipc.action(f'card {pair} ungroup') == 'ok: ok' and gone(pair)
    processes.pop(a2).terminate()
    wait(lambda: a2 not in ipc.windows())

    # 5. Closes. A key close of the card's only own app takes the card apart (it keeps two faces), and its record
    # says dissolved; so does a close of the cover.
    move(a, PARK)
    ipc.focus(x)
    rest(x)
    lone = build([[a]], x)
    assert ipc.action(f'card {lone} show 1') == 'ok: ok'
    wait(lambda: not card(lone)['covered'])
    clients = ipc.windows()
    start = mark()
    close_key(a)
    [r] = records(start, 1)
    assert r['address'] == a and r['initial_class'] == clients[a]['initialClass'], r
    place(r, lone, 0, 0, 1, dissolved=True); why(r)
    wait(lambda: gone(lone))
    loose(x, PLACE)
    c1 = spawn('closing')
    move(c1, PARK)
    ipc.focus(x)
    rest(x)
    covered = build([[c1]], x)
    clients = ipc.windows()
    start = mark()
    close_key(x)
    [r] = records(start, 1)
    assert r['address'] == x and r['initial_class'] == clients[x]['initialClass'], r
    place(r, covered, None, None, None, cover=True, dissolved=True); why(r)
    wait(lambda: gone(covered))
    loose(c1, PLACE)
    passed('a key close of the only app of a card with one face of its own takes the card apart and reads face 0 '
           'of 1, dissolved; a key close of its cover takes it apart too and reads cover, dissolved' +
           (' (reasons unknown with the hooks off)' if args.hooks_off else ''))
finally:
    for process in processes.values():
        if process and process.poll() is None: process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    (root / 'restore-cover-results.json').write_text(json.dumps(checks, indent=2))
