#!/usr/bin/env python3
"""Exercise real portable pickers on an explicitly selected disposable desktop.

Run under dbus-run-session so detection never contacts the user's Omarchy shell.
Requires fuzzel, rofi, wofi and wtype on PATH (or --picker-bin).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from control import environment

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--picker-bin', type=Path)
parser.add_argument('--backend', choices=('fuzzel', 'rofi', 'wofi'), action='append')
args = parser.parse_args()
root = args.session.resolve().parent
env = environment(args.session) | {
    'XDG_CONFIG_HOME': str(root / 'menu-config'), 'XDG_DATA_HOME': str(root / 'menu-data'),
    'XDG_STATE_HOME': str(root / 'menu-state'), 'XDG_CACHE_HOME': str(root / 'menu-cache'),
    'HYPRFLIP_MENU': 'auto', 'GDK_BACKEND': 'wayland',
    'NO_AT_BRIDGE': '1', 'GSETTINGS_BACKEND': 'memory', 'GIO_USE_VFS': 'local',
}
env.pop('DISPLAY', None)
if args.picker_bin:
    env['PATH'] = str(args.picker_bin) + os.pathsep + env['PATH']
    env['LD_LIBRARY_PATH'] = str(args.picker_bin.parent / 'lib')
ipc = w.Hyprctl(env)
checks = []


class Request:
    def __init__(self): self.cancelled = threading.Event()
    def check(self):
        if self.cancelled.is_set(): raise w.Cancelled()


def wait(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('Picker did not reach the expected state')


def layers():
    return [row.get('namespace', '') for monitor in ipc.data('-j', 'layers').values()
            for level in monitor['levels'].values() for row in level]


def interact(backend, method, arguments, keys):
    request = Request()
    menu = w.DesktopMenu(backend, request, env)
    before = layers()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(getattr(menu, method), *arguments)
        try:
            wait(lambda: future.done() or layers() != before)
            if future.done(): return future.result()
            time.sleep(.5)  # Surface map precedes keyboard focus and GTK's idle population.
            subprocess.run(['wtype', *keys], env=env, check=True, timeout=3)
            try:
                return future.result(timeout=6)
            except TimeoutError:
                subprocess.run(['grim', '-o', output, str(root / ('menu-' + backend + '-failure.png'))], env=env, timeout=3)
                raise
        finally:
            request.cancelled.set()
            wait(lambda: layers() == before)


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


completed = False
output = None
try:
    monitors = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in monitors)
    ipc.call('eval', f'hl.monitor({{output="{output}",mode="1280x800@60",position="2000x0",scale=1}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    assert not w.omarchy_running(env), 'Use a private D-Bus session for this test'
    assert w.select_menu_backend(env) == 'fuzzel'
    passed('a stopped Omarchy shell automatically selects Fuzzel')
    choices = [w.Choice('first', 'Same app', 'One'), w.Choice('second', 'Same app', 'Two')]
    for backend in args.backend or ('fuzzel', 'rofi', 'wofi'):
        assert interact(backend, 'choose', ('Choose an app', choices), ['-k', 'Down', '-s', '200', '-k', 'Return']) == 'second'
        text = 'Research & notes'
        assert interact(backend, 'input', ('Name this card',), [text, '-k', 'Return']) == text
        try: interact(backend, 'choose', ('Cancel this menu', choices), ['-k', 'Escape'])
        except w.Cancelled: pass
        else: raise AssertionError(backend + ' should cancel on Escape')
        passed(backend + ': real selection uses the original row, text input works, Escape cancels')
    completed = True
finally:
    if output: ipc.call('output', 'remove', output)
    (root / 'menu-results.json').write_text(json.dumps({'completed': completed, 'checks': checks}, indent=2))
