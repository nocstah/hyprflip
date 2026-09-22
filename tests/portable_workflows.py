#!/usr/bin/env python3
"""Install and use portable helpers in a disposable --containers demo.

Run with a private D-Bus: dbus-run-session -- python3 tests/portable_workflows.py
SESSION --picker-bin PATH. Only the disposable demo's sample apps are closed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from control import environment
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--picker-bin', type=Path, required=True)
args = parser.parse_args()
root, project = args.session.resolve().parent, Path(__file__).resolve().parent.parent
env = environment(args.session) | {
    'HOME': str(root / 'portable-home'), 'XDG_CONFIG_HOME': str(root / 'config'),
    'XDG_STATE_HOME': str(root / 'portable-state'), 'XDG_DATA_HOME': str(root / 'portable-data'),
    'XDG_DATA_DIRS': str(root / 'empty-data'), 'XDG_CACHE_HOME': str(root / 'portable-cache'),
    'PATH': str(args.picker_bin) + os.pathsep + os.environ['PATH'],
    'LD_LIBRARY_PATH': str(args.picker_bin.parent / 'lib'), 'HYPRFLIP_MENU': 'auto',
}
env.pop('DISPLAY', None)
ipc = w.Hyprctl(env)
request = w.Request(Path(env['XDG_RUNTIME_DIR']), env['HYPRLAND_INSTANCE_SIGNATURE'])
config = root / 'hyprland.lua'
original = config.read_text()
names = ('hyprflip-front', 'hyprflip-back', 'hyprflip-notes')
checks, output, completed = [], None, False


def wait(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle: ' + json.dumps(ipc.status()))


def layers():
    return [row['address'] for m in ipc.data('-j', 'layers').values() for rows in m['levels'].values() for row in rows]


class Menu(w.AutoMenu):
    def __init__(self, *answers):
        super().__init__(root, request, env)
        assert self.backend == 'fuzzel'
        self.answers = iter(answers)
    def answer(self, method, arguments, keys):
        before = layers()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.call, method, *arguments)
            try:
                wait(lambda: future.done() or layers() != before)
                if not future.done():
                    time.sleep(.5)
                    subprocess.run(['wtype', *keys], env=env, check=True, timeout=4)
                return future.result(timeout=8)
            finally:
                if not future.done():
                    request.finish()  # Cancel the picker rather than leave a stuck worker.
                wait(lambda: layers() == before)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        index = [c.value for c in choices].index(answer)
        keys = ['-k', 'Down', '-s', '100'] * index + ['-k', 'Return']
        return self.answer('choose', (prompt, choices), keys)
    def input(self, prompt):
        return self.answer('input', (prompt,), [next(self.answers), '-k', 'Return'])


def passed(text): checks.append(text); print('PASS', text, flush=True)
def card(): return ipc.status()['containers'][0]
def fixture(): return {v['class']: a for a, v in ipc.windows().items() if v['class'] in names}
def reveal(address):
    flow = w.Find(ipc, Menu(address))
    flow.apply(flow.prepare())
    assert ipc.data('-j', 'activewindow')['address'] == address


try:
    assert not w.omarchy_running(env), 'Use a private D-Bus session'
    assert set(fixture()) == set(names), 'Start the disposable three-window demo'
    assert len(ipc.status()['containers']) == 1
    assert {a for f in card()['faces'] for a in f} == set(fixture().values())
    request.start()
    home = Path(env['HOME']); home.mkdir(exist_ok=True)
    main = Path(env['XDG_CONFIG_HOME']) / 'hypr/hyprland.lua'
    main.parent.mkdir(parents=True, exist_ok=True)
    overrides = ''.join('hl.env(' + json.dumps(k) + ', ' + json.dumps(env[k]) + ')\n'
                        for k in ('HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'XDG_DATA_DIRS',
                                  'XDG_CACHE_HOME', 'PATH', 'LD_LIBRARY_PATH', 'DBUS_SESSION_BUS_ADDRESS'))
    main.write_text(original + '\n' + overrides + '\nhl.config({input={resolve_binds_by_sym=true}})\n')
    config.write_text('dofile(' + json.dumps(str(main)) + ')\n')
    ipc.call('reload'); assert not ipc.call('configerrors')
    assert ipc.call('repl', 'return os.getenv("HOME")') == str(home)
    before = deepcopy(card())
    for flags in (['--dry-run', '--mouse-flip'], ['--mouse-flip']):
        result = subprocess.run([sys.executable, str(project / 'scripts/install-setup.py'), *flags],
                                env=env, text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
    assert card()['faces'] == before['faces']
    helper = home / '.local/lib/hyprflip/setup.py'
    assert subprocess.check_output([sys.executable, str(helper), '--check-menu'], env=env, text=True).strip() == 'fuzzel'
    assert ipc.call('repl', 'return package.loaded["hypr.hyprflip-shortcuts"].version') == '1'
    assert not ipc.call('configerrors')
    passed('plain Hyprland imports modules, installs helpers and optional mouse binding, and preserves the existing card')

    monitors = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in monitors)
    ipc.call('eval', f'hl.monitor({{output="{output}",mode="1920x1200@60",position="2000x0",scale=1}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=70})')
    a, b, c = (fixture()[name] for name in names)
    ipc.focused((a, 'workspace 70'))
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.focused((a, 'unpair'))
    flow = w.Setup(ipc, Menu(b, c)); flow.apply(flow.prepare(a))
    assert card()['faces'] == [[a], [b, c]] and card()['active'] == 0 and not card()['unfolded']
    passed('real Fuzzel choices create a folded front / two-app back card')

    applications = Path(env['XDG_DATA_HOME']) / 'applications'; applications.mkdir(parents=True, exist_ok=True)
    for name in names:
        (applications / (name + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName=' + name
            + '\nStartupWMClass=' + name + '\nExec=/usr/bin/foot --config /dev/null --app-id=' + name
            + ' --title=' + name + ' /usr/bin/cat\n')
    flow = w.Edit(ipc, Menu('save', 'Portable comms')); flow.apply(flow.prepare(a))
    recipe = w.RecipeStore(env).read()['Portable comms']
    assert all(app.get('desktop_id') for face in recipe['faces'] for app in face['apps'])
    ipc.focused((a, 'unpair'))
    for address in (a, b, c): ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda: not fixture())
    flow = w.Saved(ipc, Menu('0')); flow.apply(flow.prepare_restore())
    a, b, c = (fixture()[name] for name in names)
    assert card()['faces'] == [[a], [b, c]] and card()['active'] == 0 and not card()['unfolded']
    passed('save via real text input, close all three apps, then reopen the exact card through the portable menu')

    shape = deepcopy(card())
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=220,enabled=true}}})')
    reveal(c)
    assert card()['faces'] == shape['faces'] and card()['active'] == 1
    ipc.call('dispatch', 'hl.dsp.focus({workspace=72})')
    reveal(a)
    assert ipc.data('-j', 'activeworkspace')['id'] == 70
    assert all(ipc.windows()[addr]['workspace']['id'] == 70 for addr in (a, b, c))
    ipc.focused((a, 'unfold')); reveal(c); assert card()['unfolded']
    ipc.focused((c, 'unfold'), (c, 'floating')); reveal(a)
    assert card()['floating'] and card()['faces'] == shape['faces']
    passed('Find reveals an exact hidden pane, navigates from another workspace, and preserves unfolded/floating cards')

    ipc.focused((a, 'unpair'))
    ipc.call('eval', 'hl.config({general={layout="dwindle"},plugin={hyprflip={duration_ms=0}}})')
    for address in (a, b, c):
        if ipc.windows()[address]['floating']: ipc.tile(ipc.windows()[address])
    ipc.focused((a, 'mark'), (b, 'pair'))
    assert len(ipc.status()['pairs']) == 1 and not ipc.status()['containers']
    reveal(a); reveal(b)
    assert ipc.status()['pairs'][0]['current'] == b
    passed('Find also reveals either side of a native two-window pair without the container layout')
    completed = True
finally:
    request.finish()
    # These are known demo classes, on the explicitly guarded disposable connection.
    for address in list(fixture().values()):
        ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    config.write_text(original); ipc.call('reload')
    if output: ipc.call('output', 'remove', output)
    (root / 'portable-results.json').write_text(json.dumps({'completed': completed, 'checks': checks}, indent=2))
