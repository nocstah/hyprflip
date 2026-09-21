#!/usr/bin/env python3
"""Save or restore a six-app card; designed to run on either side of a compositor restart."""
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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--state-dir', type=Path, required=True)
parser.add_argument('--phase', choices=('save', 'restore'), required=True)
parser.add_argument('--engine', type=Path)
args = parser.parse_args()
assert args.state_dir.resolve().is_relative_to('/tmp')
root, project = args.session.parent, Path(__file__).resolve().parent.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(args.state_dir)}
spec = importlib.util.spec_from_file_location('hf_saved_setup', project / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = setup; spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
loaded, processes, checks = [], [], []
output, completed = None, False


class Menu:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        if answer is None: raise setup.Cancelled()
        assert answer in [c.value for c in choices], (prompt, choices, answer)
        return answer
    def input(self, prompt): return next(self.answers)


def lua(code): return ipc.call('repl', code)
def card(): return ipc.status()['containers'][0]
def wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.03)
    raise AssertionError('State did not settle: ' + json.dumps(ipc.status()))
def passed(message): checks.append(message); print('PASS', message, flush=True)
def spawn(name):
    process = subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', name, '--title', name, 'sh', '-c', 'exec cat'],
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(w['class'] == name for w in ipc.windows().values()))
    return next(a for a, w in ipc.windows().items() if w['class'] == name)
