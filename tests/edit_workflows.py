#!/usr/bin/env python3
"""Exercise the card editor against real windows in a disposable compositor."""
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
args = parser.parse_args()
env = environment(args.session)
project, root = Path(__file__).resolve().parent.parent, args.session.parent
spec = importlib.util.spec_from_file_location('hyprflip_setup', project / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup
spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
completed = False
second_output = None


class Picker:
    def __init__(self, *answers): self.answers, self.prompts = iter(answers), []
    def choose(self, prompt, choices):
        self.prompts.append((prompt, choices))
        answer = next(self.answers)
        if answer is None: raise setup.Cancelled()
        return answer


def wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle')


def passed(message): checks.append(message); print('PASS', message, flush=True)
def active(): return ipc.data('-j', 'activewindow').get('address')
def card(front): return next(c for c in ipc.status()['containers'] if front in c['faces'][0])
def geometry(): return {a: (w['at'], w['size'], w['workspace'], w['acceptsInput']) for a, w in ipc.windows().items()}
def pair(a, b): ipc.focus(a); ipc.action('mark'); ipc.focus(b); ipc.action('pair')
def edit(anchor, *answers):
    flow = setup.Edit(ipc, Picker(*answers))
    flow.apply(flow.prepare(anchor))
def visible(c):
    windows = ipc.windows()
    for side, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (c['unfolded'] or side == c['active'])


def spawn(name, gtk=False, minimum=None):
    name = 'hyprflip-edit-' + name
    if gtk:
        control = root / (name + '.command')
        control.write_text('minimum ' + ' '.join(map(str, minimum)) if minimum else '')
        command = ['python', str(project / 'tests/gtk_fixture.py'), name, str(control)]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', name, '--title', name, 'sh', '-c', 'exec cat']
    processes.append(subprocess.Popen(command, env=env | {'GDK_BACKEND': 'wayland', 'GSK_RENDERER': 'cairo'},
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(w['class'] == name for w in ipc.windows().values()))
    return next(a for a, w in ipc.windows().items() if w['class'] == name)


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source, name in ((project / 'build/hyprflip.so', 'edit-hyprflip.so'),
                         (project / 'build/containers/provider/upstream/libhy3.so', 'edit-hy3.so')):
        shutil.copy2(source, root / name)
    config.write_text(original + '\n' + ''.join(f'hl.plugin.load({json.dumps(str(root / name))})\n'
                      for name in ('edit-hyprflip.so', 'edit-hy3.so')) + '''
if hl.plugin.hy3 then hl.config({general={layout="hy3"}}) end
if hl.plugin.hyprflip then hl.config({plugin={hyprflip={notifications=false,duration_ms=0}}}) end
hl.config({input={resolve_binds_by_sym=true}})
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    primary_output = ipc.data('-j', 'monitors')[0]['name']
    ipc.call('dispatch', 'hl.dsp.focus({workspace=3})')
    a, b, c, d = (spawn(name) for name in ('front', 'back', 'companion', 'outside'))
    pair(a, b)
    ipc.focus(d); ipc.action('mark'); ipc.focus(b); time.sleep(.4)
    for choices in ((None,), ('add', None)):
        before, boxes = deepcopy(ipc.status()), geometry()
        try: edit(b, *choices)
        except setup.Cancelled: pass
        else: raise AssertionError('Cancellation must abort the edit')
        assert ipc.status() == before and geometry() == boxes and active() == b
    passed('cancelling either edit menu preserves card, geometry, focus and pending mark')

    edit(b, 'add', c)
    assert card(a)['faces'] == [[a], [b, c]] and not card(a)['unfolded'] and active() == c
    visible(card(a))
    assert ipc.status()['marked'] is None
    picker = Picker(None)
    try: setup.Edit(ipc, picker).prepare(c)
    except setup.Cancelled: pass
    assert '2 apps on this side' in picker.prompts[0][0]
    assert [x.value for x in picker.prompts[0][1]] == ['add', 'release:' + c, 'release:' + b]
    passed('adding an app targets the back, focuses the new pane and leaves room for a third app')

    edit(c, 'release:' + c)
    assert card(a)['faces'] == [[a], [b]] and active() == c and ipc.windows()[c]['acceptsInput']
    visible(card(a))
    passed('removing a companion preserves both faces and leaves the removed app open and focused')

    ipc.focus(b); edit(b, 'add', c); ipc.focus(b)
    edit(b, 'release:' + c)
    assert card(a)['faces'] == [[a], [b]] and active() == b and ipc.windows()[c]['acceptsInput']
    visible(card(a))
    passed('the other app can be removed while focus stays on the original pane')

    ipc.focus(a); edit(a, 'add', d)
    assert card(a)['faces'] == [[a, d], [b]] and active() == d
    ipc.action('flip'); assert active() == b
    ipc.action('flip'); assert active() == d
    visible(card(a))
    passed('the front can gain a second app and flips remember the newly focused pane')

    ipc.focus(b); ipc.action('unfold'); edit(b, 'add', c)
    assert card(a)['faces'] == [[a, d], [b, c]] and card(a)['unfolded'] and active() == c
    visible(card(a))
    ipc.focus(d); edit(d, 'release:' + d)
    assert card(a)['faces'] == [[a], [b, c]] and card(a)['unfolded'] and active() == d
    visible(card(a))
    ipc.focus(a)
    picker = Picker('unpair'); flow = setup.Edit(ipc, picker)
    flow.apply(flow.prepare(a))
    assert picker.prompts[0][1][-1].label == 'Ungroup card'
    assert not ipc.status()['containers'] and all(ipc.windows()[w]['acceptsInput'] for w in (a, b, c, d))
    passed('unfolded edits retain all live panes; removing the last app is explicitly an ungroup action')

    pair(a, b); ipc.focus(b)
    flow = setup.Edit(ipc, Picker('add', c))
    selected = flow.prepare(b)
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{c}",workspace="2",follow=false}})')
    before = deepcopy(ipc.status())
    try: flow.apply(selected)
    except setup.SetupError: pass
    else: raise AssertionError('Moving a selected app must invalidate the edit')
    assert ipc.status() == before and active() == b
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{c}",workspace="3",follow=false}})')
    selected = setup.Edit(ipc, Picker('add', c)).prepare(b)
    ipc.action('flip'); before = deepcopy(ipc.status())
    try: flow.apply(selected)
    except setup.SetupError: pass
    else: raise AssertionError('Flipping while the picker is open must invalidate the edit')
    assert ipc.status() == before and active() == a
    passed('moving a selected app or flipping the card aborts a stale edit before mutation')

    module = (project / 'examples/containers-setup.lua').read_text()
    spy = '''
_G.hyprflip_edit_command = nil
local hl = setmetatable({
    dispatch = function(command) _G.hyprflip_edit_command = command end,
    dsp = setmetatable({exec_cmd = function(command) return command end}, {__index=hl.dsp}),
}, {__index=hl})
'''
    ipc.call('repl', spy + module)
    subprocess.run(['wtype', '-M', 'logo', '-M', 'ctrl', '-M', 'alt', '-k', 'c',
                    '-m', 'alt', '-m', 'ctrl', '-m', 'logo'], env=env, check=True, timeout=5)
    wait(lambda: ipc.call('repl', 'return _G.hyprflip_edit_command ~= nil') == 'true')
    assert "--edit '" + a + "'" in ipc.call('repl', 'return _G.hyprflip_edit_command')
    assert not card(a)['unfolded']
    subprocess.run(['wtype', '-M', 'logo', '-M', 'ctrl', '-M', 'alt', '-k', 'o',
                    '-m', 'alt', '-m', 'ctrl', '-m', 'logo'], env=env, check=True, timeout=5)
    wait(lambda: card(a)['unfolded'])
    binds = ipc.data('-j', 'binds')
    for key in ('C', 'O'):
        assert len([x for x in binds if x['modmask'] == 76 and x['key'].upper() == key]) == 1
    passed('the real C chord captures the focused address for editing; O still unfolds directly')
    ipc.action('unpair')

    # Import an ordinary window from dwindle on a different, rotated monitor.
    outputs = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    second_output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in outputs)
    ipc.call('repl', f'hl.monitor({{output="{second_output}",mode="1920x1080@60",position="2000x0",scale=1.5,transform=1}}); '
                    f'hl.workspace_rule({{workspace="5",monitor="{second_output}",layout="dwindle"}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{second_output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=5})')
    ipc.move(c, 5)
    ipc.focus(a); pair(a, b); ipc.focus(b)
    for choices in (('add', 'workspace:5', None), ('add', 'workspace:5', 'back', None)):
        before = deepcopy(ipc.status())
        try: edit(b, *choices)
        except setup.Cancelled: pass
        else: raise AssertionError('Remote picker cancellation must abort')
        assert ipc.status() == before and ipc.windows()[c]['workspace']['id'] == 5 and active() == b
    passed('workspace submenus and Back are cancellable without moving any app or changing focus')

    edit(b, 'add', 'workspace:5', c)
    assert card(a)['faces'] == [[a], [b, c]] and active() == c and ipc.windows()[c]['workspace']['id'] == 3
    assert ipc.data('-j', 'activeworkspace')['id'] == 3
    assert next(m for m in ipc.data('-j', 'monitors') if m['name'] == second_output)['activeWorkspace']['id'] == 5
    visible(card(a))
    ipc.focus(b); edit(b, 'release:' + c); ipc.move(c, 5)
    ipc.action('unfold'); edit(b, 'add', 'workspace:5', c)
    assert card(a)['unfolded'] and active() == c
    visible(card(a))
    ipc.focus(b); edit(b, 'release:' + c)
    assert card(a)['unfolded'] and active() == b
    ipc.action('unpair')
    passed('imports cross layouts and rotated monitors, including unfolded cards, without switching the source display')

    ipc.move(c, 5); ipc.move(d, 6); ipc.focus(a)
    flow = setup.Setup(ipc, Picker('workspace:5', c, 'workspace:6', d, 'create'))
    selected = flow.prepare(a)
    assert ipc.windows()[c]['workspace']['id'] == 5 and ipc.windows()[d]['workspace']['id'] == 6
    flow.apply(selected)
    assert card(a)['faces'] == [[a], [c, d]] and not card(a)['unfolded'] and active() == a
    assert all(ipc.windows()[w]['workspace']['id'] == 3 for w in (a, c, d))
    visible(card(a)); ipc.action('unpair')
    passed('guided creation imports the back and companion from two different workspaces only after selection')

    class RefuseAttach(setup.Hyprctl):
        def action(self, action):
            if action.startswith('attach '): raise setup.SetupError('Injected attachment failure')
            return super().action(action)
    ipc.move(c, 5); ipc.move(d, 6); ipc.focus(a)
    flow = setup.Setup(RefuseAttach(env), Picker('workspace:5', c, 'workspace:6', d, 'create'))
    try: flow.apply(flow.prepare(a))
    except setup.SetupError: pass
    else: raise AssertionError('A failed creation must roll back the imported apps')
    assert not ipc.status()['containers'] and active() == a
    assert ipc.data('-j', 'activeworkspace')['id'] == 3
    assert ipc.windows()[c]['workspace']['id'] == 5 and ipc.windows()[d]['workspace']['id'] == 6
    passed('failed creation returns both imported apps to their original workspaces')

    ipc.call('repl', f'hl.workspace_rule({{workspace="4",monitor="{primary_output}",layout="hy3"}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{primary_output}"}})')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=4})')
    big = spawn('minimum', gtk=True, minimum=(900, 550))
    time.sleep(.4)
    partner = spawn('minimum-back')
    pair(big, partner)
    extra = spawn('minimum-extra')
    ipc.focus(extra); ipc.action('mark'); ipc.focus(big)
    flow = setup.Edit(ipc, Picker('add', extra))
    selected = flow.prepare(big)
    try: flow.apply(selected)
    except setup.SetupError as error: assert 'too small' in str(error), str(error)
    else: raise AssertionError('A split below real application minimum sizes should fail')
    assert card(big)['faces'] == [[big], [partner]] and not card(big)['unfolded']
    assert active() == big and ipc.status()['marked'] == extra
    assert ipc.windows()[extra]['acceptsInput']
    visible(card(big))
    ipc.action('cancel')
    passed('a refused split preserves the existing card, pending mark and access to every app')
    ipc.move(extra, 5); ipc.focus(big)
    flow = setup.Edit(ipc, Picker('add', 'workspace:5', extra))
    try: flow.apply(flow.prepare(big))
    except setup.SetupError as error: assert 'too small' in str(error), str(error)
    else: raise AssertionError('A refused imported app must be returned')
    assert card(big)['faces'] == [[big], [partner]] and active() == big
    assert ipc.windows()[extra]['workspace']['id'] == 5 and ipc.status()['marked'] is None
    visible(card(big)); ipc.action('unpair')
    passed('a size-limited attachment returns the remote app and retains the original card')
    completed = True
finally:
    try:
        config.write_text(original)
        ipc.call('reload'); assert not ipc.call('configerrors')
        if second_output: ipc.call('output', 'remove', second_output)
    finally:
        for proc in processes:
            if proc.poll() is None: proc.terminate()
        for proc in processes:
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)
        output = project / 'test-results/edit-workflows.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps({'completed': completed, 'checks_passed': checks, 'count': len(checks)}, indent=2) + '\n')
print(f'{len(checks)} edit workflow checks passed', flush=True)
