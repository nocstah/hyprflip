#!/usr/bin/env python3
"""A window covering a card (card <id> cover), as a workspace manager puts its own
window over a card on a narrow screen: the window joins the card as an extra face
that status leaves out, flips like any face, never goes out of sight with the card
and comes out as an ordinary tile. Only the Hyprflip core is loaded (native dwindle
cards); no call may move the pointer. With --protocol (Hyprland's
wlr-virtual-pointer-unstable-v1.xml) a real Super-drag also drops an app on the cover's face;
start the session with --notify-recorder to read the refusal it shows."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--protocol', type=Path, help='wlr-virtual-pointer-unstable-v1.xml for the drag-to-add check')
args = parser.parse_args()
root = args.session.parent
home = root / 'cover'
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
notify_log = Path(env.pop('notify_log')) if 'notify_log' in env else None
for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY'):
    env.pop(key, None)
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = {}, []
library, probe = root / 'cover-hyprflip.so', root / 'cover-probe.so'
loaded = probed = False
mouse = held = None
COVER_FACE = "This face is the card's cover and holds only that window."


def wait(fn, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name, gtk=False):
    app = 'hyprflip-cover-' + name
    if gtk:
        command = ['python3', str(project / 'tests/gtk_fixture.py'), app, str(home / (name + '.control'))]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                   'sh', '-c', 'printf "\\n  %s\\n" "$1"; exec cat', 'pane', name]
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    address = next(a for a, win in ipc.windows().items() if win['class'] == app)
    processes[address] = process
    return address


def close(address):
    processes.pop(address).terminate()
    wait(lambda: address not in ipc.windows())


def active(): return ipc.data('-j', 'activewindow').get('address')
def workspace(): return ipc.data('-j', 'activeworkspace')['id']
def card(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)
def gone(id): return not any(c['id'] == id for c in ipc.status()['containers'])
def tile(address):
    win = ipc.windows()[address]
    return [*win['at'], *win['size']]


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


def still(action, over):
    """An action by id, sent while the pointer rests over a window: the pointer stays there."""
    before = rest(over)
    reply = ipc.action(action)
    time.sleep(.1)
    assert pointer() == before, (action, before, pointer())
    return reply


def refused(action, over=None):
    """A refusal that changes no card and, when over is given, leaves the pointer where it was."""
    before, at = ipc.status(), rest(over) if over else None
    try:
        reply = ipc.action(action)
        raise AssertionError((action, reply))
    except w.SetupError as error:
        reply = str(error)
    after = ipc.status()
    assert after['containers'] == before['containers'] and after['pairs'] == before['pairs'], action
    assert not over or pointer() == at, (action, at, pointer())
    return reply


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


def apart(a, b):
    """Two [x, y, w, h] boxes that do not overlap."""
    return a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def inside(a, b, slack=1):
    """Box a lies within box b."""
    return (a[0] >= b[0] - slack and a[1] >= b[1] - slack and a[0] + a[2] <= b[0] + b[2] + slack and
            a[1] + a[3] <= b[1] + b[3] + slack)


def same(a, b, slack=1): return all(abs(x - y) <= slack for x, y in zip(a, b))


def loose(address, place):
    """A window out of any card or group, taking input, on the workspace named `place`."""
    win = ipc.windows()[address]
    assert not win['grouped'] and win['acceptsInput'] and win['workspace']['name'] == place, win


def visible(id, cover=None):
    """Only the shown face takes input: the cover's when covered, else the face status calls active."""
    c, windows = card(id), ipc.windows()
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (not c['covered'] and side == c['active']), (c, windows[address])
    if cover:
        assert windows[cover]['acceptsInput'] == c['covered'], (c, windows[cover])


