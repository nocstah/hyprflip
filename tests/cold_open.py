#!/usr/bin/env python3
"""Reopen a saved card from closed Brave app windows in a disposable compositor."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from control import environment

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
p.add_argument('--engine', type=Path)
p.add_argument('--hyprglass', type=Path)
args = p.parse_args()
root, project = args.session.parent / 'cold-open', Path(__file__).resolve().parent.parent
root.mkdir(exist_ok=True)
env = environment(args.session)
for key, directory in (('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'),
                       ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state')):
    (root / directory).mkdir(exist_ok=True)
    env[key] = str(root / directory)
env.update(XDG_DATA_DIRS=str(root / 'empty-data'), DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(root / 'no-bus'))
spec = importlib.util.spec_from_file_location('hf_cold_setup', project / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = setup; spec.loader.exec_module(setup)
trace = []


class ObservedIPC(setup.Hyprctl):
    def windows(self):
        result = super().windows()
        trace.append({'t': time.monotonic(), 'windows': {a: {k: w.get(k) for k in
                     ('class', 'pid', 'workspace', 'floating', 'mapped', 'hidden')} for a, w in result.items()}})
        return result

    def data(self, *arguments):
        result = super().data(*arguments)
        if arguments in (('-j', 'activewindow'), ('-j', 'activeworkspace')):
            trace.append({'t': time.monotonic(), arguments[-1]: result})
        return result


class Menu:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        assert answer in [c.value for c in choices], (prompt, choices, answer)
        return answer
    def input(self, prompt): return next(self.answers)


ipc = ObservedIPC(env)
config = args.session.parent / 'hyprland.lua'; original = config.read_text()
loaded, checks, processes = [], [], []
output, completed = None, False
titles = ['Hyprflip cold front', 'Hyprflip cold back', 'Hyprflip cold third']
apps = root / 'data/applications'; apps.mkdir(exist_ok=True)


def wait(predicate, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.06)
    raise AssertionError('Cold-open state did not settle')


def addresses():
    windows = ipc.windows()
    return [next((a for a, w in windows.items() if w['title'] == title), None) for title in titles]


def close_all():
    if ipc.status()['containers']: ipc.action('unpair')
    current = addresses()
    for address in current:
        if address: ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda: not any(addresses()))


def passed(message): checks.append(message); print('PASS', message, flush=True)


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / source.name; shutil.copy2(source, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    if args.hyprglass:
        target = root / 'hyprglass.so'; shutil.copy2(args.hyprglass, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    if args.hyprglass: ipc.call('eval', 'hl.plugin.hyprglass.config({enabled=true,manage_window_blur=true})')
    monitors = {m['name'] for m in ipc.data('-j', 'monitors')}; ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in monitors)
    ipc.call('eval', f'hl.monitor({{output="{output}",mode="2560x1440@60",position="2000x0",scale=1}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch', 'hl.dsp.focus({workspace=60})')
    if args.engine:
        home = root / 'home'; (home / '.local/state').mkdir(parents=True, exist_ok=True)
        engine = root / 'chillmode.lua'
        engine.write_text(args.engine.read_text().replace('os.getenv("HOME")', json.dumps(str(home))))
        ipc.call('eval', 'CHILLMODE_OPTS={auto=true,auto_max=3,notify=false,keybind="",key_hide="",key_restore="",hide=false}; '
                 + f'dofile({json.dumps(str(engine))})')
    commands = []
    for index, title in enumerate(titles[:2]):
        page = root / f'app{index}.html'
        page.write_text(f'''<title>{title}</title><style>
body{{margin:0;background:#{'284455' if index == 0 else '553344'};color:white;font:32px sans-serif}}
h1{{margin:60px}}.corner{{position:fixed;width:40px;height:40px;background:#00cc99}}
.tr{{right:0;top:0}}.bl{{left:0;bottom:0}}.br{{right:0;bottom:0}}</style>
<div class="corner"></div><div class="corner tr"></div><div class="corner bl"></div><div class="corner br"></div>
<h1>{title}</h1><p>All four green corners must remain visible after resizing.</p>''')
        commands.append(['/usr/bin/brave', '--user-data-dir=' + str(root / 'profile'), '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
            '--disable-sync', '--ozone-platform=wayland', '--app=' + page.as_uri()])
    commands.append(['/usr/bin/foot', '--config', '/dev/null', '--app-id=hyprflip-cold-third',
                     '--title=' + titles[2], '/usr/bin/cat'])
    for index, command in enumerate(commands):
        with (root / f'app{index}.log').open('w') as log:
            processes.append(subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT))
        wait(lambda: addresses()[index])
    a, b, c = addresses()
    with setup.Setup(ipc, Menu()).reserve(ipc.windows(), ipc.status(), 60):
        for address in (a, b, c): ipc.tile(ipc.windows()[address])
        ipc.focused((a, 'mark'), (b, 'pair')); ipc.focused((c, 'mark'), (b, 'attach horizontal'))
    ipc.focus(a)
    for index, (address, command) in enumerate(zip((a, b, c), commands)):
        # A tiny script avoids desktop-entry argument escaping obscuring the test.
        launcher = root / f'launch{index}.py'
        launcher.write_text('import os\nos.execv(' + repr(command[0]) + ', ' + repr(command) + ')\n')
        (apps / f'cold{index}.desktop').write_text('[Desktop Entry]\nType=Application\nName=' + titles[index]
            + '\nStartupWMClass=' + ipc.windows()[address]['class'] + '\nExec=/usr/bin/python ' + str(launcher) + '\n')
    flow = setup.Edit(ipc, Menu('save', 'Cold card', 'replace')); flow.apply(flow.prepare(a))
    recipe = setup.RecipeStore(env).read()['Cold card']
    assert recipe['active'] == 0 and [len(face['apps']) for face in recipe['faces']] == [1, 2]
    close_all()
    # Let the old browser finish shutdown before cold-starting its profile again.
    for process in processes:
        process.wait(timeout=10)
    for attempt in range(3):
        flow = setup.Saved(ipc, Menu('0')); plan = flow.prepare_restore()
        assert len(plan.launchers) == 3 and plan.chosen == [None, None, None]
        print('Opening all three closed apps, attempt', attempt + 1, flush=True)
        flow.apply(plan)
        a, b, c = addresses(); card = ipc.status()['containers'][0]
        assert card['faces'] == [[a], [b, c]] and card['active'] == 0 and card['current'] == a, card
        time.sleep(.5)
        assert all(not ipc.windows()[address]['floating'] for address in (a, b, c))
        subprocess.run(['grim', '-o', output, str(root / f'front-{attempt}.png')], env=env, check=True, timeout=8)
        ipc.action('flip'); wait(lambda: not ipc.status()['animating'])
        time.sleep(.4)
        subprocess.run(['grim', '-o', output, str(root / f'back-{attempt}.png')], env=env, check=True, timeout=8)
        passed(f'all three closed apps reopen into the saved front/back arrangement, attempt {attempt + 1}')
        close_all(); time.sleep(1)
    completed = True
finally:
    (root / 'trace.json').write_text(json.dumps(trace))
    (root / 'results.json').write_text(json.dumps({'completed': completed, 'checks': checks}, indent=2))
    close_all()
    if args.engine: ipc.call('eval', 'if chillmode then chillmode.unload() end')
    # Unload core and layout while Hyprglass is still mapped.
    for target in (root / 'hyprflip.so', root / 'libhy3.so', root / 'hyprglass.so'):
        if target in loaded: ipc.call('plugin', 'unload', str(target))
    config.write_text(original); ipc.call('reload')
    if output: ipc.call('output', 'remove', output)
    for process in processes:
        if process.poll() is None: process.terminate()
