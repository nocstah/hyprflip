#!/usr/bin/env python3
"""Cards another program opens and saves through `control.py unattended`, with nobody at a
menu: from a disposable store beside a working tile, from apps parked on a special
workspace, with an app it launches, an app its caller owns and a restore the core refuses.
No request may keep the keyboard, change the workspace, move the pointer or notify the
desktop. Only the Hyprflip core is loaded (native dwindle cards), with notifications on;
start the session with --notify-recorder."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from control import environment

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
# Whatever this suite starts, the helper included, finds the recorder's
# notify-send first, and no session bus or X display that leads to the
# user's desktop.
notify_log, home = Path(env.pop('notify_log')), root / 'unattended'
path, recorder = env.get('PATH', os.defpath), str(notify_log.parent / 'bin')
for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'DESKTOP_STARTUP_ID', 'XDG_ACTIVATION_TOKEN'):
    env.pop(key, None)
env.update(PATH=os.pathsep.join([recorder, path]), XDG_STATE_HOME=str(root / 'state'),
           XDG_DATA_HOME=str(home / 'data'), XDG_DATA_DIRS=str(home / 'share'))
# The program that calls the helper, with a hyprctl that records its arguments.
caller = env | {'PATH': os.pathsep.join([recorder, str(home / 'tools'), path])}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
# The apps this suite opens, by window, and the pids of those the helper launched.
processes, started, checks, replies = {}, [], [], []
library_so = root / 'unattended-hyprflip.so'
loaded, output = False, None
# Every window's title starts with this. It must never leave Hyprland.
SENTINEL = 'hf-title-sentinel'
store, library = home / 'caller/cards.json', root / 'state/hyprflip/cards.json'
calls_log, marker = home / 'hyprctl.log', home / 'owned-launched'


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
    """A terminal on the shown workspace, standing in for an app."""
    app = 'hyprflip-unattended-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', f'{SENTINEL}-{name}', 'cat']
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    address = next(a for a, win in ipc.windows().items() if win['class'] == app)
    processes[address] = process
    return address


def close(address):
    processes.pop(address).terminate()
    wait(lambda: address not in ipc.windows())


def show(number): ipc.call('dispatch', f'hl.dsp.focus({{workspace={number}}})')
def active(): return ipc.data('-j', 'activewindow').get('address')
def workspace(): return ipc.data('-j', 'activeworkspace')['id']
def card(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)
def tile(address): return [*ipc.windows()[address]['at'], *ipc.windows()[address]['size']]


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


def visible(id):
    c, windows = card(id), ipc.windows()
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (c['unfolded'] or side == c['active']), (c, windows[address])


def calls():
    """The arguments of each hyprctl call the helper made, in order."""
    text = calls_log.read_text() if calls_log.exists() else ''
    return [record.split('\037')[:-1] for record in text.split('\036')[:-1]]


def changes(sent):
    """The calls that could change something: anything but reading and the plugin's status or leases."""
    return [c for c in sent if c[0] != '-j' and c[:2] != ['hyprflip', 'status'] and
            not (c[0] == 'hyprflip' and c[1].split(' ')[0] in ('reserve', 'unreserve'))]


def notes(): return [json.loads(line) for line in notify_log.read_text().splitlines()]


def app(name, label):
    """A slot of a definition, as a caller keeps it: no title."""
    return {'class': 'hyprflip-unattended-' + name, 'initial_class': 'hyprflip-unattended-' + name,
            'title': '', 'label': label}


def definition(front, back):
    return {'active': 0, 'faces': [{'apps': apps, 'axis': 'horizontal', 'ratios': [1 / len(apps)] * len(apps),
                                    'focus': 0} for apps in (front, back)]}


def launcher(path, **fields):
    path.write_text('[Desktop Entry]\nType=Application\n' + ''.join(f'{key}={value}\n' for key, value in fields.items()))


