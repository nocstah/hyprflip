#!/usr/bin/env python3
"""Real input and output lifecycle checks for hold-to-peek, in a disposable session."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
args = parser.parse_args()
env = environment(args.session)
root, project = args.session.parent, Path(__file__).resolve().parent.parent
config = root / 'hyprland.lua'; original = config.read_text()
loaded, processes, checks = [], [], []
output, completed = None, False


def ctl(*args):
    result = subprocess.run(['hyprctl', *map(str, args)], env=env, capture_output=True, text=True, timeout=8)
    reply = result.stdout.strip()
    if result.returncode or reply.startswith('error') or 'Lua error' in reply: raise AssertionError((args, reply, result.stderr))
    return reply
def data(*args): return json.loads(ctl(*args))
def state(): return data('hyprflip', 'status')
def card(): return state()['containers'][0]
def action(value): return ctl('hyprflip', value)
def lua(value): return ctl('repl', value)
def focus(address): ctl('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
def wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.012)
    raise AssertionError('Did not settle: ' + json.dumps(state()))
def settled(): wait(lambda: not state()['animating'])
def passed(message): checks.append(message); print('PASS', message, flush=True)
def setting(mode, duration=420): lua(f'hl.config({{plugin={{hyprflip={{transition="{mode}",duration_ms={duration},notifications=false}}}}}})')
def type_keys(*keys):
    subprocess.run(['wtype', *keys], env=env, check=True, timeout=8, capture_output=True)
def held(*keys):
    process = subprocess.Popen(['wtype', '-M', 'ctrl', '-M', 'alt', '-M', 'logo', '-P', 'space', *keys], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    processes.append(process)
    return process


try:
    assert not data('-j', 'plugin', 'list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('peek-' + source.name); shutil.copy2(source, target)
        ctl('plugin', 'load', target); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"') + '''
-- The synthetic wtype keyboard has its own keymap. Physical bindings retain
-- the user's existing resolver setting; this override is only in this fixture.
hl.config({input={resolve_binds_by_sym=true}})
hl.bind("SUPER + CTRL + ALT + SPACE", function() hl.plugin.hyprflip.peek() end)
''')
    ctl('reload'); assert not ctl('configerrors')
    busy = {w['id'] for w in data('-j', 'workspaces')}
    workspace = next(n for n in range(30, 90) if n not in busy and n + 1 not in busy)
    outputs = {m['name'] for m in data('-j', 'monitors')}; ctl('output', 'create', 'headless')
    output = next(m['name'] for m in data('-j', 'monitors') if m['name'] not in outputs)
    lua(f'hl.monitor({{output="{output}",mode="1920x1200@60",position="2000x0",scale=1}})')
    ctl('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ctl('dispatch', f'hl.dsp.focus({{workspace={workspace}}})')
    clients = {w['class']: w['address'] for w in data('-j', 'clients')}
    a, b = clients['hyprflip-front'], clients['hyprflip-back']
    for address in (a, b): ctl('dispatch', f'hl.dsp.window.move({{window="address:{address}",workspace="{workspace}",follow=false}})')
    focus(a); action('mark'); focus(b); action('pair'); focus(a)
    time.sleep(.6)
    for mode in state()['transition_modes']:
        setting(mode)
        for source in (0, 1):
            focus(a if source == 0 else b); time.sleep(.12)
            action('peek'); settled()
            assert state()['peeking'] and card()['active'] == 1 - source, state()
            action('peek end'); settled()
            assert not state()['peeking'] and card()['active'] == source, state()
            action('peek end'); assert card()['active'] == source
        passed(mode + ': hold shows the other face, release returns, duplicate release is harmless')
    setting('flip', 1200); focus(a); time.sleep(.2)
    action('peek'); wait(lambda: state()['progress'] > .2)
    progress = state()['progress']; action('peek end')
    assert abs(state()['progress'] - progress) < .15
    settled(); assert card()['active'] == 0
    passed('early release reverses the same animation without snapping')

    setting('flip'); focus(a)
    process = held('-s', '800', '-m', 'logo', '-m', 'alt', '-m', 'ctrl', '-s', '150', '-p', 'space')
    wait(lambda: state()['peeking']); wait(lambda: not state()['animating'])
    assert card()['active'] == 1
    process.wait(timeout=5); assert process.returncode == 0, process.stderr.read()
    wait(lambda: not state()['peeking']); settled(); assert card()['active'] == 0
    passed('actual shortcut release returns even when all modifiers are released before Space')

    focus(a); action('peek'); settled(); type_keys('x')
    wait(lambda: not state()['peeking']); action('peek end'); settled(); assert card()['active'] == 1
    passed('typing on the peeked side keeps it active after release')
    focus(a); action('peek'); settled(); focus(a); action('peek end'); settled(); assert card()['current'] == a
    passed('explicit focus replaces the peek; releasing cannot pull focus back')

    focus(a); action('unfold')
    rejected = subprocess.run(['hyprctl', 'hyprflip', 'peek'], env=env, capture_output=True, text=True)
    assert 'already visible' in rejected.stdout
    assert card()['unfolded'] and not state()['peeking']; action('unfold')
    passed('unfolded cards explain that both sides are already visible')

    focus(a); action('peek'); settled(); ctl('dispatch', f'hl.dsp.focus({{workspace={workspace+1}}})')
    assert not state()['peeking']; action('peek end'); assert data('-j', 'activeworkspace')['id'] == workspace+1
    ctl('dispatch', f'hl.dsp.focus({{workspace={workspace}}})'); focus(a)
    action('peek'); ctl('reload'); assert not state()['peeking'] and not state()['animating']; assert not ctl('configerrors')
    passed('workspace changes and configuration reload cancel the temporary return')

    commands = root / 'peek-gtk.commands'
    process = subprocess.Popen(['python', str(project / 'tests/gtk_fixture.py'), 'hyprflip-peek-popup', str(commands)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(w['class'] == 'hyprflip-peek-popup' for w in data('-j', 'clients')))
    c = next(w['address'] for w in data('-j', 'clients') if w['class'] == 'hyprflip-peek-popup')
    focus(c); action('mark'); focus(b); action('attach horizontal'); focus(a)
    action('peek'); settled(); commands.write_text('popup')
    wait(lambda: not state()['peeking']); action('peek end'); assert card()['active'] == 1
    commands.write_text('dismiss'); time.sleep(.25)
    passed('a real application popup cancels the return and stays usable')
    focus(a); action('peek'); settled(); process.terminate(); process.wait(timeout=5)
    wait(lambda: not state()['peeking']); assert len(card()['faces'][1]) == 1
    passed('closing a pane while peeking keeps the remaining card valid')

    setting('instant'); focus(a); action('flip'); time.sleep(.6); action('flip'); time.sleep(.6)
    setting('portal', 1200); focus(a); action('peek'); wait(lambda: state()['progress'] > .2)
    ctl('output', 'remove', output); output = None
    wait(lambda: not state()['animating'] and not state()['peeking'])
    assert len(state()['containers']) == 1
    for address in (a, b):
        focus(address)
        assert card()['current'] == address
        assert next(w for w in data('-j', 'clients') if w['address'] == address)['acceptsInput']
    action('peek end'); assert not ctl('configerrors')
    passed('disconnecting the card monitor mid-transition migrates the intact card and clears the effect')

    # These are virtual outputs only. This exercises DPMS, not physical suspend.
    focus(a); action('peek')
    ctl('dispatch', 'hl.dsp.dpms({action="disable"})')
    wait(lambda: all(not m['dpmsStatus'] for m in data('-j', 'monitors')))
    time.sleep(.4)
    ctl('dispatch', 'hl.dsp.dpms({action="enable"})')
    wait(lambda: all(m['dpmsStatus'] for m in data('-j', 'monitors')))
    settled(); action('peek end'); settled()
    assert len(state()['containers']) == 1
    passed('virtual output power off/on settles motion and leaves the card usable')
    focus(a); action('peek'); settled()
    ctl('plugin', 'unload', loaded[-1]); loaded.pop()
    assert all(not w['hidden'] for w in data('-j', 'clients') if w['address'] in (a, b))
    passed('unloading while holding releases the card without hidden survivors')
    core = root / 'peek-hyprflip.so'
    ctl('plugin', 'load', core); loaded.append(core)
    lua('hl.config({general={layout="dwindle"}})'); time.sleep(.4)
    setting('instant'); focus(a); action('mark'); focus(b); action('pair'); focus(a)
    assert len(state()['pairs']) == 1 and not state()['containers']
    action('peek'); assert state()['peeking'] and state()['pairs'][0]['current'] == b
    action('peek end'); assert state()['pairs'][0]['current'] == a
    action('peek'); type_keys('x'); action('peek end')
    assert not state()['peeking'] and state()['pairs'][0]['current'] == b
    action('unpair')
    passed('native two-window pairs also return on release and keep the other side after typing')
    completed = True
finally:
    for process in processes:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    config.write_text(original); ctl('reload')
    for target in reversed(loaded): ctl('plugin', 'unload', target)
    if output: ctl('output', 'remove', output)
    (root / 'peek-results.json').write_text(json.dumps({'completed': completed, 'checks': checks}, indent=2))