def shape(): return setup.Saved.capture(card(), ipc.windows())
def assert_shape(expected):
    restored = shape()
    assert restored['active'] == expected['active'], (restored, expected)
    for left, right in zip(restored['faces'], expected['faces']):
        assert left['axis'] == right['axis'] and left['focus'] == right['focus'], (left, right)
        assert [a['class'] for a in left['apps']] == [a['class'] for a in right['apps']]
        assert all(abs(a - b) < .035 for a, b in zip(left['ratios'], right['ratios'])), (left, right)


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('saved-' + source.name); shutil.copy2(source, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    lua('hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    names = {m['name'] for m in ipc.data('-j', 'monitors')}; ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    lua(f'hl.monitor({{output="{output}",mode="2560x1440@60",position="2000x0",scale=1}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch', 'hl.dsp.focus({workspace=30})')
    fixtures = {w['class']: a for a, w in ipc.windows().items()}
    a, b = fixtures['hyprflip-front'], fixtures['hyprflip-back']
    for address in (a, b): ipc.move(address, 30)
    front = [a, spawn('hyprflip-save-front2'), spawn('hyprflip-save-front3')]
    back = [b, spawn('hyprflip-save-back2'), spawn('hyprflip-save-back3')]
    addresses = front + back
    if args.phase == 'save':
        ipc.focus(a); ipc.action('mark'); ipc.focus(b); ipc.action('pair')
        for face, axis in ((front, 'horizontal'), (back, 'vertical')):
            for address in face[1:]:
                ipc.focus(address); ipc.action('mark'); ipc.focus(face[0]); ipc.action('attach ' + axis)
        helper = setup.Setup(ipc, Menu())
        for members, axis, ratios in ((front, 'horizontal', [.5, .3, .2]), (back, 'vertical', [.2, .5, .3])):
            helper.restore_ratios({'windows': members, 'axis': axis, 'ratios': ratios})
        ipc.focus(front[2]); ipc.focus(back[1]); time.sleep(.2)
        before = deepcopy(card())
        flow = setup.Edit(ipc, Menu('save', 'Communications'))
        flow.apply(flow.prepare(back[1]))
        assert card() == before
        store = setup.RecipeStore(env)
        assert_shape(store.read()['Communications'])
        text = store.path.read_text()
        assert all(address not in text for address in addresses)
        (args.state_dir / 'before.json').write_text(json.dumps({'instance': env['HYPRLAND_INSTANCE_SIGNATURE'],
                                                              'addresses': addresses, 'recipe': store.read()['Communications']}))
        passed('saved a live six-app card with two axes, unequal proportions and remembered focus; no window addresses stored')
    else:
        before = json.loads((args.state_dir / 'before.json').read_text())
        assert env['HYPRLAND_INSTANCE_SIGNATURE'] != before['instance']
        assert not set(before['addresses']) & set(addresses)
        for address in front: ipc.move(address, 31)
        ipc.focus(b)
        flow = setup.Saved(ipc, Menu('0', 'restore', 'restore'))
        plan = flow.prepare_restore(); assert not ipc.status()['containers']
        flow.apply(plan); time.sleep(.2)
        assert_shape(before['recipe'])
        assert all(ipc.windows()[a]['workspace']['id'] == 30 for a in addresses)
        passed('after a real compositor restart, fresh app addresses restore both faces, axes, proportions and focus from another workspace')

        ipc.action('unpair')
        for address in front: ipc.move(address, 31)
        if args.engine:
            home = root / 'engine-home'; (home / '.local/state').mkdir(parents=True)
            engine = root / 'chillmode.lua'
            engine.write_text(args.engine.read_text().replace('os.getenv("HOME")', json.dumps(str(home))))
            lua('CHILLMODE_OPTS={auto=false,notify=false,keybind="",hide=false}; ' + f'dofile({json.dumps(str(engine))}); chillmode.toggle(31)')
            wait(lambda: all(ipc.windows()[a]['floating'] for a in front))
        else:
            for address in front: ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{address}",action="enable"}})')
        ipc.focus(b); time.sleep(.25)
        original_windows = deepcopy(ipc.windows())
        flow = setup.Saved(ipc, Menu('0', 'restore', 'restore', 'tile'))
        plan = flow.prepare_restore()
        real_action = ipc.action
        def rejected(action):
            if action == 'attach vertical': raise setup.SetupError('Injected attachment failure')
            return real_action(action)
        ipc.action = rejected
        try: flow.apply(plan)
        except setup.SetupError as error: assert 'Injected attachment' in str(error), error
        else: raise AssertionError('Expected a failed restore')
        finally: ipc.action = real_action
        time.sleep(.25)
        assert not ipc.status()['containers']
        for address in addresses:
            current, previous = ipc.windows()[address], original_windows[address]
            assert current['workspace'] == previous['workspace'] and current['floating'] == previous['floating']
            if previous['floating']:
                assert current['at'] == previous['at'] and current['size'] == previous['size'], (current, previous)
                assert ('chillmode' in current['tags']) == ('chillmode' in previous['tags'])
        for workspace in (30, 31): assert lua(f'return hl.plugin.hyprflip.protects_workspace({workspace})') == 'false'
        assert ipc.data('-j', 'activewindow')['address'] == b
        passed('a failed restore after partial grouping rolls back remote workspaces, floating geometry, Chill tags and original focus')
        flow = setup.Saved(ipc, Menu('0', 'restore', 'restore', 'tile'))
        flow.apply(flow.prepare_restore()); time.sleep(.2)
        assert_shape(before['recipe'])
        assert all(not ipc.windows()[a]['floating'] for a in addresses)
        passed('the same saved card restores successfully from Chill after the refused attempt')
        # Saving and deleting a recipe must never dissolve a running card.
        membership = deepcopy(card()['faces'])
        flow = setup.Saved(ipc, Menu('0', 'delete', 'delete')); flow.apply(flow.prepare_restore())
        assert card()['faces'] == membership and not setup.RecipeStore(env).read()
        passed('deleting a saved arrangement leaves the running card intact')
    completed = True
finally:
    for process in processes:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    config.write_text(original); ipc.call('reload')
    for target in reversed(loaded): ipc.call('plugin', 'unload', str(target))
    if output: ipc.call('output', 'remove', output)
    (args.state_dir / (args.phase + '-results.json')).write_text(json.dumps({'completed': completed, 'checks': checks}, indent=2))
