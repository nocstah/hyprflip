#!/usr/bin/env python3
"""The movement-shortcut switch in a real compositor. install-setup.py --navigation and --no-navigation, and the panel's
navigation action through the installed control.py, reload Hyprland, so that the keys come and go at once. Off, the
configuration's own Super+Shift+1 is back. The card and its windows stay as they were, and the panel action sends no
handoff. Everything is installed into a home inside the session folder.

Start the session with tests/nested_session.py --native-cards, then run this with its session.json.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import navigation  # noqa: E402
import workflow as w  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('session', type=Path)
args = parser.parse_args()
root = args.session.resolve().parent
home = root / 'switch-home'
env = environment(args.session) | {
    'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_STATE_HOME': str(home / '.local/state'),
    'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_CACHE_HOME': str(home / '.cache'), 'HYPRFLIP_MENU': 'fuzzel'}
env.pop('DISPLAY', None)
ipc = w.Hyprctl(env)
paths = navigation.Paths(env)
config, checks = root / 'hyprland.lua', []
OWN = 'Own key: move a window to workspace 1'


def passed(text): checks.append(text); print('PASS', text, flush=True)


def binds():
    return ipc.data('-j', 'binds')


def movement_keys():
    return sorted(b['description'] for b in binds() if b.get('description') in navigation.KEYS)


def own_key_there():
    return [b['description'] for b in binds() if b.get('description') == OWN]


def install(*flags):
    result = subprocess.run([sys.executable, str(project / 'scripts/install-setup.py'), *flags],
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


helper = home / '.local/lib/hyprflip/control.py'


def snapshot():
    return json.loads(subprocess.check_output([sys.executable, str(helper), 'snapshot'], env=env, text=True, timeout=20))


def panel(enabled):
    """The panel's navigation action as OmaCards sends it: one request, then the helper's JSON lines."""
    request = {'protocol': 1, 'action': 'navigation', 'enabled': enabled, 'context': snapshot()['context']}
    with (root / 'panel.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, str(helper), 'run', '--request', json.dumps(request)], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
    watchdog = threading.Timer(60, process.kill)
    watchdog.start()
    lines = []
    try:
        # its input stays open, as a panel's does, until the helper has answered
        for line in process.stdout:
            lines.append(json.loads(line))
            if lines[-1]['type'] in ('done', 'error', 'cancelled'): break
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        watchdog.cancel()
    return lines


def card_windows():
    return sorted((c['id'], [list(face) for face in c['faces']]) for c in ipc.status()['containers'])


try:
    session_windows(env)
    assert ipc.status().get('container_provider'), 'Start the session with --native-cards'
    for folder in ('.config/hypr', '.local/state', '.local/share', '.cache'):
        (home / folder).mkdir(parents=True, exist_ok=True)
    main = paths.main
    overrides = ''.join(f'hl.env({json.dumps(k)}, {json.dumps(env[k])})\n'
                        for k in ('HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'))
    # the session's configuration, a stand-in for the desktop's own Super+Shift+1, and the session's home
    main.write_text(overrides + config.read_text() + '\nhl.bind("SUPER + SHIFT + code:10", '
                    'hl.dsp.window.move({workspace="1"}), {description=' + json.dumps(OWN) + '})\n')
    config.write_text('dofile(' + json.dumps(str(main)) + ')\n')
    ipc.call('reload')
    assert not ipc.call('configerrors'), ipc.call('configerrors')
    assert ipc.call('repl', 'return os.getenv("XDG_CONFIG_HOME")') == str(home / '.config')
    assert own_key_there() and not movement_keys()
    deadline = time.monotonic() + 15
    while not card_windows() and time.monotonic() < deadline: time.sleep(.1)
    cards = card_windows()
    assert cards, 'the --native-cards demo has a card'

    install('--navigation')
    assert movement_keys() == sorted(navigation.KEYS), movement_keys()
    assert not own_key_there()
    state = snapshot()
    assert (state['navigation'], state['navigation_choice'], state['capabilities']['navigation']) == ('on', 'on', True), state
    assert card_windows() == cards
    passed('install-setup.py --navigation loads all 24 movement keys over the configuration\'s own, and the snapshot says on')

    lines = panel(False)
    assert [line['type'] for line in lines] == ['done'], lines
    assert 'Movement shortcuts off' in lines[0]['message'], lines
    assert not movement_keys() and own_key_there() == [OWN]
    assert not paths.module.exists() and not navigation.loaded(main.read_text())
    state = snapshot()
    assert (state['navigation'], state['navigation_choice']) == ('off', 'off'), state
    assert card_windows() == cards and not ipc.call('configerrors')
    passed('the panel action turns them off at once, without a handoff: the own Super+Shift+1 is back, the card stays')

    lines = panel(True)
    assert [line['type'] for line in lines] == ['done'], lines
    assert movement_keys() == sorted(navigation.KEYS) and not own_key_there()
    state = snapshot()
    assert (state['navigation'], state['navigation_choice']) == ('on', 'on'), state
    assert card_windows() == cards
    passed('the panel action turns them on again at once')

    # a copy with changes of the user's own: off keeps it with the backup, and the panel says where
    paths.module.write_bytes(paths.module.read_bytes() + b'-- a change of my own\n')
    assert snapshot()['navigation'] == 'edited'
    lines = panel(False)
    assert [line['type'] for line in lines] == ['done'] and 'kept in' in lines[0]['message'], lines
    kept = Path(lines[0]['message'].rsplit('kept in ', 1)[1].rstrip('.'))
    assert (kept / 'hyprflip-navigation.lua').read_bytes().endswith(b'-- a change of my own\n')
    assert not movement_keys()
    passed('an edited copy goes off with the backup the panel names')

    install('--navigation')
    output = install('--no-navigation')
    assert 'Movement shortcuts off' in output, output
    assert not movement_keys() and own_key_there() == [OWN]
    assert snapshot()['navigation_choice'] == 'off' and not paths.record.exists()
    install()
    assert not movement_keys() and snapshot()['navigation'] == 'off'
    assert card_windows() == cards and not ipc.call('configerrors')
    passed('install-setup.py --no-navigation turns them off, and a later plain install leaves them off')
finally:
    print(json.dumps({'checks': checks}), flush=True)
