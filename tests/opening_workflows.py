#!/usr/bin/env python3
"""Launch real desktop entries and rebuild a saved card in a disposable session."""
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
from control import environment

p = argparse.ArgumentParser(description=__doc__); p.add_argument('session', type=Path)
args = p.parse_args()
root, project = args.session.parent, Path(__file__).resolve().parent.parent
env = environment(args.session) | {'XDG_STATE_HOME':str(root / 'open-state'),
    'XDG_DATA_HOME':str(root / 'open-data'), 'XDG_DATA_DIRS':str(root / 'empty-data'),
    'DBUS_SESSION_BUS_ADDRESS':'unix:path=' + str(root / 'no-notification-bus')}
spec = importlib.util.spec_from_file_location('hf_open_setup', project / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = setup; spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
loaded, checks = [], []
output, completed = None, False
apps = root / 'open-data/applications'; apps.mkdir(parents=True, exist_ok=True)
names = ['hyprflip-open-front', 'hyprflip-open-back', 'hyprflip-open-third']


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
def fixture(name): return next((a for a,w in ipc.windows().items() if w['class'] == name), None)
def card(): return ipc.status()['containers'][0]
def close(address):
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda: address not in ipc.windows())
def definition(name, command=None):
    (apps / (name + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName=' + name +
        '\nStartupWMClass=' + name + '\nExec=' + (command or
        f'/usr/bin/foot --config /dev/null --app-id={name} --title={name} /usr/bin/cat') + '\n')
def opening():
    flow = setup.Saved(ipc, Menu('0','open','open'))
    return flow, flow.prepare_restore()


try:
    assert not ipc.data('-j','plugin','list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('open-' + source.name); shutil.copy2(source,target)
        ipc.call('plugin','load',str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"','layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval','hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    monitors = {m['name'] for m in ipc.data('-j','monitors')}; ipc.call('output','create','headless')
    output = next(m['name'] for m in ipc.data('-j','monitors') if m['name'] not in monitors)
    ipc.call('eval',f'hl.monitor({{output="{output}",mode="2560x1440@60",position="2000x0",scale=1}})')
    ipc.call('dispatch',f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch','hl.dsp.focus({workspace=50})')
    for name in names: definition(name)
    catalog = setup.DesktopApps(env)
    for name in names: catalog.launch(catalog.apps[name + '.desktop']).wait(timeout=5)
    wait(lambda: all(fixture(name) for name in names))
    a,b,c = [fixture(name) for name in names]
    ipc.focused((a,'mark'),(b,'pair')); ipc.focused((c,'mark'),(b,'attach vertical'))
    setup.Setup(ipc,Menu()).restore_ratios({'windows':[b,c],'axis':'vertical','ratios':[.65,.35]})
    ipc.focus(c)
    flow = setup.Edit(ipc,Menu('save','Communications')); flow.apply(flow.prepare(c))
    recipe = setup.RecipeStore(env).read()['Communications']
    assert all(app['desktop_id'] == app['class'] + '.desktop' for face in recipe['faces'] for app in face['apps'])
    ipc.action('unpair'); close(c); ipc.move(a,51); ipc.focus(b)
    original_pids = {w:ipc.windows()[w]['pid'] for w in (a,b)}
    flow, plan = opening()
    assert plan.chosen == [a,b,None] and not fixture(names[2])
    flow.apply(plan)
    c = fixture(names[2])
    assert card()['faces'] == [[a],[b,c]] and card()['current'] == c
    assert all(ipc.windows()[w]['workspace']['id'] == 50 for w in (a,b,c))
    assert all(ipc.windows()[w]['pid'] == pid for w,pid in original_pids.items())
    shape = setup.Saved.capture(card(),ipc.windows())
    assert shape['faces'][1]['axis'] == 'vertical'
    assert all(abs(x-y) < .035 for x,y in zip(shape['faces'][1]['ratios'], recipe['faces'][1]['ratios']))
    passed('GIO launches only the missing app; open apps are reused across workspaces and split proportions/focus restored')

    before = deepcopy(card()); identities = {a:w['pid'] for a,w in ipc.windows().items()}
    flow = setup.Saved(ipc,Menu('0','open')); plan = flow.prepare_restore()
    assert plan.action == 'goto'; flow.apply(plan)
    assert card() == before and {a:w['pid'] for a,w in ipc.windows().items()} == identities
    passed('opening an already running saved card focuses it without duplicate apps or regrouping')

    ipc.action('unpair'); close(c); ipc.focus(b)
    delayed = root / 'delayed-app.py'
    delayed.write_text('import os,time\ntime.sleep(1.5)\nos.execv("/usr/bin/foot", '
        + repr(['/usr/bin/foot','--config','/dev/null','--app-id='+names[2],'--title='+names[2],'/usr/bin/cat']) + ')\n')
    definition(names[2], '/usr/bin/python ' + str(delayed))
    flow, plan = opening()
    request = setup.Request(root / 'runtime', env['HYPRLAND_INSTANCE_SIGNATURE']); request.start(); flow.menu.request = request
    next_request = setup.Request(root / 'runtime', env['HYPRLAND_INSTANCE_SIGNATURE'])
    timer = threading.Timer(.35, next_request.start); timer.start()
    try:
        try: flow.apply(plan)
        except setup.Cancelled: pass
        else: raise AssertionError('The new request should cancel opening')
    finally: timer.join(); request.finish(); next_request.finish()
    wait(lambda: fixture(names[2]))
    assert not ipc.status()['containers'] and all(fixture(name) for name in names)
    passed('a new menu request cancels an in-flight launch; later-arriving apps stay open and no card is created')

    close(fixture(names[2])); ipc.focus(b)
    definition(names[2], '/usr/bin/true')
    flow, plan = opening()
    before = {a:(w['workspace'],w['floating']) for a,w in ipc.windows().items()}
    try: flow.apply_open(plan,timeout=.4)
    except setup.SetupError as error: assert 'Still waiting' in str(error)
    else: raise AssertionError('Successful launcher exit is not a mapped application')
    assert not ipc.status()['containers']
    assert {a:(w['workspace'],w['floating']) for a,w in ipc.windows().items()} == before
    passed('a launcher exiting successfully without a window times out without moving or closing existing apps')
    completed = True
finally:
    config.write_text(original); ipc.call('reload')
    for target in reversed(loaded): ipc.call('plugin','unload',str(target))
    for a,w in ipc.windows().items():
        if w['class'] in names: close(a)
    if output: ipc.call('output','remove',output)
    (root / 'opening-results.json').write_text(json.dumps({'completed':completed,'checks':checks},indent=2))
