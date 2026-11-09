#!/usr/bin/env python3
"""The face switcher and the carousel, in a disposable compositor with only the core loaded.

Cards with three or more faces spin round a carousel instead of flipping. Holding
the flip key shows a strip of face previews; the same switcher is driven here
through hyprctl hyprflip switcher open|step|pick|cancel|last, since simulated
keys do not reach bindings in a nested session.
"""
import sys, time, shutil, subprocess
from pathlib import Path
project = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(project / 'tests'), str(project / 'scripts')]
from control import environment
import workflow as w
session = Path(sys.argv[1]); root = session.parent; out = root
env = environment(session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env); procs = []
def wait(fn, what, t=8):
    d = time.monotonic() + t
    while time.monotonic() < d:
        if fn(): return
        time.sleep(.03)
    x = ipc.status()
    raise AssertionError('timed out: ' + what + ' ' + str(x.get('switcher')) + ' pending=' + str(x.get('switch_pending')) + ' active=' + str(x['containers'][0]['active']))
def ok(m): print('PASS', m, flush=True)
colours = {'a': 'c0392b', 'b': '27ae60', 'c': '2980b9', 'd': '8e44ad'}
def spawn(n):
    app = 'sw-' + n
    procs.append(subprocess.Popen(['foot', '--config', '/dev/null', '-o', f'colors-dark.background={colours[n]}', '-o', 'font=monospace:size=28',
        '--app-id', app, '--title', app, 'sh', '-c', f'echo FACE {n.upper()}; cat'], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(x['class'] == app for x in ipc.windows().values()), app)
    return next(a for a, x in ipc.windows().items() if x['class'] == app)
def st(): return ipc.status()
def card(): return st()['containers'][0]
def shot(name, output): subprocess.run(['grim', '-l', '1', '-o', output, str(out / name)], env=env, check=True, timeout=8)
config = root / 'hyprland.lua'; original = config.read_text()
try:
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    src = project / 'build/hyprflip.so'; tgt = root / 'sw.so'; shutil.copy2(src, tgt); ipc.call('plugin', 'load', str(tgt))
    config.write_text(original + f'\nhl.monitor({{output="{output}",mode="1920x1080@60",position="4000x0",scale=1}})\n'
                      'hl.workspace_rule({workspace="52",monitor="' + output + '"})\n')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch', 'hl.dsp.focus({workspace=52})')
    m = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    apps = [spawn(n) for n in 'abcd']
    line = ' '.join(f'{wd} horizontal {a} {a}:1' for wd, a in zip(['front', 'back', 'face', 'face'], apps))
    r = ipc.batch([f'hyprflip restore quiet floating 0 0 {m["x"]+360} {m["y"]+190} 1200 700 ' + line])[-1]; assert r.startswith('ok'), r
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{apps[0]}"}})')
    wait(lambda: card()['active'] == 0, 'front')
    time.sleep(.3)

    assert ipc.action('switcher open').startswith('ok')
    s = st()['switcher']; assert s['open'] and s['faces'] == 4 and s['previews'] == 4 and s['selected'] == 1, s
    time.sleep(.2); shot('open.png', output)
    ipc.action('switcher step'); assert st()['switcher']['selected'] == 2
    ipc.action('switcher step back'); ipc.action('switcher step'); ipc.action('switcher step')
    assert st()['switcher']['selected'] == 3
    time.sleep(.2); shot('step.png', output)
    assert ipc.action('switcher pick 4').startswith('ok')
    wait(lambda: card()['active'] == 3, 'pick 4'); assert not st()['switcher']['open']
    ok('IPC switcher opens with four previews, steps and picks face 4')

    assert ipc.action('switcher last').startswith('ok'); wait(lambda: card()['active'] == 0, 'last face')
    assert ipc.action('switcher last').startswith('ok'); wait(lambda: card()['active'] == 3, 'last face again')
    ok('going to the last face toggles between the two latest faces')
    assert ipc.action('switcher open').startswith('ok'); assert st()['switcher']['selected'] == 0
    ipc.action('switcher cancel'); assert not st()['switcher']['open'] and card()['active'] == 3
    ipc.action('switcher open'); ipc.call('dispatch', 'hl.dsp.focus({workspace=53})')
    wait(lambda: not st()['switcher']['open'], 'workspace change closes'); ipc.call('dispatch', 'hl.dsp.focus({workspace=52})')
    ok('cancel and leaving the workspace put the switcher away without turning')
    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=1600}}})')
    assert st()['transition'] == 'flip'
    assert ipc.action('switcher open').startswith('ok'); assert ipc.action('switcher pick 2').startswith('ok')
    wait(lambda: 0 < st()['progress'] < 1, 'the turn to start')
    assert st()['last_fallback'] == '', st()['last_fallback']
    wait(lambda: card()['active'] == 1 and st()['progress'] in (0, 1), 'animated pick')
    ok('a pick turns the card, animated, with no fallback')
finally:
    for p in procs: p.terminate()