def restore(apps, over):
    """A quiet restore of a tiled card with one app on each face, beside the window `over`."""
    box = ipc.windows()[apps[0]]
    words = ['front', 'back'] + ['face'] * (len(apps) - 2)
    reply = still(f'restore quiet tiled 0 0 {box["at"][0]} {box["at"][1]} {box["size"][0]} {box["size"][1]} ' +
                  ' '.join(f'{word} horizontal {app} {app}:1' for word, app in zip(words, apps)), over)
    assert reply == 'ok: ok', reply
    return next(c for c in ipc.status()['containers'] if apps[0] in c['faces'][0])['id']


class Keyboard:
    """The windows Hyprland's event socket said took the keyboard, in order."""
    def __init__(self):
        self.moves = []
        events = Path(env['XDG_RUNTIME_DIR']) / 'hypr' / env['HYPRLAND_INSTANCE_SIGNATURE'] / '.socket2.sock'
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.connect(str(events))
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        pending = b''
        while chunk := self.connection.recv(65536):
            *lines, pending = (pending + chunk).split(b'\n')
            self.moves += ['0x' + line[16:].decode() for line in lines if line.startswith(b'activewindowv2>>')]


def send(command):
    mouse.stdin.write(command + '\n'); mouse.stdin.flush()
    assert mouse.stdout.readline().strip() == 'ok'


