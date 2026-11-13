#!/usr/bin/env python3
"""scripts/uninstall.py in a disposable compositor: after scripts/install.py and install-setup.py, the plugin unloads
with a reload, a card's apps stay open as ordinary windows, hyprland.lua is as it was, and a new install loads again.

Start the session with its own home, which the compositor's hyprflip.lua loads the plugin from:

  HOME=/tmp/hf-un/home python3 tests/nested_session.py --directory /tmp/hf-un [--aquamarine /tmp/aq/build]
  python3 tests/uninstall_session.py /tmp/hf-un/session.json
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('session', type=Path)
args = parser.parse_args()
root = args.session.resolve().parent
home = root / 'home'
user = root / 'config/hypr/hyprland.lua'  # the configuration the installers edit, which the session's own loads
ORIGINAL = '-- disposable uninstall test configuration\nhl.config({ general = { gaps_in = 7 } })\n'
env = environment(args.session) | {'HOME': str(home), 'XDG_CONFIG_HOME': str(root / 'config'),
                                   'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
session_config = root / 'hyprland.lua'
original_session = session_config.read_text()
processes, checks, failed = [], [], []


def check(message, body):
    try:
        body()
    except Exception as error:
        failed.append(message)
        print('FAIL', message, repr(error), flush=True)
    else:
        checks.append(message)
        print('PASS', message, flush=True)


def run(script, *arguments):
    result = subprocess.run([sys.executable, str(project / 'scripts' / script), *arguments], env=env, capture_output=True,
                            text=True, timeout=180)
    assert result.returncode == 0, (script, result.stdout, result.stderr)
    return result.stdout


def plugins():
    return {p['name'] for p in ipc.data('-j', 'plugin', 'list')}


def wait(fn, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(.05)
    raise AssertionError('timed out')


def spawn(name):
    app = 'hyprflip-uninstall-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, 'cat'], env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def installed():
    run('install.py')
    assert 'hyprflip' in plugins()
    # what the installers wrote is what this session reads: the plugin stays through a reload
    ipc.call('reload')
    assert 'hyprflip' in plugins() and not ipc.call('configerrors')


try:
    assert (home / '.local').resolve().is_relative_to(Path('/tmp')), home
    assert 'hyprflip' not in plugins(), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text(ORIGINAL)
    session_config.write_text(original_session + f'dofile({json.dumps(str(user))})\n')
    ipc.call('reload')
    assert not ipc.call('configerrors'), ipc.call('configerrors')

    def a_card_comes_apart():
        installed()
        out = run('install-setup.py')
        assert 'Guided setup installed' in out, out
        ipc.call('dispatch', 'hl.dsp.focus({ workspace = "61" })')
        front, back = spawn('front'), spawn('back')
        ipc.focused((front, 'mark'), (back, 'card'))
        wait(lambda: len(ipc.status()['containers']) == 1)
        out = run('uninstall.py', '--yes')
        assert 'Hyprflip is removed.' in out, out
        assert 'hyprflip' not in plugins(), plugins()
        assert not ipc.call('configerrors'), ipc.call('configerrors')
        assert user.read_text() == ORIGINAL, user.read_text()
        assert not (home / '.local/lib/hyprflip').exists()
        assert not list((root / 'config/hypr').glob('hyprflip*')), list((root / 'config/hypr').glob('hyprflip*'))
        windows = ipc.windows()
        assert {front, back} <= set(windows) and not windows[front]['grouped'] and not windows[back]['grouped'], windows
    check('an uninstall unloads the plugin with a reload, leaves the card\'s apps as ordinary windows and the '
          'configuration as it was', a_card_comes_apart)

    def again():
        installed()
        out = run('uninstall.py', '--yes')
        assert 'hyprflip' not in plugins() and user.read_text() == ORIGINAL, (out, plugins())
    check('a new install loads again after an uninstall, and uninstalls again', again)
    if failed:
        raise SystemExit(f'{len(failed)} of {len(failed) + len(checks)} checks failed')
finally:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    try:
        if 'hyprflip' in plugins():
            ipc.call('plugin', 'unload', str(home / '.local/lib/hyprflip/hyprflip.so'))
    except Exception:
        pass
    try:
        session_config.write_text(original_session)
        ipc.call('reload')
    except Exception:
        pass
    (root / 'uninstall-session-results.json').write_text(json.dumps(checks, indent=2))