def helper(request, over=None):
    """One request through `control.py unattended`, as another program sends it.

    One JSON line comes back, with nothing on stderr and an exit code that agrees
    with it. When the pointer rests over a tile, it stays there. Returns the reply
    and the hyprctl calls the helper made.
    """
    before = rest(over) if over else None
    mark = len(calls())
    result = subprocess.run([sys.executable, str(project / 'scripts/control.py'), 'unattended',
                             '--request', json.dumps({'protocol': 1, **request})],
                            env=caller, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
    assert len(result.stdout.splitlines()) == 1 and not result.stderr, (result.returncode, result.stdout, result.stderr)
    reply = json.loads(result.stdout)
    assert reply['protocol'] == 1 and result.returncode == (0 if reply['ok'] else 1), (result.returncode, reply)
    replies.append(result.stdout)
    if over:
        time.sleep(.1)
        print('pointer', before, pointer(), request['action'], flush=True)
        assert pointer() == before, (request['action'], before, pointer())
    return reply, calls()[mark:]


def library_state():
    """What any write to the library would change: its content, its time and its folder."""
    return library.read_bytes(), library.stat().st_mtime_ns, sorted(p.name for p in library.parent.iterdir())


class Keyboard:
    """When Hyprland's event socket said the keyboard moved, and to which window."""
    def __init__(self):
        self.moves = []
        events = Path(env['XDG_RUNTIME_DIR']) / 'hypr' / env['HYPRLAND_INSTANCE_SIGNATURE'] / '.socket2.sock'
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.connect(str(events))
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        pending = b''
        while chunk := self.connection.recv(65536):
            when = time.monotonic()
            *lines, pending = (pending + chunk).split(b'\n')
            # Only addresses are kept: other events carry window titles.
            self.moves += [(when, '0x' + line[16:].decode()) for line in lines if line.startswith(b'activewindowv2>>')]


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    # The caller's own files: a private folder for its store, its launchers,
    # and a hyprctl that records each call before it runs the real one.
    for folder in (home, library.parent): shutil.rmtree(folder, ignore_errors=True)
    for folder in ('caller', 'tools', 'data/applications', 'share/applications'):
        (home / folder).mkdir(mode=0o700, parents=True)
    real, log = shlex.quote(shutil.which('hyprctl', path=path)), shlex.quote(str(calls_log))
    (home / 'tools/hyprctl').write_text(f'#!/bin/sh\nprintf "%s\\037" "$@" >> {log}\nprintf "\\036" >> {log}\n'
                                        f'exec {real} "$@"\n')
    (home / 'tools/hyprctl').chmod(0o700)
    launcher(home / 'data/applications/notes-c.desktop', Name='Notes', NoDisplay='true',
             StartupWMClass='hyprflip-unattended-c',
             Exec=f'foot --config /dev/null --app-id hyprflip-unattended-c --title {SENTINEL}-c cat')
    launcher(home / 'share/applications/owned-tool.desktop', Name='Owned Tool', StartupWMClass='hyprflip-unattended-owned',
             Exec=f'touch {marker}')
    keeper = w.RecipeStore(path=str(store), titles=False)
    # The menus' library, with a title as they keep it. The helper never touches it.
    kept = definition([app('library-a', 'Library A')], [app('library-b', 'Library B')])
    kept['faces'][0]['apps'][0]['title'] = 'Kept by the menus'
    w.RecipeStore(env).change({'Library': None}, {'Library': kept})

    shutil.copy2(project / 'build/hyprflip.so', library_so)
    ipc.call('plugin', 'load', str(library_so)); loaded = True
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + f'''
hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})
''' + ''.join(f'hl.workspace_rule({{workspace="{n}",monitor="{output}"}})\n' for n in range(81, 86)) + '''
hl.config({general={gaps_in=14,gaps_out=24},animations={enabled=false},
    plugin={hyprflip={duration_ms=0,notifications=true}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    show(81)
    assert [p['name'] for p in ipc.data('-j', 'plugin', 'list')] == ['hyprflip']
    keyboard, baseline = Keyboard(), len(notes())
    reply, _ = helper({'action': 'capabilities'})
    assert reply == {'protocol': 1, 'ok': True, 'result': 'capabilities', 'actions': ['capabilities', 'list', 'delete', 'open', 'save'],
                     'core': True, 'max_panes': ipc.status()['container_max_panes']}, reply
    passed('the helper finds a core with native cards and ungroup by id')

    # The tile someone works in, as Herdr is.
    herdr = spawn('herdr')
    full = tile(herdr)
    assert ipc.windows()[herdr]['title'].startswith(SENTINEL)
    other = spawn('other')
    # Positive control: a focus dispatch warps the pointer to the middle of its
    # window, even of the one that has the keyboard already.
    ipc.focus(herdr)
    rest(herdr)
    ipc.focus(herdr)
    x, y, width, height = tile(herdr)
    centre = pointer()
    assert abs(centre[0] - (x + width / 2)) <= 1 and abs(centre[1] - (y + height / 2)) <= 1, (centre, tile(herdr))
    passed('a focus dispatch warps the pointer to the centre of the window it focuses, even one already focused')
    flow = w.Unattended(w.Hyprctl(caller), None)
    ipc.focus(other)
    warps = ipc.data('-j', 'getoption', 'cursor:no_warps')['bool']
    before, mark = rest(herdr), len(calls())
    assert flow.give_back(herdr) and active() == herdr
    time.sleep(.1)
    sent = calls()[mark:]
    assert changes(sent) == [['dispatch', w.Unattended.focus_command(herdr)]], sent
    assert pointer() == before and ipc.data('-j', 'getoption', 'cursor:no_warps')['bool'] == warps, (pointer(), before)
    mark = len(calls())
    assert flow.give_back(herdr) and calls()[mark:] == [['-j', 'activewindow']] and pointer() == before
    close(other)
    assert tile(herdr) == full
    passed('give_back sends one focus that leaves the pointer and cursor:no_warps as they were, '
           'and nothing to the window that has the keyboard')

    # 1. A stored definition, opened beside the working tile: its front app is
    # already there, and its back app comes from another workspace.
    show(84)
    browser, notes_app = spawn('browser'), spawn('notes')
    ipc.move(browser, 81); ipc.move(notes_app, 82)
    show(81); ipc.focus(herdr)
    keeper.change({'Beside': None}, {'Beside': definition([app('browser', 'Browser')], [app('notes', 'Notes')])})
    beside = tile(herdr)
    assert beside != full
    reply, sent = helper({'action': 'open', 'store': str(store), 'name': 'Beside', 'workspace': 81,
                          'bind': [browser, notes_app], 'focus': herdr}, herdr)
    assert reply['ok'] and reply['result'] == 'opened', reply
    first = reply['card']
    made = card(first)
    assert made['faces'] == [[browser], [notes_app]] and made['native_group'], made
    assert made['workspace'] == {'id': 81, 'name': '81', 'special': False} == reply['workspace'], (made, reply)
    assert active() == herdr and workspace() == 81 and tile(herdr) == beside, (active(), workspace(), tile(herdr), beside)
    assert [c[0] for c in sent].count('--batch') == 1 and changes(sent) == [c for c in sent if c[0] == '--batch'], sent
    batch = next(c[1] for c in sent if c[0] == '--batch')
    assert batch.count('follow=false') == 1 and ' ; hyprflip restore quiet tiled ' in batch, batch
    assert reply['token'] == w.Unattended.token(keeper.read()['Beside']), reply
    assert (reply['launched'], reply['unused'], reply['focus_returned']) == ([], [], True), reply
    visible(first)
    passed('a stored card opens beside the working tile in one batch: the keyboard, the workspace, '
           'the working tile and the pointer stay as they were')

    # 2. Apps waiting on a special workspace, as card mode parks them.
    ipc.action(f'card {first} workspace special:park silent')
    assert card(first)['workspace']['name'] == 'special:park' and tile(herdr) == full
    show(84)
    mail, chat = spawn('mail'), spawn('chat')
    for address in (mail, chat): ipc.move(address, 'special:park')
    show(81); ipc.focus(herdr)
    reply, sent = helper({'action': 'open', 'recipe': definition([app('mail', 'Mail')], [app('chat', 'Chat')]),
                          'workspace': 81, 'bind': [mail, chat], 'focus': herdr, 'launch': False}, herdr)
    assert reply['ok'] and reply['result'] == 'opened' and reply['token'] is None, reply
    second = reply['card']
    assert card(second)['faces'] == [[mail], [chat]] and card(second)['workspace']['id'] == 81, card(second)
    monitor = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    assert active() == herdr and workspace() == 81 and not monitor['specialWorkspace']['id'], monitor
    assert changes(sent) == [c for c in sent if c[0] == '--batch'] and len(changes(sent)) == 1, sent
    assert changes(sent)[0][1].count('follow=false') == 2, sent
    visible(second)
    ipc.action(f'card {second} workspace special:park silent')
    passed('bound apps parked on a special workspace join the card silently: the special workspace stays hidden, '
           'and the keyboard and the pointer stay')

    # 3. An app that is not open, launched from a launcher nobody sees in a
    # menu. It takes the keyboard as it maps; the keyboard comes straight back.
    show(84)
    viewer = spawn('viewer')
    ipc.move(viewer, 81)
    show(81); ipc.focus(herdr)
    keeper.change({'Launch': None}, {'Launch': definition([app('viewer', 'Viewer')], [app('c', 'Notes')])})
    assert not any(win['class'] == 'hyprflip-unattended-c' for win in ipc.windows().values())
    mark = len(keyboard.moves)
    reply, sent = helper({'action': 'open', 'store': str(store), 'name': 'Launch', 'workspace': 81, 'bind': [viewer],
                          'focus': herdr}, herdr)
    assert reply['ok'] and reply['result'] == 'opened', reply
    assert [(a['desktop_id'], a['wm_class']) for a in reply['launched']] == [('notes-c.desktop', 'hyprflip-unattended-c')], reply
    fresh, third = reply['launched'][0]['address'], reply['card']
    assert card(third)['faces'] == [[viewer], [fresh]] and ipc.windows()[fresh]['class'] == 'hyprflip-unattended-c'
    moves = keyboard.moves[mark:]
    took = next((i for i, (_, address) in enumerate(moves) if address == fresh), None)
    assert took is not None, 'The launched app never took the keyboard, so nothing was given back'
    back = next(i for i in range(took + 1, len(moves)) if moves[i][1] == herdr)
    print('keyboard back after', round((moves[back][0] - moves[took][0]) * 1000), 'ms', flush=True)
    assert moves[back][0] - moves[took][0] <= .3, moves
    assert active() == herdr and workspace() == 81 and reply['focus_returned'] is True, reply
    assert [c for c in changes(sent) if c[0] != '--batch'] == [['dispatch', w.Unattended.focus_command(herdr)]], sent
    # The launched app runs in the nested session, never on the user's desktop.
    pid = ipc.windows()[fresh]['pid']
    started.append(pid)
    environ = dict(entry.split('=', 1) for entry in Path(f'/proc/{pid}/environ').read_text(errors='replace').split('\0')
                   if '=' in entry)
    assert (environ.get('WAYLAND_DISPLAY'), environ.get('XDG_RUNTIME_DIR')) == (env['WAYLAND_DISPLAY'], env['XDG_RUNTIME_DIR'])
    assert not {'DBUS_SESSION_BUS_ADDRESS', 'DISPLAY'} & set(environ)
    stored = keeper.read()['Launch']
    assert stored['faces'][1]['apps'][0]['desktop_id'] == 'notes-c.desktop' and reply['remembered'] is True, stored
    visible(third)
    ipc.action(f'card {third} workspace special:park silent')
    passed('a missing app starts from a hidden launcher matched by its window class, inside the nested session; '
           'the keyboard is back on the working tile within 300 ms and the pointer never moves')

    # 4. A slot whose app the caller opens itself.
    show(84)
    reader, player, spare = spawn('reader'), spawn('player'), spawn('spare')
    ipc.move(reader, 82); ipc.move(player, 'special:park')
    show(81); ipc.focus(herdr)
    owned = app('owned', 'Owned Tool')
    # Positive control: its launcher matches by class as well as by name.
    assert w.DesktopApps(caller).infer(owned, by_label=False).id == 'owned-tool.desktop'
    reply, sent = helper({'action': 'open', 'recipe': definition([app('reader', 'Reader')], [app('player', 'Player'), owned]),
                          'workspace': 81, 'bind': [reader, player, spare], 'owned': [owned['class']], 'focus': herdr}, herdr)
    assert reply['ok'] and reply['result'] == 'opened', reply
    fourth, slot = reply['card'], reply['slots'][1][1]
    assert card(fourth)['faces'] == [[reader], [player]], card(fourth)
    assert (slot['class'], slot['address'], slot['missing']) == (owned['class'], None, 'owned'), slot
    assert (reply['launched'], reply['unused']) == ([], [spare]), reply
    time.sleep(.5)
    assert not marker.exists()
    assert ipc.windows()[spare]['workspace']['id'] == 84 and not ipc.windows()[spare]['grouped']
    assert active() == herdr and workspace() == 81
    ipc.action(f'card {fourth} workspace special:park silent')
    close(spare)
    passed('a slot the caller owns is never launched, though a launcher matches it; a bound app no slot wants stays where it was')

    # 5. A restore the core refuses, after the batch moved the apps in: one
    # from a special workspace, one tiled and one floating on another workspace.
    assert tile(herdr) == full
    show(84)
    left, right, floater = spawn('left'), spawn('right'), spawn('floater')
    ipc.move(left, 'special:park'); ipc.move(right, 83); ipc.move(floater, 83)
    ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{floater}",action="enable"}})')
    wait(lambda: ipc.windows()[floater]['floating'])
    # The front app needs a card taller than the screen, which the back app cannot
    # grow to, so the core refuses the card. Dwindle floats an app whose largest
    # size is below the tile it would get, so that limit is above the screen's.
    for address, limit, size in ((left, 'min_size', '1000 2400'), (right, 'max_size', '4000 2200')):
        ipc.call('dispatch', f'hl.dsp.window.set_prop({{window="address:{address}",prop="{limit}",value="{size}"}})')
    show(81); ipc.focus(herdr)
    def places(): return {a: (ipc.windows()[a]['workspace']['name'], ipc.windows()[a]['floating']) for a in (left, right, floater)}
    origins, spot = places(), tile(floater)
    cards = [(c['id'], c['faces']) for c in ipc.status()['containers']]
    reply, sent = helper({'action': 'open', 'recipe': definition([app('left', 'Left')], [app('right', 'Right'), app('floater', 'Floater')]),
                          'workspace': 81, 'bind': [left, right, floater], 'focus': herdr}, herdr)
    assert not reply['ok'] and reply['code'] == 'refused' and reply['launched'] == [], reply
    batch = next(c[1] for c in sent if c[0] == '--batch')
    assert batch.count('follow=false') == 3 and ' ; hyprflip restore quiet tiled ' in batch, batch
    assert places() == origins and origins[left] == ('special:park', False) and tile(floater) == spot, (places(), origins)
    assert [(c['id'], c['faces']) for c in ipc.status()['containers']] == cards
    assert active() == herdr and workspace() == 81 and tile(herdr) == full
    passed('a refused restore sends each imported app back where it was, a special workspace included, '
           'and floats again the one that floated')

    # 6. Saving a parked card by its id.
    state, parked = library_state(), card(first)
    assert parked['workspace']['name'] == 'special:park', parked
    request = {'action': 'save', 'store': str(store), 'name': 'Parked', 'card': first, 'members': [browser, notes_app]}
    reply, sent = helper(request | {'previous': None}, herdr)
    assert reply['ok'] and reply['result'] == 'saved' and reply['dropped'] == [], reply
    saved = keeper.read()['Parked']
    assert [[a['class'] for a in face['apps']] for face in saved['faces']] == [[ipc.windows()[browser]['class']],
                                                                             [ipc.windows()[notes_app]['class']]], saved
    assert all(a['title'] == '' for face in saved['faces'] for a in face['apps']) and SENTINEL not in store.read_text()
    assert (card(first)['faces'], card(first)['workspace']) == (parked['faces'], parked['workspace'])
    assert not changes(sent) and active() == herdr and workspace() == 81, sent
    written = store.stat().st_mtime_ns
    again, _ = helper(request | {'previous': reply['token']}, herdr)
    assert (again['result'], again['token'], store.stat().st_mtime_ns) == ('unchanged', reply['token'], written), again
    assert library_state() == state
    passed('saving a parked card by id keeps no title and leaves the card and the library alone; '
           'saving it again is unchanged')

    # 7. Positive controls: refusals of a Lua call and of a plain restore sent with
    # hyprctl are recorded. Refusals of calls by id and of quiet restores, complete
    # or bare, are not, and nor was anything the helper did.
    assert len(notes()) == baseline, notes()[baseline:]
    show(85)
    assert not active()
    try: ipc.call('eval', 'hl.plugin.hyprflip.flip()')
    except w.SetupError: pass
    wait(lambda: len(notes()) == baseline + 1, 4)
    assert '--app-name=Hyprflip' in notes()[-1] and '--icon=dialog-warning' in notes()[-1], notes()[-1]
    x, y, width, height = full
    for action in ('card 9999 flip', 'restore quiet', f'restore quiet tiled 0 0 {x} {y} {width} {height} '
                   'front horizontal 0x1 0x1:1 back horizontal 0x2 0x2:1'):
        try:
            raise AssertionError((action, ipc.action(action)))
        except w.SetupError:
            pass
    time.sleep(.5)
    assert len(notes()) == baseline + 1, notes()[baseline:]
    try:
        raise AssertionError(('restore', ipc.action('restore')))
    except w.SetupError:
        pass
    wait(lambda: len(notes()) == baseline + 2, 4)
    passed('refused Lua calls and plain restores notify; refused calls by id, refused quiet restores (bare or complete) '
           'and every helper request do not')

    # 8. Unloading the plugin, with one card shown and three parked.
    show(81)
    ipc.action(f'card {first} workspace 81 silent')
    members = [a for c in ipc.status()['containers'] for face in c['faces'] for a in face]
    assert sorted(c['id'] for c in ipc.status()['containers']) == sorted([first, second, third, fourth])
    assert not ipc.call('configerrors')
    ipc.call('plugin', 'unload', str(library_so)); loaded = False
    windows = ipc.windows()
    for address in members:
        assert windows[address]['acceptsInput'] and not windows[address]['grouped'], windows[address]
    passed('unloading releases every app of the cards the helper made, shown or parked')

    assert SENTINEL not in calls_log.read_text() + store.read_text() + ''.join(replies) + notify_log.read_text()
    passed('no window title reached the helper\'s hyprctl calls, its replies, its store or a notification')
finally:
    for process in processes.values():
        if process.poll() is None: process.terminate()
    for pid in started:
        try: os.kill(pid, signal.SIGTERM)
        except OSError: pass
    if loaded:
        try: ipc.call('plugin', 'unload', str(library_so))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    if output: ipc.call('output', 'remove', output)
    (root / 'unattended-results.json').write_text(json.dumps(checks, indent=2))
