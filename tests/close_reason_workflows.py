#!/usr/bin/env python3
"""Why an app closed: status's close_reasons and closes, against real closes in a
nested session. Keys bound in the session close (Super+F9, hl.dsp.window.close)
and kill (Super+F10, hl.dsp.window.kill) the focused window; wtype presses them.
Covers a key close, a close by hyprctl dispatch, an app exiting by itself, a kill
from outside, a key kill of one of two windows of one process, the cover, a card
that comes apart, a window in no card, the last face of a card at the core's
face limit, a class holding "Lua error" and quotes, and a plugin reload. With
--protocol (Hyprland's wlr-virtual-pointer-unstable-v1.xml) a click in
hyprctl kill's mode kills a card app too.

With --hooks-off, run it in a session whose Hyprland was started with
HYPRFLIP_CLOSE_HOOKS=0 in its environment: status says close_reasons false,
closes read unknown, and a click kill still reads killed."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--protocol', type=Path, help='wlr-virtual-pointer-unstable-v1.xml for the click kill')
parser.add_argument('--hooks-off', action='store_true',
                    help='the session runs with HYPRFLIP_CLOSE_HOOKS=0: check the reduced reasons')
args = parser.parse_args()
root = args.session.parent
home = root / 'closes'
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
env.pop('notify_log', None)
for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY'):
    env.pop(key, None)
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = {}, []
servers = []
library = root / 'close-hyprflip.so'
loaded = False
reads = 0


def wait(fn, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError(status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def status():
    """Every status read goes through the helper's own Hyprctl, which parses it as JSON."""
    global reads
    reply = ipc.status()
    reads += 1
    return reply


def spawn(name, exits=False, app=None):
    """A foot window. With exits it waits for <name>.exit to appear, then quits by itself."""
    app = app or 'hyprflip-close-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name, 'sh', '-c']
    if exits:
        command += ['printf "\\n  %s\\n" "$1"; while [ ! -e "$2" ]; do sleep .05; done', 'pane', name,
                    str(home / (name + '.exit'))]
    else:
        command += ['printf "\\n  %s\\n" "$1"; exec cat', 'pane', name]
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    address = next(a for a, win in ipc.windows().items() if win['class'] == app)
    processes[address] = process
    return address


def press(key):
    subprocess.run(['wtype', '-M', 'logo', '-k', key, '-m', 'logo'], env=env, check=True, timeout=5)


def card(id): return next(c for c in status()['containers'] if c['id'] == id)
def gone(id): return not any(c['id'] == id for c in status()['containers'])
def listed(address): return any(address in face for c in status()['containers'] for face in c['faces'])
def mark(): return status()['closes']['next']


def restore(faces):
    """A quiet restore of a tiled card whose faces hold these apps, on the first app's tile."""
    box = ipc.windows()[faces[0][0]]
    words = ['front', 'back'] + ['face'] * (len(faces) - 2)
    line = ' '.join(f'{word} horizontal {apps[0]} ' + ' '.join(f'{app}:{1 / len(apps):.3f}' for app in apps)
                    for word, apps in zip(words, faces))
    reply = ipc.action(f'restore quiet tiled 0 0 {box["at"][0]} {box["at"][1]} {box["size"][0]} {box["size"][1]} {line}')
    assert reply == 'ok: ok', reply
    id = next(c for c in status()['containers'] if faces[0][0] in c['faces'][0])['id']
    assert card(id)['faces'] == faces, card(id)
    return id


def records(since, count):
    """Waits for `count` records numbered from `since` and returns them, oldest first."""
    wait(lambda: mark() >= since + count)
    found = [r for r in status()['closes']['list'] if r['seq'] >= since]
    assert len(found) == count and [r['seq'] for r in found] == list(range(since, since + count)), found
    return found


def none_since(since):
    """No record arrives for a close: given time, `next` stays."""
    time.sleep(.5)
    assert mark() == since, status()['closes']


def about(record, address, client):
    """The record names the window as hyprctl clients did before it closed."""
    assert record['address'] == address and record['stable_id'] == client['stableId'], (record, client)
    assert record['initial_class'] == client['initialClass'], (record, client)
    space = client['workspace']
    assert record['workspace'] == {'id': space['id'], 'name': space['name'],
                                   'special': space['name'].startswith('special')}, (record, client)
    assert record['pid'] in (client['pid'], None) and (record['pid'] is None or record['pid'] > 0), (record, client)


