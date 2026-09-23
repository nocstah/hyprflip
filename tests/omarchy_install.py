#!/usr/bin/env python3
"""Install from source in a fresh home with stock Omarchy defaults and real menus.

This uses the host's installed packages, not a fresh OS. Bubblewrap hides the
real home and makes the host filesystem read-only. Startup services are omitted;
the real Omarchy shell runs separately on a private D-Bus and Wayland session.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True, help='A clean, built source checkout')
parser.add_argument('--parent-session', type=Path, help='Optional disposable parent compositor connection')
parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
args = parser.parse_args()
root, source = args.directory.resolve(), args.source.resolve()
if not root.is_relative_to('/tmp') or len(os.fsencode(root)) > 18:
    raise SystemExit('Use a short temporary directory, e.g. /tmp/hf-install')
if not (source / 'build/hyprflip.so').is_file():
    raise SystemExit('Build the source checkout with make test first')
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
if subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=source, text=True).strip():
    raise SystemExit('Use a clean source checkout so the test records an exact revision')
task_home = root / 'home'
env = os.environ.copy()
if args.parent_session:
    connection = json.loads(args.parent_session.read_text())
    assert Path(connection['XDG_RUNTIME_DIR']).is_relative_to('/tmp')
    env.update(connection)
parent_display = Path(env.get('WAYLAND_DISPLAY', 'wayland-1'))
if not parent_display.is_absolute(): parent_display = Path(env['XDG_RUNTIME_DIR']) / parent_display

if not args.inside:
    if root.exists(): raise SystemExit('Choose a new test directory; existing data is never overwritten')
    root.mkdir(mode=0o700)
    for directory in ('home', 'runtime', 'home/.config', 'home/.cache', 'home/.local/share', 'home/.local/state'):
        (root / directory).mkdir(mode=0o700, parents=True, exist_ok=True)
    runner = root / 'runner.py'
    shutil.copy2(__file__, runner)
    env.update(HOME=str(task_home), XDG_RUNTIME_DIR=str(root / 'runtime'),
               XDG_CONFIG_HOME=str(task_home / '.config'), XDG_CACHE_HOME=str(task_home / '.cache'),
               XDG_DATA_HOME=str(task_home / '.local/share'), XDG_STATE_HOME=str(task_home / '.local/state'),
               WAYLAND_DISPLAY=str(parent_display), OMARCHY_PATH='/usr/share/omarchy',
               LIBSEAT_BACKEND='hyprflip-test-no-physical-session', AQ_DRM_DEVICES='/dev/null',
               HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', HYPRLAND_NO_CRASHREPORTER='1',
               PATH='/usr/share/omarchy/bin:/usr/bin:/bin', HYPRFLIP_MENU='auto',
               GDK_SCALE='1', GSK_RENDERER='cairo', HYPRFLIP_TEST_REAL_HOME=str(Path.home()))
    for name in ('HYPRLAND_INSTANCE_SIGNATURE', 'DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'LD_PRELOAD', 'PYTHONPATH'):
        env.pop(name, None)
    command = ['bwrap', '--die-with-parent', '--unshare-pid', '--ro-bind', '/', '/', '--tmpfs', '/home',
               '--tmpfs', '/tmp', '--bind', str(root), str(root), '--ro-bind', str(source), str(source),
               '--ro-bind', str(parent_display.parent), str(parent_display.parent), '--proc', '/proc',
               '--dev', '/dev', '--dev-bind', '/dev/dri', '/dev/dri', '--chdir', str(root),
               'dbus-run-session', '--', 'python3', str(runner), '--inside',
               '--directory', str(root), '--source', str(source)]
    raise SystemExit(subprocess.run(command, env=env).returncode)

assert Path.home() == task_home
assert not (Path(env['HYPRFLIP_TEST_REAL_HOME']) / '.config/hypr/hyprland.lua').exists(), 'The real configuration must be hidden'
assert os.environ.get('DBUS_SESSION_BUS_ADDRESS')
hypr_config = task_home / '.config/hypr'
shutil.copytree('/usr/share/omarchy/config/hypr', hypr_config)
main = hypr_config / 'hyprland.lua'
original_main = main.read_bytes()
wrapper = root / 'hyprland.lua'
wrapper.write_text('package.preload["default.hypr.autostart"] = function() return {} end\n'
                   + 'dofile(' + json.dumps(str(main)) + ')\n'
                   + 'hl.monitor({output="",mode="1440x900@60",position="auto",scale=1})\n'
                   + 'hl.env("GDK_SCALE", "1")\n'
                   + 'hl.config({animations={enabled=false},input={follow_mouse=0}})\n')
shell_config = task_home / '.config/omarchy/shell.json'
shell_config.parent.mkdir(parents=True)
shell_defaults = json.loads(Path('/usr/share/omarchy/config/omarchy/shell.json').read_text())
shell_defaults['idle'] = {'screensaver': 86400, 'lock': 86400}
shell_config.write_text(json.dumps(shell_defaults))
sys.path.insert(0, str(source / 'scripts'))
import workflow as w
processes, checks = [], []

def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)

def start(command, name):
    with (root / (name + '.log')).open('wb') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    processes.append(process)
    return process

def wait(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.06)
    raise AssertionError('Clean-install state did not settle; see ' + str(root))

def run_script(name, *flags):
    result = subprocess.run(['python3', str(source / 'scripts' / name), *flags], env=env,
                            capture_output=True, text=True, timeout=30)
    with (root / 'install.log').open('a') as log:
        log.write(name + ' ' + ' '.join(flags) + '\n' + result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr

try:
    compositor = start(['Hyprland', '--config', str(wrapper)], 'compositor')
    wait(lambda: compositor.poll() is not None or list((root / 'runtime').glob('hypr/*/.socket.sock')), 25)
    assert compositor.poll() is None, 'Nested compositor exited; see compositor.log'
    socket = next((root / 'runtime').glob('hypr/*/.socket.sock'))
    display = next(p for p in (root / 'runtime').glob('wayland-*') if not p.name.endswith('.lock'))
    env.update(HYPRLAND_INSTANCE_SIGNATURE=socket.parent.name, WAYLAND_DISPLAY=display.name)
    (root / 'session.json').write_text(json.dumps({key: env[key] for key in
        ('XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE')}))
    ipc = w.Hyprctl(env)
    assert not ipc.call('configerrors')
    assert not ipc.data('-j', 'plugin', 'list')
    assert ipc.call('repl', 'return hl.get_config("general.layout")') == 'dwindle'
    assert ipc.call('repl', 'return os.getenv("HOME")') == str(task_home)
    passed('Stock Omarchy configuration starts on dwindle with a fresh home, private session and no compositor plugins')
    # Quickshell's audio service expects a responding PipeWire server. This
    # private server has no audio devices in the test's minimal /dev mount.
    start(['pipewire'], 'pipewire')
    shell = start(['quickshell', '-n', '-p', '/usr/share/omarchy/shell'], 'shell')
    wait(lambda: w.omarchy_running(env), 25)
    run_script('install.py', '--dry-run')
    assert main.read_bytes() == original_main and not (task_home / '.local/lib/hyprflip').exists()
    run_script('install.py')
    assert ipc.status()['native_cards'] and not ipc.status()['hy3_provider']
    assert [p['name'] for p in ipc.data('-j', 'plugin', 'list')] == ['hyprflip']
    passed('The published core installer passes dry-run, installs, loads and preserves the stock dwindle layout')
    wait(lambda: shell.poll() is not None or w.omarchy_running(env), 25)
    assert shell.poll() is None, 'Omarchy shell exited; see shell.log'
    run_script('install-setup.py', '--dry-run')
    run_script('install-setup.py')
    helper = task_home / '.local/lib/hyprflip/setup.py'
    assert subprocess.check_output(['python3', str(helper), '--check-menu'], env=env, text=True).strip() == 'omarchy'
    assert not ipc.call('configerrors')
    owned = [b for b in ipc.data('-j', 'binds') if b.get('description', '').startswith('Hyprflip:')]
    assert len({(b['modmask'], b['key'].lower()) for b in owned}) == len(owned)
    passed('Guided helpers select the real Omarchy menu, import correctly and register shortcuts without stock binding conflicts')

    # Run the installed helper module, not the copy from the source checkout.
    sys.path[0] = str(helper.parent)
    del sys.modules['workflow']
    import workflow as w
    ipc = w.Hyprctl(env)
    request = w.Request(root / 'runtime', env['HYPRLAND_INSTANCE_SIGNATURE'])
    request.start()
    class Menu(w.AutoMenu):
        def __init__(self, *answers):
            directory = Path(tempfile.mkdtemp(prefix='menu-', dir=root))
            super().__init__(directory, request, env)
            assert self.backend == 'omarchy'
            self.answers = iter(answers)
        def answer(self, method, arguments, keys):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.call, method, *arguments)
                try:
                    time.sleep(.7)
                    subprocess.run(['wtype', *keys], env=env, check=True, timeout=5)
                    return future.result(timeout=10)
                finally:
                    if not future.done(): request.finish()
        def choose(self, prompt, choices):
            answer = next(self.answers)
            index = [choice.value for choice in choices].index(answer)
            return self.answer('choose', (prompt, choices), ['-k', 'Down', '-s', '80'] * index + ['-k', 'Return'])
        def input(self, prompt):
            return self.answer('input', (prompt,), [next(self.answers), '-k', 'Return'])

    names = ['hyprflip-install-' + side for side in ('front', 'back', 'notes')]
    applications = task_home / '.local/share/applications'
    applications.mkdir(parents=True)
    for name in names:
        (applications / (name + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName=' + name
            + '\nStartupWMClass=' + name + '\nExec=/usr/bin/foot --config /dev/null --app-id=' + name
            + ' --title=' + name + ' /usr/bin/cat\n')
        start(['foot', '--config', '/dev/null', '--app-id', name, '--title', name, '/usr/bin/cat'], name)
    def fixture(): return {v['class']: a for a, v in ipc.windows().items() if v['class'] in names}
    def card():
        cards = ipc.status()['containers']
        assert len(cards) == 1, cards
        return cards[0]
    wait(lambda: set(fixture()) == set(names))
    a, b, c = (fixture()[name] for name in names)
    ipc.focus(a)
    flow = w.Setup(ipc, Menu(b, c, 'create')); flow.apply(flow.prepare(a))
    assert card()['faces'] == [[a], [b, c]] and card()['native_group']
    ipc.action('flip'); wait(lambda: not ipc.status()['animating'])
    ipc.action('flip'); wait(lambda: not ipc.status()['animating'])
    ipc.action('unfold'); assert card()['unfolded']
    ipc.action('unfold'); assert not card()['unfolded']
    passed('Real Omarchy menu choices create a native card; flip and unfold work with the core alone')
    ipc.focus(a)
    flow = w.Edit(ipc, Menu('save', 'Clean install')); flow.apply(flow.prepare(a))
    recipe = w.RecipeStore(env).read()['Clean install']
    assert all(app.get('desktop_id') for face in recipe['faces'] for app in face['apps'])
    old_pids = {win['pid'] for win in ipc.windows().values()}
    ipc.action('unpair')
    for address in (a, b, c):
        ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda: not fixture())
    flow = w.Saved(ipc, Menu('0')); flow.apply(flow.prepare_restore())
    a, b, c = (fixture()[name] for name in names)
    assert card()['faces'] == [[a], [b, c]] and card()['native_group']
    assert not old_pids.intersection(win['pid'] for win in ipc.windows().values())
    assert not ipc.call('configerrors')
    passed('A named card saved through real menus cold-launches all three apps and restores on dwindle')
    request.finish()
finally:
    for process in reversed(processes):
        if process.poll() is None: process.terminate()
    for process in reversed(processes):
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill()
    (root / 'session.json').unlink(missing_ok=True)
    (root / 'results.json').write_text(json.dumps({'source': str(source), 'revision': revision, 'checks': checks,
        'scope': 'Fresh home and stock Omarchy configuration using host packages; not a fresh OS install'}, indent=2) + '\n')
