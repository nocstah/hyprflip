#!/usr/bin/env python3
"""Exercise real card movement and temporary unfolding in a disposable session."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--hyprglass', type=Path, required=True)
args = parser.parse_args()
env = environment(args.session)
project = Path(__file__).resolve().parent.parent
root = args.session.parent
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
completed = False
second_output = None


def ctl(*arguments, success=True):
    result = subprocess.run(['hyprctl', *arguments], env=env, capture_output=True, text=True, timeout=8)
    output = result.stdout.strip()
    if success and (result.returncode or output.startswith('error') or 'Lua error' in output or 'could not be loaded' in output):
        raise AssertionError((arguments, output, result.stderr))
    return output


def lua(code): return ctl('repl', code)
def status(): return json.loads(ctl('hyprflip', 'status'))
def clients(): return {w['address']: w for w in json.loads(ctl('-j', 'clients'))}
def active(): return json.loads(ctl('-j', 'activewindow')).get('address')
def workspace(): return json.loads(ctl('-j', 'activeworkspace'))['id']
def focus(address):
    ctl('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: active() == address)
def action(name): return ctl('hyprflip', name)
def card(): return next(c for c in status()['containers'] if a in c['faces'][0])


def wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.035)
    raise AssertionError('State did not settle: ' + json.dumps(status()))


def bind(key):
    # Run the exact registered callback. Binding registration is checked below;
    # wtype supplies its own keymap, unlike a physical number-row keyboard.
    lua('_G.hyprflip_test_binds[' + json.dumps(key) + ']()')
    time.sleep(.15)


def spawn(name, gtk=False, minimum=None):
    app = 'hyprflip-workflow-' + name
    if gtk:
        control = root / (name + '.command')
        control.write_text('minimum ' + ' '.join(map(str, minimum)) if minimum else '')
        command = ['python', str(project / 'tests/gtk_fixture.py'), app, str(control)]
    else:
        command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', app,
                   '--override', 'font=monospace:size=16', 'sh', '-c', 'exec cat']
    processes.append(subprocess.Popen(command, env=env | {'GDK_BACKEND': 'wayland', 'GSK_RENDERER': 'cairo'},
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(w['class'] == app for w in clients().values()))
    return next(w['address'] for w in clients().values() if w['class'] == app)


def visible():
    state = card()
    windows = clients()
    for side, face in enumerate(state['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (state['unfolded'] or side == state['active'])


def passed(name):
    checks.append(name)
    print('PASS', name, flush=True)


try:
    assert not json.loads(ctl('-j', 'plugin', 'list')), 'Use a fresh nested fixture'
    for source, name in ((project / 'build/hyprflip.so', 'hyprflip.so'),
                         (project / 'build/containers/provider/upstream/libhy3.so', 'libhy3.so'),
                         (args.hyprglass, 'hyprglass.so')):
        shutil.copy2(source, root / name)
    core = (project / 'examples/hyprflip.lua').read_text().replace(
        'os.getenv("HOME") .. "/.local/lib/hyprflip/hyprflip.so"', json.dumps(str(root / 'hyprflip.so')))
    trial = (project / 'examples/containers-trial.lua').read_text().replace(
        'os.getenv("HOME") .. "/.local/lib/hyprflip/containers/libhy3.so"', json.dumps(str(root / 'libhy3.so'))
    ).replace('local trial_workspace = "8"', 'local trial_workspace = nil')
    # Record callbacks without modifying the module under test.
    capture_binds = '''
_G.hyprflip_test_binds = {}
local original_bind = hl.bind
local function record_bind(key, callback, options)
    _G.hyprflip_test_binds[key] = callback
    return original_bind(key, callback, options)
end
local hl = setmetatable({ bind = record_bind }, { __index = hl })
'''
    configured = (original + '\n' + capture_binds + core + '\n' + trial + '\n' +
                  (project / 'examples/containers-navigation.lua').read_text() + '\n' +
                  f'hl.plugin.load({json.dumps(str(root / "hyprglass.so"))})\n' +
                  'hl.config({input={resolve_binds_by_sym=true}})\n')
    config.write_text(configured)
    ctl('reload'); assert not ctl('configerrors')
    wait(lambda: status()['container_provider'])
    assert any(m['name'] != 'FALLBACK' for m in json.loads(ctl('-j', 'monitors'))), 'The test session needs an output'
    ctl('dispatch', 'hl.dsp.focus({workspace=1})')
    a = next(w['address'] for w in clients().values() if w['class'] == 'hyprflip-front')
    b = next(w['address'] for w in clients().values() if w['class'] == 'hyprflip-back')
    for address in (a, b):
        ctl('dispatch', f'hl.dsp.window.move({{window="address:{address}",workspace="1",follow=false}})')
    c, outside = spawn('companion'), spawn('outside')
    focus(a); action('mark'); focus(b); action('pair')
    focus(c); action('mark'); focus(b); action('attach horizontal')
    members = {a, b, c}
    faces = card()['faces']
    binds = json.loads(ctl('-j', 'binds'))
    for number in range(1, 11):
        for mods, word in ((65, ''), (73, 'silently ')):
            # This Hyprland serializes Lua code bindings with keycode=0.
            description = f'Move card or window {word}to workspace {number}'
            assert len([x for x in binds if x['modmask'] == mods and x['description'] == description]) == 1
    focus(c); bind('SUPER + SHIFT + code:11')
    wait(lambda: all(clients()[w]['workspace']['id'] == 2 for w in members))
    assert workspace() == 2 and active() == c and card()['faces'] == faces
    bind('SUPER + SHIFT + ALT + code:10')
    wait(lambda: all(clients()[w]['workspace']['id'] == 1 for w in members))
    assert workspace() == 2 and active() not in members
    passed('number-row shortcuts move the whole card; silent moves leave focus on an empty source workspace')

    focus(c); bind('SUPER + SHIFT + ALT + code:11')
    assert workspace() == 1 and active() == outside
    focus(c); bind('SUPER + SHIFT + code:10')
    assert workspace() == 1 and active() == c
    focus(outside); bind('SUPER + SHIFT + code:12')
    assert clients()[outside]['workspace']['id'] == 3 and workspace() == 3
    assert all(clients()[w]['workspace']['id'] == 1 for w in members)
    bind('SUPER + SHIFT + code:10')
    passed('silent moves select a remaining source window; ordinary window shortcuts still work')

    focus(c)
    lua('hl.workspace_rule({workspace="4",layout="dwindle"})')
    bind('SUPER + SHIFT + code:13')
    assert all(clients()[w]['workspace']['id'] == 1 for w in members) and card()['faces'] == faces
    for invalid in ('workspace 0', 'workspace -1', 'workspace 2 silent junk', 'move sideways'):
        assert ctl('hyprflip', invalid, success=False).startswith('error:')
    passed('unsupported destinations and invalid movement never detach a pane')

    before = card()['box']
    bind('SUPER + SHIFT + LEFT')
    time.sleep(.5)
    left = card()['box']
    bind('SUPER + SHIFT + RIGHT')
    time.sleep(.5)
    assert card()['box'][0] != left[0] and card()['faces'] == faces and active() == c, {
        'before': before, 'left': left, 'after': card(), 'active': active(),
        'expected_focus': c, 'outside': {k:clients()[outside][k] for k in ('at','size','workspace')}}
    assert {w['address'] for w in clients().values() if w['acceptsInput']} >= {b, c, outside}
    passed('directional movement reorders the whole card beside another window')

    # Make an uneven inner split and prove folding does not reset it.
    focus(c)
    ctl('dispatch', 'hl.dsp.window.resize({x=70,y=0,relative=true})')
    time.sleep(.5)
    before = {w: clients()[w]['size'] for w in (b, c)}
    footprint = card()['box']
    bind('SUPER + CTRL + ALT + O')
    assert card()['unfolded'] and card()['faces'] == faces
    visible(); time.sleep(.5)
    assert card()['box'] == footprint
    for w in members:
        focus(w); assert active() == w
    subprocess.run(['grim', str(root / 'unfolded.png')], env=env, check=True, timeout=8)
    focus(c); bind('SUPER + CTRL + ALT + O')
    wait(lambda: not card()['unfolded']); time.sleep(.5)
    assert card()['current'] == c and card()['faces'] == faces
    assert all(abs(clients()[w]['size'][axis] - before[w][axis]) <= 2 for w in (b, c) for axis in (0, 1))
    visible()
    passed('unfold exposes all live panes in the same footprint; refolding preserves split sizes and focused face')

    front_pane = spawn('front-pane')
    focus(front_pane); action('mark'); focus(a); action('attach horizontal')
    subprocess.run(['wtype','-M','logo','-M','ctrl','-M','alt','-k','o'],env=env,check=True,timeout=5)
    wait(lambda: card()['unfolded'])
    assert [len(face) for face in card()['faces']] == [2, 2]
    visible()
    focus(front_pane); bind('SUPER + CTRL + ALT + O')
    assert not card()['unfolded'] and card()['current'] == front_pane
    action('release')
    ctl('dispatch','hl.dsp.window.close()')
    wait(lambda: front_pane not in clients())
    assert card()['faces'] == faces
    focus(c)
    passed('the real unfold shortcut handles four panes and folds onto the newly focused face')

    bind('SUPER + CTRL + ALT + O')
    bind('SUPER + SHIFT + code:11')
    assert card()['unfolded'] and all(clients()[w]['workspace']['id'] == 2 for w in members)
    ctl('reload'); assert not ctl('configerrors')
    assert card()['unfolded'] and card()['faces'] == faces
    focus(c); bind('SUPER + CTRL + ALT + F')
    assert not card()['unfolded'] and card()['active'] == 0 and active() == a
    visible()
    passed('unfolded cards survive workspace moves and reload; flip folds to the opposite face')

    monitors = json.loads(ctl('-j', 'monitors'))
    original_monitor = clients()[a]['monitor']
    ctl('output', 'create', 'headless')
    wait(lambda: len(json.loads(ctl('-j', 'monitors'))) > len(monitors))
    extra = next(m for m in json.loads(ctl('-j', 'monitors')) if m['name'] not in {m['name'] for m in monitors})
    second_output = extra['name']
    lua(f'hl.monitor({{output={json.dumps(second_output)},mode="1280x800@60",position="1280x0",scale=1.6,transform=1}})')
    lua(f'hl.workspace_rule({{workspace="6",monitor={json.dumps(second_output)},layout="hy3"}})')
    bind('SUPER + SHIFT + code:15')
    wait(lambda: all(clients()[w]['monitor'] == extra['id'] for w in members))
    assert workspace() == 6 and card()['faces'] == faces and active() == a
    time.sleep(.5)
    action('flip'); wait(lambda: not status()['animating']); visible()
    action('unfold'); assert card()['unfolded']; visible()
    time.sleep(.5)
    subprocess.run(['grim', '-o', second_output, str(root / 'unfolded-rotated.png')], env=env, check=True, timeout=8)
    action('unfold'); visible()
    bind('SUPER + SHIFT + ALT + code:11')
    wait(lambda: all(clients()[w]['monitor'] == original_monitor for w in members))
    assert workspace() == 6 and active() not in members
    focus(a)
    passed('follow and silent moves cross scaled, rotated outputs without losing panes or stealing focus')

    ctl('dispatch', 'hl.dsp.window.fullscreen({action="set",layout_aware=false})')
    assert ctl('hyprflip', 'unfold', success=False).startswith('error:')
    bind('SUPER + SHIFT + code:10')
    assert all(clients()[w]['workspace']['id'] == 2 for w in members)
    ctl('dispatch', 'hl.dsp.window.fullscreen({action="unset",layout_aware=false})')
    action('unfold'); focus(c); action('release')
    assert card()['unfolded'] and card()['faces'] == [[a], [b]]
    focus(b); action('unpair')
    assert not status()['containers']
    assert all(clients()[w]['acceptsInput'] for w in members)
    passed('fullscreen guards movement; release and unpair work while unfolded')

    # Genuine application minimum sizes, not window-rule overrides.
    ctl('dispatch', 'hl.dsp.focus({workspace=5})')
    large = spawn('large', gtk=True, minimum=(900, 550))
    time.sleep(.5)
    partner = spawn('large-partner')
    focus(large); action('mark'); focus(partner); action('pair')
    assert len(status()['containers']) == 1
    assert ctl('hyprflip', 'unfold', success=False).startswith('error:')
    assert not status()['containers'][0]['unfolded'] and active() == large
    assert not clients()[partner]['acceptsInput']
    action('unpair')
    passed('unfold rejects an arrangement below real application minimum sizes without losing the card')
    completed = True
finally:
    try:
        if second_output:
            ctl('output', 'remove', second_output)
        config.write_text(original + f'\nhl.plugin.load({json.dumps(str(root / "hyprglass.so"))})\n')
        ctl('reload'); assert not ctl('configerrors')
        config.write_text(original)
        ctl('reload'); assert not ctl('configerrors')
    finally:
        for process in processes:
            if process.poll() is None: process.terminate()
        for process in processes:
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
        output = project / 'test-results/workflows.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps({'completed': completed, 'checks_passed': checks, 'count': len(checks)}, indent=2) + '\n')
print(f'{len(checks)} workflow checks passed', flush=True)
