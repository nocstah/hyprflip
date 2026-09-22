#!/usr/bin/env python3
"""Exercise guided creation with real windows in a disposable compositor."""
import argparse
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
spec = importlib.util.spec_from_file_location('hyprflip_setup', project / 'scripts/workflow.py')
setup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup
spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
completed = False


class Picker:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        if answer is None: raise setup.Cancelled()
        return answer


def wait(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle')


def passed(message): checks.append(message); print('PASS', message, flush=True)
def create(front, *choices):
    flow = setup.Setup(ipc, Picker(*choices))
    selected = flow.prepare(front)
    flow.apply(selected)
def card(front): return next(c for c in ipc.status()['containers'] if front in c['faces'][0])
def ordinary(): return {a: (w['at'], w['size'], w['workspace'], w['grouped']) for a,w in ipc.windows().items()}


def spawn(name, gtk=False, minimum=None):
    name = 'hyprflip-setup-' + name
    if gtk:
        control = root / (name + '.command')
        control.write_text('minimum ' + ' '.join(map(str, minimum)) if minimum else '')
        command = ['python', str(project / 'tests/gtk_fixture.py'), name, str(control)]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', name, '--title', name, 'sh', '-c', 'exec cat']
    processes.append(subprocess.Popen(command, env=env | {'GDK_BACKEND': 'wayland', 'GSK_RENDERER': 'cairo'},
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(w['class'] == name for w in ipc.windows().values()))
    return next(a for a,w in ipc.windows().items() if w['class'] == name)


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source, name in ((project / 'build/hyprflip.so', 'setup-hyprflip.so'),
                         (project / 'build/containers/provider/upstream/libhy3.so', 'setup-hy3.so')):
        shutil.copy2(source, root / name)
    config.write_text(original + '\n' + ''.join(f'hl.plugin.load({json.dumps(str(root / name))})\n'
                      for name in ('setup-hyprflip.so', 'setup-hy3.so')) + '''
if hl.plugin.hy3 then hl.config({general={layout="hy3"}}) end
if hl.plugin.hyprflip then hl.config({plugin={hyprflip={notifications=false,duration_ms=0}}}) end
''')
    ipc.call('reload'); assert not ipc.call('configerrors')
    if not any(m['name'] != 'FALLBACK' for m in ipc.data('-j', 'monitors')):
        ipc.call('output', 'create', 'headless')
    ipc.call('dispatch', 'hl.dsp.focus({workspace=1})')
    a, b, c = spawn('front'), spawn('back'), spawn('companion')
    ipc.focus(a); time.sleep(.4)
    for choices in ((None,), (b, None)):
        before = ordinary()
        ipc.focus(c); ipc.action('mark'); ipc.focus(a)
        try: create(a, *choices)
        except setup.Cancelled: pass
        else: raise AssertionError('Cancellation should abort setup')
        assert ordinary() == before and not ipc.status()['containers']
        assert ipc.status()['marked'] == c and ipc.data('-j', 'activewindow')['address'] == a
    ipc.action('cancel')
    passed('cancelling either stage preserves real window layout, focus and pending mark')

    create(a, b, 'create')
    assert card(a)['faces'] == [[a], [b]] and not card(a)['unfolded']
    assert card(a)['current'] == a and ipc.data('-j', 'activewindow')['address'] == a
    assert ipc.windows()[a]['acceptsInput'] and not ipc.windows()[b]['acceptsInput']
    ipc.action('unfold')
    assert card(a)['unfolded']
    assert ipc.windows()[a]['acceptsInput'] and ipc.windows()[b]['acceptsInput']
    ipc.focus(b); ipc.action('unfold')
    assert card(a)['current'] == b and not card(a)['unfolded']
    ipc.action('unpair')
    passed('one reverse app finishes folded on the front; explicit unfolding and focused-face refolding work')

    ipc.focus(a); create(a, b, c, 'create')
    assert card(a)['faces'] == [[a], [b, c]] and not card(a)['unfolded']
    assert card(a)['current'] == a and ipc.data('-j', 'activewindow')['address'] == a
    assert ipc.windows()[a]['acceptsInput'] and not any(ipc.windows()[w]['acceptsInput'] for w in (b, c))
    ipc.action('unfold')
    assert card(a)['unfolded']
    assert all(ipc.windows()[w]['acceptsInput'] for w in (a, b, c))
    ipc.focus(c); ipc.action('unfold')
    assert card(a)['current'] == c and not card(a)['unfolded']
    ipc.action('unpair')
    ipc.focus(a); create(a, b, c, 'create')
    assert not card(a)['unfolded'] and card(a)['current'] == a
    assert ipc.data('-j', 'activewindow')['address'] == a
    passed('two reverse apps finish folded on the front, including after ungrouping and guided recreation')

    # The shipped O callback must take the immediate native path for a card,
    # and capture the front's address when dispatching the helper for setup.
    module = (project / 'examples/containers-setup.lua').read_text()
    spy = '''
_G.hyprflip_setup_command = nil
local hl = setmetatable({
    bind = function(key, fn, options)
        if key == "SUPER + CTRL + ALT + O" then _G.hyprflip_setup_key = fn end
    end,
    unbind = function(key) end,
    dispatch = function(command) _G.hyprflip_setup_command = true end,
    dsp = setmetatable({exec_cmd = function(command)
        _G.hyprflip_setup_argv = command
        return command
    end}, {__index=hl.dsp}),
}, {__index=hl})
'''
    ipc.call('repl', spy + module)
    ipc.focus(a); ipc.call('repl', '_G.hyprflip_setup_key()')
    assert card(a)['unfolded']
    ipc.call('repl', '_G.hyprflip_setup_key()')
    assert not card(a)['unfolded']
    assert ipc.call('repl', 'return _G.hyprflip_setup_command == nil') == 'true'
    ipc.action('unpair'); ipc.focus(a)
    ipc.call('repl', '_G.hyprflip_setup_key()')
    assert ipc.call('repl', 'return _G.hyprflip_setup_command') == 'true'
    assert a in ipc.call('repl', 'return _G.hyprflip_setup_argv')
    passed('the shipped O callback unfolds and folds existing cards directly and captures the ungrouped front for setup')

    flow = setup.Setup(ipc, Picker(b, 'create'))
    selected = flow.prepare(a)
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{b}",workspace="2",follow=false}})')
    try: flow.apply(selected)
    except setup.SetupError: pass
    else: raise AssertionError('Moving a selected app must invalidate the selection')
    assert not ipc.status()['containers'] and ipc.status()['marked'] is None
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{b}",workspace="1",follow=false}})')
    passed('moving a chosen application while selecting aborts before any card or mark is created')

    class RefuseAttach(setup.Hyprctl):
        attachments = 0
        def action(self, action):
            if action.startswith('attach '):
                self.attachments += 1
                if self.attachments == 2:
                    raise setup.SetupError('The selected companion can no longer be attached.')
            return super().action(action)
    d = spawn('third-back')
    ipc.move(d, 5)
    ipc.focus(a)
    refused = setup.Setup(RefuseAttach(env), Picker(b, c, 'workspace:5', d))
    try: refused.apply(refused.prepare(a))
    except setup.SetupError as error: assert 'can no longer be attached' in str(error)
    else: raise AssertionError('Attachment failure should be reported')
    assert not ipc.status()['containers'] and ipc.status()['marked'] is None
    assert all(ipc.windows()[w]['acceptsInput'] for w in (a, b, c))
    assert ipc.windows()[d]['workspace']['id'] == 5
    assert ipc.data('-j', 'activewindow')['address'] == a
    passed('a third-app attachment failure dissolves only the new card, returns the remote app and leaves every app accessible')

    # Creation needs room for one face, even if simultaneous display cannot fit.
    ipc.call('dispatch', 'hl.dsp.focus({workspace=4})')
    big = spawn('minimum', gtk=True, minimum=(900, 550))
    time.sleep(.4)
    partner = spawn('minimum-back')
    ipc.focus(big)
    create(big, partner, 'create')
    assert card(big)['faces'] == [[big], [partner]] and not card(big)['unfolded']
    assert card(big)['current'] == big and ipc.data('-j', 'activewindow')['address'] == big
    assert ipc.windows()[big]['acceptsInput'] and not ipc.windows()[partner]['acceptsInput']
    try: ipc.action('unfold')
    except setup.SetupError: pass
    else: raise AssertionError('These minimum sizes should prevent unfolding')
    assert card(big)['faces'] == [[big], [partner]] and not card(big)['unfolded']
    ipc.action('unpair')
    passed('creation succeeds without an unfold-space error; a later refused unfold retains the folded card')
    completed = True
finally:
    try:
        config.write_text(original)
        ipc.call('reload'); assert not ipc.call('configerrors')
    finally:
        for proc in processes:
            if proc.poll() is None: proc.terminate()
        for proc in processes:
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)
        output = project / 'test-results/setup-workflows.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps({'completed': completed, 'checks_passed': checks, 'count': len(checks)}, indent=2) + '\n')
print(f'{len(checks)} guided setup workflow checks passed', flush=True)
