#!/usr/bin/env python3
"""Restore missing panes in a disposable compositor, retaining the original card."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from control import environment

p = argparse.ArgumentParser(description=__doc__); p.add_argument('session', type=Path)
args = p.parse_args()
root, project = args.session.parent, Path(__file__).resolve().parent.parent
env = environment(args.session) | dict(XDG_STATE_HOME=str(root / 'repair-state'),
    XDG_DATA_HOME=str(root / 'repair-data'), XDG_DATA_DIRS=str(root / 'empty-data'),
    DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(root / 'no-notification-bus'))
spec = importlib.util.spec_from_file_location('hf_repair_setup', project / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = setup; spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
loaded, checks, processes = [], [], []
output, completed = None, False
apps = root / 'repair-data/applications'; apps.mkdir(parents=True, exist_ok=True)
names = ['hyprflip-repair-' + n for n in 'abcdef']


class Menu:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        assert answer in [c.value for c in choices], (prompt, choices, answer)
        return answer
    def input(self, prompt): return next(self.answers)


def wait(predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle: ' + json.dumps(ipc.status()))
def passed(message): checks.append(message); print('PASS', message, flush=True)
def fixture(name): return next((a for a, w in ipc.windows().items() if w['class'] == name), None)
def card(): return ipc.status()['containers'][0]
def active(): return ipc.data('-j', 'activewindow').get('address')
def close(address):
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda: address not in ipc.windows())
def definition(name, command=None):
    (apps / (name + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName=' + name +
        '\nStartupWMClass=' + name + '\nExec=' + (command or
        f'/usr/bin/foot --config /dev/null --app-id={name} --title={name} /usr/bin/cat') + '\n')
def repair():
    flow = setup.Edit(ipc, Menu('repair')); return flow, flow.prepare(active())
def arrange(members, axis, ratios):
    ipc.focused((members[0], 'arrange ' + axis + ''.join(f' {a}:{r}' for a, r in zip(members, ratios))))
def visible():
    c, windows = card(), ipc.windows()
    for side, face in enumerate(c['faces']):
        for a in face: assert windows[a]['acceptsInput'] == (c['unfolded'] or side == c['active'])


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('repair-' + source.name); shutil.copy2(source, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    monitors = {m['name'] for m in ipc.data('-j', 'monitors')}; ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in monitors)
    ipc.call('eval', f'hl.monitor({{output="{output}",mode="2560x1440@60",position="2000x0",scale=1}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch', 'hl.dsp.focus({workspace=60})')
    for name in names: definition(name)
    catalog = setup.DesktopApps(env)
    for name in names: catalog.launch(catalog.apps[name + '.desktop']).wait(timeout=5)
    wait(lambda: all(fixture(name) for name in names))
    a, b, c, d, e, f = [fixture(name) for name in names]
    ipc.focused((a, 'mark'), (d, 'pair'))
    for anchor, extras in ((a, [b,c]), (d, [e,f])):
        for extra in extras: ipc.focused((extra, 'mark'), (anchor, 'attach vertical'))
        arrange([anchor, *extras], 'vertical', [.2,.3,.5])
    ipc.focus(a)
    flow = setup.Edit(ipc, Menu('save', 'Communications', 'replace')); flow.apply(flow.prepare(a))
    recipe = setup.RecipeStore(env).read()['Communications']
    assert ipc.status()['repair_cards']

    for iteration, missing_names in enumerate(((names[1], names[4]), (names[0], names[3]),
                                                (names[2], names[5]), (names[0], names[1], names[3], names[4]))):
        if card()['unfolded']: ipc.action('unfold')
        for name in missing_names: close(fixture(name))
        for face in card()['faces']:
            if len(face) > 1: arrange(face, 'vertical', [.7, .3])
        ipc.focus(card()['faces'][iteration % 2][0])
        if iteration % 2: ipc.action('unfold')
        before, identities = deepcopy(card()), {a: w['pid'] for a,w in ipc.windows().items()}
        flow, plan = repair(); flow.apply(plan)
        after = card(); expected = [[fixture(name) for name in names[:3]], [fixture(name) for name in names[3:]]]
        assert after['faces'] == expected and after['id'] == before['id']
        assert after['current'] == before['current'] and active() == before['current']
        assert after['unfolded'] == before['unfolded']
        for side, layout in enumerate(after['layouts']):
            assert layout['focused'] == before['layouts'][side]['focused']
            survivors = dict(zip(before['faces'][side], before['layouts'][side]['ratios']))
            missing_share = sum(r for a,r in zip(expected[side], recipe['faces'][side]['ratios']) if a not in survivors)
            for a, r, saved in zip(expected[side], layout['ratios'], recipe['faces'][side]['ratios']):
                assert abs(r - (survivors[a] * (1 - missing_share) if a in survivors else saved)) < .00001
            assert all(ipc.windows()[a]['pid'] == identities[a] for a in survivors)
        visible()
        passed('repair position case ' + str(iteration + 1) + ': both faces retain card identity, survivor weights, focus and unfold state')

    if card()['unfolded']: ipc.action('unfold')
    before = deepcopy(card()); side = before['faces'][before['active']]; other = before['faces'][1 - before['active']]
    invalid = ['horizontal ' + ' '.join(f'{a}:.333333333333' for a in [side[0],side[0],side[2]]),
        'horizontal ' + ' '.join(f'{a}:.333333333333' for a in [side[0],other[0],side[2]]),
        'vertical ' + ' '.join(f'{a}:0' for a in side),
        'vertical ' + ' '.join(f'{a}:nan' for a in side),
        'vertical ' + ' '.join(f'{a}:1' for a in side)]
    for argument in invalid:
        try: ipc.action('arrange ' + argument)
        except setup.SetupError: pass
        else: raise AssertionError('Invalid layout was accepted: ' + argument)
        assert card() == before
    passed('malformed, duplicate, foreign-face, zero, nonfinite and unnormalized layout requests leave the card untouched')

    remote = fixture(names[1]); ipc.focused((remote, 'release')); ipc.move(remote, 61)
    ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{remote}",action="enable"}})')
    ipc.focus(card()['faces'][1][0]); before = deepcopy(card()); pid = ipc.windows()[remote]['pid']
    flow, plan = repair(); assert not plan.launchers; flow.apply(plan)
    assert card()['faces'][0][1] == remote and ipc.windows()[remote]['pid'] == pid
    assert ipc.windows()[remote]['workspace']['id'] == 60 and not ipc.windows()[remote]['floating']
    assert active() == before['current']; visible()
    passed('an existing floating app on another workspace is reused and tiled without restarting it')

    # Force a failure after real tree attachments to exercise rollback against hy3.
    remote = fixture(names[1]); ipc.focused((remote, 'release')); ipc.move(remote, 61)
    ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{remote}",action="enable"}})')
    ipc.focus(card()['faces'][1][0]); before = deepcopy(card())
    flow, plan = repair(); original_focused = ipc.focused; refused = False
    def failed_layout(*operations):
        global refused
        if not refused and any(action.startswith('arrange ') for _,action in operations):
            refused = True; raise setup.SetupError('Injected final arrangement failure')
        return original_focused(*operations)
    with patch.object(ipc, 'focused', side_effect=failed_layout):
        try: flow.apply(plan)
        except setup.SetupError as error: assert 'Injected final arrangement failure' in str(error), str(error)
        else: raise AssertionError('Layout failure should abort repair')
    after = card()
    assert after['faces'] == before['faces'] and after['id'] == before['id'] and after['current'] == before['current']
    for side in range(2):
        assert after['layouts'][side]['focused'] == before['layouts'][side]['focused']
        assert all(abs(x-y) < 1e-6 for x,y in zip(after['layouts'][side]['ratios'],before['layouts'][side]['ratios']))
    assert ipc.windows()[remote]['workspace']['id'] == 61 and ipc.windows()[remote]['floating']; visible()
    passed('failed final arrangement releases only the new pane, restores the original splits and returns the imported float')

    close(remote); ipc.focus(before['current'])
    delayed = root / 'repair-delayed.py'
    delayed.write_text('import os,time\ntime.sleep(1.5)\nos.execv("/usr/bin/foot", ' +
        repr(['/usr/bin/foot','--config','/dev/null','--app-id='+names[1],'--title='+names[1],'/usr/bin/cat']) + ')\n')
    definition(names[1], '/usr/bin/python ' + str(delayed))
    flow, plan = repair(); before = deepcopy(card())
    request = setup.Request(root / 'runtime', env['HYPRLAND_INSTANCE_SIGNATURE']); request.start(); flow.menu.request = request
    replacement = setup.Request(root / 'runtime', env['HYPRLAND_INSTANCE_SIGNATURE'])
    timer = threading.Timer(.35, replacement.start); timer.start()
    try:
        try: flow.apply(plan)
        except setup.Cancelled: pass
        else: raise AssertionError('Replacement request should cancel reopening')
    finally: timer.join(); request.finish(); replacement.finish()
    wait(lambda: fixture(names[1]))
    assert card()['faces'] == before['faces'] and card()['id'] == before['id']
    passed('cancelling a delayed reopen leaves the existing card intact and the late app separate')

    # Exercise provider rollback when one pane's own size constraints refuse a split.
    ipc.focus(card()['current']); ipc.action('unpair')
    for name in names:
        if address := fixture(name): ipc.move(address, 61)
    command = root / 'repair-minimum.command'; command.write_text('minimum 1500 100')
    process = subprocess.Popen(['python', str(project / 'tests/gtk_fixture.py'), 'hyprflip-repair-minimum', str(command)],
        env=env | {'GDK_BACKEND':'wayland', 'GSK_RENDERER':'cairo'}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process); wait(lambda: fixture('hyprflip-repair-minimum'))
    wide = fixture('hyprflip-repair-minimum'); a, b = fixture(names[0]), fixture(names[3])
    ipc.move(a,60); ipc.move(b,60); ipc.focused((a,'mark'),(b,'pair')); ipc.focused((wide,'mark'),(b,'attach vertical'))
    ipc.focus(b); before = deepcopy(card())
    try: arrange([b,wide], 'horizontal', [.8,.2])
    except setup.SetupError: pass
    else: raise AssertionError('The requested split cannot satisfy the app minimum width')
    assert card() == before; visible()
    passed('provider rejects a size-constrained arrangement and atomically restores its exact order, ratios and focus')
    completed = True
finally:
    config.write_text(original); ipc.call('reload')
    for target in reversed(loaded): ipc.call('plugin','unload',str(target))
    for a,w in ipc.windows().items():
        if w['class'] in names or w['class'] == 'hyprflip-repair-minimum': close(a)
    for process in processes:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    if output: ipc.call('output','remove',output)
    (root / 'repair-results.json').write_text(json.dumps({'completed':completed,'checks':checks},indent=2))