def drag(app):
    """Starts a native Super-drag of an app with a virtual pointer, as card_interactions.py does."""
    global mouse, held
    ipc.focus(app)
    win = ipc.windows()[app]
    x, y = (round(win['at'][i] + win['size'][i] / 2) for i in (0, 1))
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x},y={y}}})')
    held = subprocess.Popen(['wtype', '-M', 'logo', '-s', '20000', '-m', 'logo'], env=env)
    wait(lambda: ipc.data('hf-motion-probe', 'input')['mods'] == 64)
    mouse = subprocess.Popen([str(home / 'pointer'), '--stream'], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    assert mouse.stdout.readline().strip() == 'ready'
    send('down')
    for _ in range(3): send('move 12 0'); time.sleep(.025)
    assert ipc.data('hf-motion-probe', 'input')['drag'], 'Native window drag did not start'


def drop():
    global mouse, held
    send('up')
    mouse.communicate('quit\n', timeout=3)
    mouse = None
    held.terminate(); held.wait(timeout=3); held = None
    time.sleep(.2)


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    shutil.rmtree(home, ignore_errors=True)
    (home / 'caller').mkdir(mode=0o700, parents=True)
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    extra = ''
    if args.protocol:
        for kind, filename in (('client-header', 'frame-pointer-protocol.h'), ('private-code', 'frame-pointer-protocol.c')):
            subprocess.run(['wayland-scanner', kind, str(args.protocol), str(home / filename)], check=True)
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True))
        subprocess.run(['cc', '-o', str(home / 'pointer'), '-I' + str(home), str(project / 'tests/frame_pointer.c'),
                        str(home / 'frame-pointer-protocol.c'), *flags], check=True)
        shutil.copy2(project / 'build/motion_probe.so', probe)
        ipc.call('plugin', 'load', str(probe)); probed = True
        # Only the fixtures' virtual keyboard: the parent's keyboard can keep a modifier held.
        extra = '''
hl.device({name="wl_keyboard",enabled=false})
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), {mouse=true})
'''
    config.write_text(original + extra + '''
hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=61})')
    state = ipc.status()
    assert state['card_cover'] is True and state['card_ungroup'] is True, state

    # Herdr's window and the card a workspace manager puts beside it.
    herdr = spawn('herdr')
    front, back = spawn('browser'), spawn('notes')
    ipc.focus(herdr)
    a = restore([front, back], herdr)
    made = card(a)
    assert made['cover'] is None and made['covered'] is False and made['faces'] == [[front], [back]], made
    assert active() == herdr and workspace() == 61
    passed('status reports card_cover, and a card with no cover reports cover null and covered false')

    # Refusals: each replies with a sentence and changes no card.
    lone = spawn('lone')
    ipc.focus(lone)
    six = restore([lone] + [spawn(f'six-{n}') for n in 'bcdef'], herdr)
    assert len(card(six)['faces']) == 6, card(six)
    assert 'already has 6 faces' in refused(f'card {six} cover {herdr}')
    assert still(f'card {six} ungroup', herdr) == 'ok: ok'
    for window in [lone] + [x for x in ipc.windows() if ipc.windows()[x]['class'].startswith('hyprflip-cover-six')]:
        close(window)
    # A cover takes the sixth face: a card with five faces of its own takes one, and then no new face.
    lone = spawn('lone')
    ipc.focus(lone)
    five = restore([lone] + [spawn(f'five-{n}') for n in 'bcde'], herdr)
    lid, spare = spawn('five-lid'), spawn('five-spare')
    assert still(f'card {five} cover {lid}', herdr) == 'ok: ok'
    c = card(five)
    assert len(c['faces']) == 5 and (c['cover'], c['covered']) == (lid, True) and len(c['names']) == 5, c
    assert 'already has 6 faces' in lua_refused((spare, 'mark'), (lid, 'attach face'))
    assert still(f'card {five} uncover', herdr) == 'ok: ok' and card(five)['cover'] is None
    assert still(f'card {five} ungroup', herdr) == 'ok: ok'
    for window in [lone] + [x for x in ipc.windows() if ipc.windows()[x]['class'].startswith('hyprflip-cover-five')]:
        close(window)
    chat, mail = spawn('chat'), spawn('mail')
    ipc.focused((chat, 'mark'), (mail, 'pair'))
    pair = next(p for p in ipc.status()['pairs'] if p['front'] == chat)['id']
    assert 'multi-app card' in refused(f'card {pair} cover {herdr}', herdr)
    assert 'already in a card, pair or group' in refused(f'card {a} cover {chat}', herdr)
    assert 'already in a card, pair or group' in refused(f'card {a} cover {front}', herdr)
    ipc.action(f'card {pair} ungroup')
    for window in (chat, mail): close(window)
    stray = spawn('stray')
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{stray}",workspace="62",follow=false}})')
    assert "card's workspace" in refused(f'card {a} cover {stray}', herdr)
    close(stray)
    for action in (f'card {a} cover', f'card {a} cover herdr', f'card {a} cover 0xzz', f'card {a} cover {herdr} now',
                   f'card 9999 cover {herdr}', f'card {a} cover 0x1', f'card {a} uncover now'):
        refused(action, herdr)
    assert refused(f'card {a} cover 0x1').startswith('No window has address 0x1')
    ipc.focus(herdr)
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    wait(lambda: ipc.windows()[herdr]['fullscreen'])
    assert 'Leave fullscreen before covering a card with that window' in refused(f'card {a} cover {herdr}')
    ipc.call('dispatch', 'hl.dsp.window.fullscreen({mode="fullscreen"})')
    wait(lambda: not ipc.windows()[herdr]['fullscreen'])
    ipc.focused((front, 'fullscreen'))
    wait(lambda: card(a)['fullscreen'])
    assert 'Leave fullscreen before covering the card' in refused(f'card {a} cover {herdr}')
    ipc.focused((front, 'fullscreen'))
    wait(lambda: not card(a)['fullscreen'])
    ipc.focused((front, 'unfold'))
    wait(lambda: card(a)['unfolded'])
    assert 'Fold the card' in refused(f'card {a} cover {herdr}')
    ipc.focused((front, 'unfold'))
    wait(lambda: not card(a)['unfolded'])
    # A popup menu's grab is input in progress.
    popup = spawn('popup', gtk=True)
    ipc.focus(popup)
    (home / 'popup.control').write_text('popup')
    time.sleep(.5)
    assert refused(f'card {a} cover {herdr}').startswith('Finish the active')
    (home / 'popup.control').write_text('dismiss')
    time.sleep(.3)
    close(popup)
    ipc.focus(herdr)
    before = card(a)
    assert still(f'card {a} uncover', herdr) == 'ok: ok' and card(a) == before
    passed('a card with five faces of its own takes a cover, which then counts as its sixth face; cover refuses a '
           'pair, a card of six faces, a window in a card or pair, on another workspace or '
           'fullscreen, a fullscreen or unfolded card, malformed input and a popup grab ("Finish the active"), '
           'changing no card; uncover with no cover replies ok and changes nothing')

    # Covered from the keyboard's own window: Herdr's tile closes and the card takes its place.
    ipc.focus(herdr)
    own, beside = tile(herdr), card(a)['box']
    assert still(f'card {a} cover {herdr}', herdr) == 'ok: ok'
    c = card(a)
    assert (c['cover'], c['covered'], c['faces'], c['active'], c['current']) == (herdr, True, [[front], [back]], 0, front), c
    assert len(c['names']) == 2 and [l['focused'] for l in c['layouts']] == [front, back], c
    assert active() == herdr and workspace() == 61
    windows = ipc.windows()
    assert sorted(windows[herdr]['grouped']) == sorted([herdr, front, back]), windows[herdr]
    visible(a, herdr)
    assert inside(own, c['box']) and inside(beside, c['box']) and inside(tile(herdr), c['box']), (own, beside, c['box'])
    assert all(win['workspace']['id'] != 61 or address in (herdr, front, back) for address, win in windows.items())
    frame = next((f for f in ipc.status()['card_frames'] if f['id'] == a), None)
    assert frame is None or frame['active'] == 0, frame
    assert 'already has a cover' in refused(f'card {a} cover {herdr}', herdr)
    passed('cover adds the window as a face of its own and shows it: status keeps the card\'s two faces, names and '
           'layouts, active is the face it showed and current that face\'s app, the cover keeps the keyboard, '
           'its tile closes and the card takes that place; a second cover is refused')

    # Face numbers count the card's own faces; the cover is reached by name or by turning.
    still(f'card {a} show 2', herdr)
    c = card(a)
    assert (c['covered'], c['active'], c['current']) == (False, 1, back) and active() == back, c
    visible(a, herdr)
    still(f'card {a} show cover', back)
    c = card(a)
    assert (c['covered'], c['active'], c['current']) == (True, 1, back) and active() == herdr, c
    visible(a, herdr)
    still(f'card {a} show front', herdr)
    assert (card(a)['covered'], card(a)['active']) == (False, 0)
    still(f'card {a} show cover', front)
    assert card(a)['covered'] and card(a)['active'] == 0
    assert 'from 1 to 2' in refused(f'card {a} show 3', herdr)
    assert 'from 1 to 2' in refused(f'card {a} name 3 Extra', herdr)
    assert still(f'card {a} name 2 Notes', herdr) == 'ok: ok' and card(a)['names'] == ['', 'Notes']
    ipc.action('face 2')
    assert (card(a)['covered'], card(a)['active']) == (False, 1) and active() == back
    ipc.action('face cover')
    assert card(a)['covered'] and card(a)['active'] == 1 and active() == herdr
    assert 'This card has 2 faces' in refused('face 3')
    ipc.action('face 1')
    assert (card(a)['covered'], card(a)['active']) == (False, 0) and active() == front
    ipc.call('eval', 'assert(hl.plugin.hyprflip.face("cover"))')
    assert card(a)['covered'] and active() == herdr
    seen = []
    for _ in range(3):
        still(f'card {a} flip', herdr if card(a)['covered'] else card(a)['current'])
        seen.append((card(a)['covered'], card(a)['active']))
    assert seen == [(False, 0), (False, 1), (True, 1)], seen
    passed('show and face count the card\'s own faces (show 3 and face 3 refused), show cover and face cover turn '
           'to the cover, a flip goes round every face with the cover last, and the keyboard follows the shown face')

    # Adding an app to the cover's face is refused; as a new face, or on another face, it is not.
    extra = spawn('extra')
    assert COVER_FACE in lua_refused((extra, 'mark'), (herdr, 'attach horizontal'))
    ipc.focused((extra, 'mark'), (back, 'attach horizontal'))
    assert card(a)['faces'] == [[front], [back, extra]] and card(a)['cover'] == herdr, card(a)
    ipc.focused((extra, 'other_side'))
    c = card(a)
    assert c['faces'] == [[front, extra], [back]] and (c['covered'], c['active'], c['cover']) == (False, 0, herdr), c
    ipc.focused((extra, 'release'))
    wait(lambda: card(a)['faces'] == [[front], [back]])
    ipc.focused((extra, 'mark'), (front, 'attach face'))
    c = card(a)
    assert c['faces'] == [[front], [back], [extra]] and (c['cover'], c['covered'], c['active']) == (herdr, False, 2), c
    still(f'card {a} show cover', extra)
    assert card(a)['covered'] and card(a)['active'] == 2
    still(f'card {a} show 3', herdr)
    assert card(a)['active'] == 2 and not card(a)['covered']
    ipc.focused((extra, 'release'))
    wait(lambda: card(a)['faces'] == [[front], [back]])
    close(extra)
    assert card(a)['cover'] == herdr
    passed('an app is refused on the cover\'s face, joins another face, moves to the next of the card\'s own faces '
           'past the cover, and is added as a new face after the cover')

    # Uncover: the cover leaves as an ordinary tile, and the card shows the face it showed before.
    still(f'card {a} show 2', front)
    still(f'card {a} show cover', back)
    ipc.focus(herdr)
    covered_box = card(a)['box']
    assert still(f'card {a} uncover', herdr) == 'ok: ok'
    c = card(a)
    assert (c['cover'], c['covered'], c['faces'], c['active'], c['current']) == (None, False, [[front], [back]], 1, back), c
    loose(herdr, '61')
    assert active() == herdr and apart(tile(herdr), c['box']), (tile(herdr), c['box'])
    assert inside(tile(herdr), covered_box) and inside(c['box'], covered_box)
    visible(a)
    assert still(f'card {a} uncover', herdr) == 'ok: ok' and card(a) == c
    passed('uncover takes the cover out as a tile of its own beside the card, which shows the face it showed before; '
           'the keyboard stays on the cover; a second uncover changes nothing')

    # The keyboard: from a card app the cover takes it; from elsewhere it stays, without passing through the cover.
    ipc.focus(front)
    still(f'card {a} cover {herdr}', front)
    assert active() == herdr and card(a)['covered']
    still(f'card {a} uncover', herdr)
    term = spawn('term')
    ipc.focus(term)
    keyboard = Keyboard()
    time.sleep(.2)
    assert still(f'card {a} cover {herdr}', term) == 'ok: ok'
    time.sleep(.2)
    assert active() == term and card(a)['covered'] and card(a)['cover'] == herdr
    assert herdr not in keyboard.moves and term not in keyboard.moves, keyboard.moves
    ipc.focus(herdr)
    wait(lambda: herdr in keyboard.moves)
    ipc.focus(term)
    passed('the cover takes the keyboard from a card app; from a window outside the card the keyboard stays, '
           'and never passes through the cover')

    # An ordinary workspace takes the cover along; a special one never does.
    still(f'card {a} workspace 62 silent', term)
    windows = ipc.windows()
    assert card(a)['cover'] == herdr and windows[herdr]['workspace']['id'] == 62 and card(a)['workspace']['id'] == 62
    assert active() == term and workspace() == 61
    still(f'card {a} workspace 61 silent', term)
    assert card(a)['cover'] == herdr and card(a)['covered'] and ipc.windows()[herdr]['workspace']['id'] == 61
    close(term)
    ipc.focus(herdr)
    full = card(a)['box']
    assert still(f'card {a} workspace special:park silent', herdr) == 'ok: ok'
    c = card(a)
    assert c['workspace']['name'] == 'special:park' and c['cover'] is None and not c['covered'], c
    assert c['faces'] == [[front], [back]]
    loose(herdr, '61')
    assert active() == herdr and workspace() == 61
    assert inside(tile(herdr), full), (tile(herdr), full)
    passed('a covered card moved to another numbered workspace takes its cover along; parked on a special '
           'workspace it leaves the cover as a tile where it was, with the keyboard')

    # One batch, as a workspace manager switches cards behind Herdr: park the covered card, bring the
    # next one beside Herdr and cover it. It ends filling the tile and showing Herdr.
    b1, b2 = spawn('browser-b'), spawn('notes-b')
    ipc.focus(herdr)
    b = restore([b1, b2], herdr)
    still(f'card {b} workspace special:park silent', herdr)
    still(f'card {a} workspace 61 silent', herdr)
    still(f'card {a} cover {herdr}', herdr)
    full = card(a)['box']
    pane = tile(herdr)
    before = rest(herdr)
    replies = ipc.batch([f'hyprflip card {a} workspace special:park silent', f'hyprflip card {b} workspace 61 silent',
                         f'hyprflip card {b} cover {herdr}'])
    time.sleep(.1)
    assert replies == ['ok: ok'] * 3, replies
    assert pointer() == before, (before, pointer())
    cb, ca = card(b), card(a)
    assert (cb['cover'], cb['covered'], cb['faces'], cb['active']) == (herdr, True, [[b1], [b2]], 0), cb
    assert same(cb['box'], full) and same(tile(herdr), pane), (cb['box'], full, tile(herdr), pane)
    assert ca['workspace']['name'] == 'special:park' and ca['cover'] is None, ca
    assert active() == herdr and workspace() == 61
    visible(b, herdr)
    passed('one batch parks a covered card, brings the next beside the cover and covers it: every reply is ok, '
           'the new card fills the tile showing the cover, and the keyboard and the pointer stay')

    # A real drag onto the cover's face: its target refuses, says why, and the drop changes nothing.
    if args.protocol:
        outsider = spawn('outsider')
        ipc.focus(outsider)
        ipc.call('dispatch', 'hl.dsp.window.float({action="float"})')
        ipc.call('dispatch', 'hl.dsp.window.resize({x=360,y=240,exact=true})')
        wait(lambda: same(card(b)['box'], full))
        before = card(b)
        if notify_log:
            notify_log.write_text('')
            ipc.call('eval', 'hl.config({plugin={hyprflip={notifications=true}}})')
        drag(outsider)
        wait(lambda: ipc.status()['drop_targets'])
        targets = ipc.status()['drop_targets']
        assert [(t['id'], t['side'], t['allowed']) for t in targets] == [(b, None, False)], targets
        x, y, width, height = targets[0]['zone']
        for _ in range(3):
            at = ipc.data('-j', 'cursorpos')
            send(f'move {x + width / 2 - at["x"]} {y + height / 2 - at["y"]}')
            time.sleep(.06)
        wait(lambda: any(t['hovered'] for t in ipc.status()['drop_targets']))
        drop()
        assert card(b) == before and ipc.windows()[outsider]['floating'] and not ipc.windows()[outsider]['grouped']
        if notify_log:
            wait(lambda: "cover" in notify_log.read_text())
            assert COVER_FACE in notify_log.read_text(), notify_log.read_text()
            ipc.call('eval', 'hl.config({plugin={hyprflip={notifications=false}}})')
        close(outsider)
        ipc.focus(herdr)
        passed('dragging an app over a covered card offers only the cover\'s face, refused (side null in status), '
               'and dropping it there changes nothing' + (' and says why' if notify_log else ''))

    # Saving the covered card through the helper keeps only its own faces.
    store = home / 'caller/cards.json'
    request = {'protocol': 1, 'action': 'save', 'store': str(store), 'name': 'Covered', 'card': b,
               'members': [b1, b2], 'previous': None}
    result = subprocess.run([sys.executable, str(project / 'scripts/control.py'), 'unattended', '--request',
                             json.dumps(request)], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=60)
    reply = json.loads(result.stdout)
    assert result.returncode == 0 and reply['ok'] and reply['result'] == 'saved', (result.returncode, reply, result.stderr)
    saved = w.RecipeStore(path=str(store), titles=False).read()['Covered']
    windows = ipc.windows()
    assert [[app['class'] for app in face['apps']] for face in saved['faces']] == [[windows[b1]['class']],
                                                                                [windows[b2]['class']]], saved
    assert saved['active'] == 0 and card(b)['cover'] == herdr and card(b)['covered'], saved
    request['members'] = [b1, b2, herdr]
    result = subprocess.run([sys.executable, str(project / 'scripts/control.py'), 'unattended', '--request',
                             json.dumps(request | {'name': 'With cover'})], env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60)
    assert json.loads(result.stdout)['code'] == 'changed', result.stdout
    passed('control.py unattended save of a covered card saves only its own two faces; the cover is not a member')

    # With animations: turns into and out of the cover, the face switcher, and an uncover, a park or a
    # close in the middle of a turn.
    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=300}}})')
    def settled(): wait(lambda: not ipc.status()['animating'])
    ipc.focus(herdr)
    ipc.action(f'card {b} flip')
    assert ipc.status()['animating']
    settled()
    assert ipc.status()['last_fallback'] == '', ipc.status()['last_fallback']
    assert (card(b)['covered'], card(b)['active']) == (False, 0) and active() == b1
    ipc.action('face cover')
    assert ipc.status()['animating']
    settled()
    assert card(b)['covered'] and active() == herdr and ipc.status()['last_fallback'] == ''
    ipc.action('switcher open')
    assert ipc.status()['switcher']['open'] and ipc.status()['switcher']['faces'] == 3, ipc.status()['switcher']
    ipc.action('switcher pick 2')
    settled()
    assert (card(b)['covered'], card(b)['active']) == (False, 1) and active() == b2
    ipc.action('switcher open')
    ipc.action('switcher pick 3')
    settled()
    assert card(b)['covered'] and active() == herdr
    ipc.action(f'card {b} flip')
    assert ipc.status()['animating']
    assert ipc.action(f'card {b} uncover') == 'ok: ok'
    assert not ipc.status()['animating'] and card(b)['cover'] is None
    loose(herdr, '61')
    visible(b)
    ipc.focus(herdr)
    still(f'card {b} cover {herdr}', herdr)
    ipc.action(f'card {b} flip')
    assert ipc.status()['animating']
    assert ipc.action(f'card {b} workspace special:park silent') == 'ok: ok'
    assert card(b)['workspace']['name'] == 'special:park' and card(b)['cover'] is None
    loose(herdr, '61')
    still(f'card {b} workspace 61 silent', herdr)
    closer = spawn('closer')
    still(f'card {b} cover {closer}', closer)
    ipc.action(f'card {b} flip')
    assert ipc.status()['animating']
    close(closer)
    wait(lambda: card(b)['cover'] is None and not ipc.status()['animating'])
    assert card(b)['faces'] == [[b1], [b2]]
    visible(b)
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0}}})')
    ipc.focus(herdr)
    still(f'card {b} cover {herdr}', herdr)
    passed('with animations, a covered card turns to and from its cover by flip, face cover and the face switcher; '
           'an uncover, a park or the cover closing in the middle of a turn ends it and leaves the cover outside')

    # The cover leaves on its own: released by the user, closed, or with the card coming apart.
    ipc.focused((herdr, 'release'))
    c = card(b)
    assert (c['cover'], c['covered'], c['faces']) == (None, False, [[b1], [b2]]), c
    loose(herdr, '61')
    closer = spawn('closer')
    still(f'card {b} show 2', herdr)
    still(f'card {b} cover {closer}', herdr)
    assert card(b)['covered'] and card(b)['cover'] == closer
    close(closer)
    wait(lambda: card(b)['cover'] is None)
    c = card(b)
    assert (c['covered'], c['faces'], c['active']) == (False, [[b1], [b2]], 1), c
    visible(b)
    still(f'card {b} cover {herdr}', herdr)
    ipc.focused((b2, 'release'))
    wait(lambda: gone(b))
    for window in (b1, b2, herdr): loose(window, '61')
    passed('a cover released by the user or closed leaves the card with no cover, showing the face it showed; '
           'releasing the last app of one of the card\'s two own faces takes the card apart as it does without one')

    # A face of a covered card that closes with its last app takes only that face while the card keeps two faces with
    # its cover: a program's window over one browser stays a card, and turning goes on between them. Without a cover a
    # face's last app closing still takes the card apart.
    ipc.focus(herdr)
    third = spawn('third')
    loose(third, '61')
    b = restore([b1, b2, third], herdr)
    still(f'card {b} cover {herdr}', herdr)
    assert card(b)['faces'] == [[b1], [b2], [third]] and card(b)['covered'], card(b)
    close(third)
    wait(lambda: not gone(b) and card(b)['faces'] == [[b1], [b2]])
    c = card(b)
    assert (c['cover'], c['covered']) == (herdr, True), c
    visible(b, herdr)
    still(f'card {b} show 2', herdr)
    assert not card(b)['covered'] and card(b)['active'] == 1, card(b)
    close(b2)
    wait(lambda: not gone(b) and card(b)['faces'] == [[b1]])
    c = card(b)
    assert (c['cover'], c['covered']) == (herdr, True), c
    visible(b, herdr)
    ipc.action(f'card {b} flip')
    wait(lambda: not card(b)['covered'] and not ipc.status()['animating'])
    assert card(b)['active'] == 0, card(b)
    visible(b, herdr)
    ipc.action(f'card {b} flip')
    wait(lambda: card(b)['covered'] and not ipc.status()['animating'])
    visible(b, herdr)
    # Parked, a card of one face of its own comes apart (a card keeps two faces): its app goes out of sight as an
    # ordinary window and the cover stays where the card was, with the keyboard.
    assert ipc.action(f'card {b} workspace special:park silent') == 'ok: ok'
    wait(lambda: gone(b))
    loose(herdr, '61')
    loose(b1, 'special:park')
    assert active() == herdr, active()
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{b1}",workspace="61",follow=false}})')
    wait(lambda: ipc.windows()[b1]['workspace']['name'] == '61')
    b2 = spawn('back-again')
    for window in (b1, b2, herdr): loose(window, '61')
    lone = spawn('lone')
    b = restore([b1, b2, lone], herdr)
    assert card(b)['cover'] is None
    close(lone)
    wait(lambda: gone(b))
    for window in (b1, b2): loose(window, '61')
    passed('a face of a covered card that closes with its last app takes only its face while two faces stay with the '
           'cover, down to one of its own and the cover, which a flip still turns between and which parked comes '
           'apart, its app out of sight and the cover in place; a card with no cover still comes apart when a face\'s '
           'last app closes')

    # Ungroup and unload leave a cover as an ordinary window, like any app.
    ipc.focus(herdr)
    b = restore([b1, b2], herdr)
    still(f'card {b} cover {herdr}', herdr)
    assert still(f'card {b} ungroup', herdr) == 'ok: ok' and gone(b)
    for window in (b1, b2, herdr): loose(window, '61')
    b = restore([b1, b2], herdr)
    still(f'card {b} cover {herdr}', herdr)
    assert not ipc.call('configerrors')
    ipc.call('plugin', 'unload', str(library)); loaded = False
    windows = ipc.windows()
    for window in (b1, b2, herdr):
        assert windows[window]['acceptsInput'] and not windows[window]['grouped'], windows[window]
    passed('ungroup and unload leave a covered card\'s apps and its cover as ordinary windows')
finally:
    for process in [mouse, held, *processes.values()]:
        if process and process.poll() is None: process.terminate()
    if probed:
        try: ipc.call('plugin', 'unload', str(probe))
        except Exception: pass
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    (root / 'cover-results.json').write_text(json.dumps(checks, indent=2))