def place(record, card_id, face, index, faces, cover=False, dissolved=False):
    got = tuple(record[k] for k in ('card', 'face', 'index', 'faces', 'cover', 'dissolved'))
    assert got == (card_id, face, index, faces, cover, dissolved), record


def why(record, reason, via=None):
    assert (record['reason'], record['via']) == (reason, via), record
    if via is None:
        assert record['asked_ms'] is None, record
    else:
        assert isinstance(record['asked_ms'], int) and 0 <= record['asked_ms'] < 5000, record


def close_key(address):
    """Super+F9 on the window: hl.dsp.window.close() from a key bind."""
    ipc.focus(address)
    press('F9')
    wait(lambda: address not in ipc.windows())


def close_gone(address):
    wait(lambda: address not in ipc.windows())
    processes.pop(address, None)


def click_kill(address):
    """hyprctl kill, then a virtual click on the window's middle."""
    win = ipc.windows()[address]
    x, y = (round(win['at'][i] + win['size'][i] / 2) for i in (0, 1))
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x},y={y}}})')
    assert ipc.call('kill') == 'ok'
    mouse = subprocess.Popen([str(home / 'pointer'), '--stream'], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    try:
        assert mouse.stdout.readline().strip() == 'ready'
        for command in ('down', 'up'):
            mouse.stdin.write(command + '\n'); mouse.stdin.flush()
            assert mouse.stdout.readline().strip() == 'ok'
        mouse.communicate('quit\n', timeout=3)
    finally:
        if mouse.poll() is None: mouse.kill()
    close_gone(address)


def flag(name): (home / (name + '.exit')).write_text('')


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(mode=0o700, parents=True)
    if args.protocol:
        for kind, filename in (('client-header', 'frame-pointer-protocol.h'), ('private-code', 'frame-pointer-protocol.c')):
            subprocess.run(['wayland-scanner', kind, str(args.protocol), str(home / filename)], check=True)
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True))
        subprocess.run(['cc', '-o', str(home / 'pointer'), '-I' + str(home), str(project / 'tests/frame_pointer.c'),
                        str(home / 'frame-pointer-protocol.c'), *flags], check=True)
    shutil.copy2(project / 'build/hyprflip.so', library)
    ipc.call('plugin', 'load', str(library)); loaded = True
    # Only the fixtures' virtual keyboard: the parent's keyboard can keep a modifier held. wtype sends
    # its own keymap, so binds resolve by key symbol.
    config.write_text(original + '''
hl.device({name="wl_keyboard",enabled=false})
hl.config({input={resolve_binds_by_sym=true}})
hl.bind("SUPER + F9", hl.dsp.window.close())
hl.bind("SUPER + F10", hl.dsp.window.kill())
hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=71})')

    state = status()
    closes = state['closes']
    hooked = not args.hooks_off
    assert state['close_reasons'] is hooked and closes['watch'] == {'close': hooked, 'kill': hooked}, closes
    assert re.fullmatch(r'[0-9a-f]{16}', closes['instance']), closes
    assert (closes['next'], closes['oldest'], closes['list']) == (1, 1, []), closes
    assert state['fullscreen_focus'] is True, 'the fullscreen hooks no longer install'
    first_instance = closes['instance']
    passed(f'at start close_reasons is {str(hooked).lower()} with a matching watch, a 16-digit instance, next 1, '
           'oldest 1 and no records; the fullscreen hooks, now found by their full names, still install')

    if args.hooks_off:
        k1, k2, k3, ex = spawn('k1'), spawn('k2'), spawn('k3'), spawn('ex', exits=True)
        c = restore([[k1, k2], [k3, ex]])
        clients = ipc.windows()
        start = mark()
        close_key(k2)
        [r] = records(start, 1)
        about(r, k2, clients[k2]); place(r, c, 0, 1, 2); why(r, 'unknown')
        ipc.action(f'card {c} show 2')
        flag('ex'); close_gone(ex)
        [r] = records(start + 1, 1)
        about(r, ex, clients[ex]); place(r, c, 1, 1, 2); why(r, 'unknown')
        loose = spawn('loose')
        start = mark()
        close_key(loose)
        none_since(start)
        passed('without hooks a key close and an app exiting by itself both read unknown with no via, and a key '
               'close of a window in no card leaves no record')
        if args.protocol:
            ipc.action(f'card {c} show 1')
            start = mark()
            click_kill(k1)
            [r] = records(start, 1)
            about(r, k1, clients[k1]); place(r, c, 0, 0, 2, dissolved=True); why(r, 'killed', 'click')
            assert gone(c)
            passed('without hooks a click in hyprctl kill\'s mode still reads killed by click, through Hyprland\'s '
                   'kill event')
    else:
        # A key close, a close by hyprctl dispatch, an app quitting by itself and a kill from outside, on one card.
        a1, a2, b1, b2 = spawn('a1'), spawn('a2'), spawn('b1'), spawn('b2')
        c1, ex = spawn('c1'), spawn('ex', exits=True)
        c = restore([[a1, a2], [b1, b2], [c1, ex]])
        clients = ipc.windows()
        ipc.action(f'card {c} show 2')
        start = mark()
        close_key(b2)
        [r] = records(start, 1)
        about(r, b2, clients[b2]); place(r, c, 1, 1, 3); why(r, 'requested', 'key')
        assert r['pid'] == clients[b2]['pid'], r
        assert card(c)['faces'] == [[a1, a2], [b1], [c1, ex]] and not listed(b2)
        passed('Super+F9 on an app on face 2 of a 3-face card reads requested by key: card, face 1, index 1, faces 3, '
               'not dissolved, asked within 5 s, its pid, initial class, stable id and workspace, and the app has left '
               'the card\'s faces')

        start = mark()
        ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{a2}"}})')
        close_gone(a2)
        [r] = records(start, 1)
        about(r, a2, clients[a2]); place(r, c, 0, 1, 3); why(r, 'requested', 'other')
        passed('hyprctl dispatch hl.dsp.window.close reads requested, via other')

        start = mark()
        flag('ex'); close_gone(ex)
        [r] = records(start, 1)
        about(r, ex, clients[ex]); place(r, c, 2, 1, 3); why(r, 'own')
        start = mark()
        os.kill(clients[c1]['pid'], signal.SIGKILL)
        close_gone(c1)
        [r] = records(start, 1)
        about(r, c1, clients[c1]); place(r, c, 2, 0, 3, dissolved=True); why(r, 'own')
        assert gone(c)
        passed('a card app that quits by itself, and one killed from outside Hyprland, read own with no via or '
               'time; the last app of a face going takes the card apart, and its record says dissolved with the '
               'face it had')

        # A window in no card: only a request leaves a record.
        start = mark()
        processes[a1].terminate(); close_gone(a1)
        none_since(start)
        close_key(b1)
        [r] = records(start, 1)
        about(r, b1, clients[b1]); place(r, None, None, None, None); why(r, 'requested', 'key')
        passed('a window in no card leaves no record when it quits by itself, and a record with card null when '
               'closed by key')

        # One process, two windows: a key kill of one reads killed; the other goes along and reads own.
        ipc.call('dispatch', 'hl.dsp.focus({workspace=72})')
        server = subprocess.Popen(['foot', '--server', '--config', '/dev/null'], env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        servers.append(server)
        socket_path = Path(env['XDG_RUNTIME_DIR']) / f'foot-{env["WAYLAND_DISPLAY"]}.sock'
        wait(lambda: socket_path.exists())
        def client(name):
            app = 'hyprflip-close-' + name
            process = subprocess.Popen(['footclient', '--app-id', app, '--title', name, 'sh', '-c', 'exec cat'],
                                       env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
            address = next(a for a, win in ipc.windows().items() if win['class'] == app)
            processes[address] = process
            return address
        f1, f2, other = client('f1'), client('f2'), spawn('other')
        c = restore([[f1, f2], [other]])
        clients = ipc.windows()
        assert clients[f1]['pid'] == clients[f2]['pid'] == server.pid, clients
        start = mark()
        ipc.focus(f1)
        press('F10')
        close_gone(f1); close_gone(f2)
        found = {r['address']: r for r in records(start, 2)}
        killed, sibling = found[f1], found[f2]
        about(killed, f1, clients[f1]); why(killed, 'killed', 'key')
        assert killed['pid'] == server.pid, killed
        about(sibling, f2, clients[f2]); why(sibling, 'own')
        # The first to close has its own place; the second is alone on the face by then and takes the card apart.
        earlier, later = sorted(found.values(), key=lambda r: r['seq'])
        place(earlier, c, 0, [f1, f2].index(earlier['address']), 2)
        place(later, c, 0, 0, 2, dissolved=True)
        assert gone(c)
        server.wait(timeout=5)
        passed('Super+F10 on one of two windows of one foot server reads killed by key with the server\'s pid; its '
               'other window, gone with the process, reads own with no via, and the second to close took the card '
               'apart')

        if args.protocol:
            ipc.call('dispatch', 'hl.dsp.focus({workspace=73})')
            k1, k2, k3 = spawn('k1'), spawn('k2'), spawn('k3')
            c = restore([[k1, k2], [k3]])
            clients = ipc.windows()
            start = mark()
            click_kill(k2)
            [r] = records(start, 1)
            about(r, k2, clients[k2]); place(r, c, 0, 1, 2); why(r, 'killed', 'click')
            assert r['pid'] == clients[k2]['pid'], r
            passed('hyprctl kill and a click on a card app read killed by click')

        # The cover closed by key.
        ipc.call('dispatch', 'hl.dsp.focus({workspace=74})')
        p, q, cover = spawn('p'), spawn('q'), spawn('cover')
        c = restore([[p], [q]])
        assert ipc.action(f'card {c} cover {cover}') == 'ok: ok' and card(c)['cover'] == cover
        clients = ipc.windows()
        start = mark()
        close_key(cover)
        [r] = records(start, 1)
        about(r, cover, clients[cover]); place(r, c, None, None, None, cover=True); why(r, 'requested', 'key')
        assert card(c)['cover'] is None and card(c)['faces'] == [[p], [q]]
        passed('the cover closed by key reads requested, with the card, cover true and no face, index or faces; '
               'the card stays')

        # The last app of a face on a 2-face card, closed by key: the card comes apart.
        start = mark()
        ipc.action(f'card {c} show 2')
        close_key(q)
        [r] = records(start, 1)
        about(r, q, clients[q]); place(r, c, 1, 0, 2, dissolved=True); why(r, 'requested', 'key')
        assert gone(c)
        passed('closing by key the last app of a face of a 2-face card reads dissolved, with the card and face it had')

        # The last face of a card at the core's limit (container_max_faces).
        ipc.call('dispatch', 'hl.dsp.focus({workspace=76})')
        most = status()['container_max_faces']
        apps = [[spawn(f'm{i}')] for i in range(1, most)] + [[spawn('last-a'), spawn('last-b')]]
        c = restore(apps)
        clients = ipc.windows()
        ipc.action(f'card {c} show {most}')
        start = mark()
        close_key(apps[-1][1])
        [r] = records(start, 1)
        about(r, apps[-1][1], clients[apps[-1][1]]); place(r, c, most - 1, 1, most); why(r, 'requested', 'key')
        passed(f'an app on face {most} of a {most}-face card (the core\'s limit) closed by key reads face {most - 1}, '
               f'faces {most}')

        # App-chosen text in a record: the status stays JSON and the helper still reads it.
        odd = 'hyprflip-close-Lua error "q" \\ \t end'
        strange = spawn('odd', app=odd)
        clients = ipc.windows()
        start = mark()
        close_key(strange)
        [r] = records(start, 1)
        about(r, strange, clients[strange]); assert r['initial_class'] == odd, r
        raw = subprocess.run(['hyprctl', 'hyprflip', 'status'], env=env, capture_output=True, timeout=8).stdout
        assert json.loads(raw)['closes']['list'][-1]['initial_class'] == odd
        passed('a class holding "Lua error", quotes, a backslash and a tab comes back exactly, in status JSON that '
               'the helper\'s Hyprctl still reads')

        # A plugin reload starts the records again under a new instance.
        ipc.call('plugin', 'unload', str(library)); loaded = False
        ipc.call('plugin', 'load', str(library)); loaded = True
        state = status()
        closes = state['closes']
        assert state['close_reasons'] is True and closes['watch'] == {'close': True, 'kill': True}, closes
        assert re.fullmatch(r'[0-9a-f]{16}', closes['instance']) and closes['instance'] != first_instance, closes
        assert (closes['next'], closes['oldest'], closes['list']) == (1, 1, []), closes
        last = spawn('after-reload')
        close_key(last)
        [r] = records(1, 1)
        why(r, 'requested', 'key')
        passed('after a plugin reload the hooks install again, the instance is new and the records start at 1')

    passed(f'all {reads} status replies parsed as JSON')
finally:
    for process in [*processes.values(), *servers]:
        if process and process.poll() is None: process.terminate()
    if loaded:
        try: ipc.call('plugin', 'unload', str(library))
        except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    (root / 'close-reason-results.json').write_text(json.dumps(checks, indent=2))
