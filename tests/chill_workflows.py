#!/usr/bin/env python3
"""Exercise automatic Chill, guided tiling and rollback in a disposable compositor."""
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
parser.add_argument('--engine', type=Path, required=True)
args = parser.parse_args()
root = args.session.parent
project = Path(__file__).resolve().parent.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state')}
spec = importlib.util.spec_from_file_location('hf_setup', project / 'scripts/workflow.py')
setup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = setup; spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
loaded, processes, checks = [], [], []
installed = root / 'chill-installed'


class Picker:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        if answer is None: raise setup.Cancelled()
        assert answer in [c.value for c in choices], (prompt, choices, answer)
        return answer


def lua(code): return ipc.call('repl', code)
def wait(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle')
def protect(workspace): return lua(f'return hl.plugin.hyprflip.protects_workspace({workspace})') == 'true'
def passed(message): checks.append(message); print('PASS', message, flush=True)
def spawn(name):
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', name, 'sh', '-c', 'exec cat'],
                     env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(w['class'] == name for w in ipc.windows().values()))
    return next(a for a,w in ipc.windows().items() if w['class'] == name)


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = installed / ('containers/libhy3.so' if source.name == 'libhy3.so' else 'hyprflip.so')
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    lua('hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    a,b = [w['address'] for w in ipc.windows().values() if w['class'] in ('hyprflip-front','hyprflip-back')]
    ipc.call('dispatch', 'hl.dsp.focus({workspace=1})')
    for w in (a,b):
        ipc.call('dispatch', f'hl.dsp.window.tag({{window="address:{w}",tag="-chillmode"}})')
        ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{w}",action="disable"}})')
        ipc.move(w,1)
    ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{a}",action="enable"}})')
    time.sleep(.2)
    plain = deepcopy(ipc.windows()[a])
    ipc.tile(plain); ipc.restore_float(plain); time.sleep(.2)
    restored = ipc.windows()[a]
    assert restored['floating'] and restored['at'] == plain['at'] and restored['size'] == plain['size']
    ipc.tile(restored)
    passed('ordinary floating apps regain their original size and position after a failed handoff')
    home = root / 'home'; (home / '.local/state').mkdir(parents=True, exist_ok=True)
    engine = root / 'chillmode.lua'
    engine.write_text(args.engine.read_text().replace('os.getenv("HOME")', json.dumps(str(home))))
    engine_code = ('CHILLMODE_OPTS={auto=true,auto_max=3,notify=false,keybind="",key_hide="",key_restore="",hide=false}; '
                   f'dofile({json.dumps(str(engine))})')
    lua(engine_code)
    wait(lambda: all(ipc.windows()[w]['floating'] for w in (a,b)))
    ipc.focus(a)
    before = deepcopy(ipc.windows())
    try: setup.Setup(ipc, Picker(None)).prepare(a)
    except setup.Cancelled: pass
    else: raise AssertionError('App selection must be cancellable')
    assert all(ipc.windows()[w]['floating'] and ipc.windows()[w]['at'] == before[w]['at'] for w in (a,b))
    assert not protect(1)
    passed('cancelling app selection preserves floating apps and leaves no reservation')

    flow = setup.Setup(ipc, Picker(b)); selected = flow.prepare(a)
    flow.apply(selected)
    assert protect(1) and ipc.status()['containers'][0]['faces'] == [[a],[b]]
    assert all(not any(t.rstrip('*') == 'chillmode' for t in ipc.windows()[w]['tags']) for w in (a,b))
    config.write_text(config.read_text() + '\n' + engine_code + '\n')
    result = subprocess.run(['python', str(project / 'scripts/update-containers.py'), '--library-root', str(installed),
                             '--state-dir', str(root / 'chill-updates')], env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert protect(1) and ipc.status()['containers'][0]['faces'] == [[a],[b]]
    assert all(ipc.windows()[w]['floating'] for w in (a,b))
    passed('a live plugin upgrade preserves the card while automatic Chill remains enabled')
    for _ in range(3):
        lua('chillmode.toggle(1)')
        time.sleep(.12)
        assert all(ipc.windows()[w]['floating'] for w in (a,b))
    c = spawn('hyprflip-chill-extra'); time.sleep(.15)
    assert not ipc.windows()[c]['floating']
    processes[-1].terminate(); processes[-1].wait(timeout=5)
    time.sleep(.15)
    assert all(ipc.windows()[w]['floating'] for w in (a,b))
    passed('guided creation takes apps out of Chill; auto, manual toggle and open/close preserve the card')

    ipc.focus(a); ipc.action('workspace 8')
    time.sleep(.2)
    assert protect(8) and not protect(1)
    assert all(ipc.windows()[w]['floating'] and ipc.windows()[w]['workspace']['id'] == 8 for w in (a,b))
    ipc.call('reload'); assert not ipc.call('configerrors')
    lua('CHILLMODE_OPTS={auto=true,auto_max=3,notify=false,keybind="",hide=false}; '
        f'dofile({json.dumps(str(engine))})')
    time.sleep(.2)
    assert all(ipc.windows()[w]['floating'] for w in (a,b))
    ipc.focus(a); ipc.action('unpair')
    assert not protect(8)
    c = spawn('hyprflip-chill-remote')
    wait(lambda: all(ipc.windows()[w]['floating'] for w in (a,b,c)))
    passed('movement and reload preserve the card; ungrouping lets automatic Chill resume')

    # One selected app from another workspace, then a deliberately rejected pair.
    ipc.move(c, 9); ipc.focus(a); time.sleep(.2)
    before = deepcopy(ipc.windows())
    flow = setup.Setup(ipc, Picker('workspace:9', c, 'create'))
    selected = flow.prepare(a)
    real_focused = ipc.focused
    def reject_pair(*operations):
        if any(action == 'pair' for _, action in operations): raise setup.SetupError('Injected pair failure')
        return real_focused(*operations)
    ipc.focused = reject_pair
    try: flow.apply(selected)
    except setup.SetupError as error: assert 'Injected' in str(error), error
    else: raise AssertionError('Expected a pair rejection')
    finally: ipc.focused = real_focused
    for w in (a,c):
        current = ipc.windows()[w]
        assert current['floating'] and current['workspace'] == before[w]['workspace']
        assert current['at'] == before[w]['at'] and current['size'] == before[w]['size'], (current,before[w])
        assert any(t.rstrip('*') == 'chillmode' for t in current['tags']) == any(t.rstrip('*') == 'chillmode' for t in before[w]['tags'])
    assert not protect(8) and not protect(9)
    passed('failed creation restores imported apps, Chill tags and floating geometry, then releases reservations')

    ipc.action('reserve 8 expiry-test 1'); assert protect(8)
    wait(lambda: not protect(8))
    passed('a helper that disappears cannot leave a permanent workspace reservation')

    lua('chillmode.hold_workspace(8,120)')
    for w in (a,b): ipc.tile(ipc.windows()[w])
    core = next(p for p in loaded if p.name == 'hyprflip.so')
    ipc.call('plugin','unload',str(core)); loaded.remove(core)
    extra = spawn('hyprflip-chill-hold'); time.sleep(.2)
    assert all(not ipc.windows()[w]['floating'] for w in (a,b,extra))
    lua('chillmode.hold_workspace(8,0)')
    processes[-1].terminate(); processes[-1].wait(timeout=5)
    wait(lambda: all(ipc.windows()[w]['floating'] for w in (a,b)))
    passed('upgrade holds protect windows while the core is unloaded and release back to normal Chill behavior')
    (root / 'chill-results.json').write_text(json.dumps(checks, indent=2))
finally:
    for process in processes:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    try:
        lua('if chillmode then chillmode.unload() end')
        config.write_text(original); ipc.call('reload')
        for target in reversed(loaded): ipc.call('plugin', 'unload', str(target))
    except (setup.SetupError, subprocess.TimeoutExpired): pass
