#!/usr/bin/env python3
"""Updating the core with scripts/install.py keeps open native cards, in a disposable compositor."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from control import environment

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
args = parser.parse_args()
root = args.session.parent
home = root / 'install-home'
(home / '.config/hypr').mkdir(parents=True, exist_ok=True)
(home / '.config/hypr/hyprland.lua').write_text('-- disposable installer test configuration\n')
env = environment(args.session) | {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
                                   'XDG_STATE_HOME': str(home / '.local/state'), 'XDG_DATA_HOME': str(home / '.local/share')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library = home / '.local/lib/hyprflip/hyprflip.so'


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.05)
    raise AssertionError(ipc.status())


def spawn(name):
    app = 'hyprflip-install-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, 'cat'], env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def install():
    result = subprocess.run(['python3', str(project / 'scripts/install.py')], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (result.stdout, result.stderr)
    return result.stdout


def shape(card):
    keys = ('faces', 'active', 'unfolded', 'floating', 'layouts', 'native_group')
    described = {k: card.get(k) for k in keys}
    described['layouts'] = [{'axis': l['axis'], 'focused': l['focused'], 'ratios': [round(r, 3) for r in l['ratios']]}
                            for l in card['layouts']]
    return described


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    config.write_text(original + '\nhl.config({animations={enabled=false},general={gaps_in=14,gaps_out=24}})\n')
    ipc.call('reload')
    out = install()
    assert 'hyprflip' in {p['name'] for p in ipc.data('-j', 'plugin', 'list')}, out
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    passed('a fresh install loads the plugin from the disposable home')

    ipc.call('dispatch', 'hl.dsp.focus({workspace=95})')
    a, b, c = spawn('front'), spawn('back'), spawn('notes')
    ipc.focused((a, 'mark'), (b, 'card')); ipc.focused((c, 'mark'), (b, 'attach horizontal'))
    ipc.focus(b)
    ipc.action(f'arrange horizontal {b}:0.7 {c}:0.3')
    d, e = spawn('float-front'), spawn('float-back')
    for x in (d, e): ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{x}",action="enable"}})')
    ipc.focused((d, 'mark'), (e, 'card'))
    ipc.call('eval', f'hl.plugin.hyprflip.card_place("{d}", 300, 150, 700, 500)')
    ipc.focus(d); ipc.action('unfold')
    time.sleep(.3)
    before = {tuple(x for f in card['faces'] for x in f): (shape(card), card['box']) for card in ipc.status()['containers']}
    assert len(before) == 2 and any(s['floating'] and s['unfolded'] for s, _ in before.values()), before

    out = install()
    assert 'Keeping 2 open card(s)' in out, out
    time.sleep(.3)
    after = {tuple(x for f in card['faces'] for x in f): (shape(card), card['box']) for card in ipc.status()['containers']}
    assert set(after) == set(before), (before, after)
    for members, (described, box) in before.items():
        assert after[members][0] == described, (described, after[members][0])
        if described['floating']:
            assert all(abs(p - q) <= 2 for p, q in zip(after[members][1], box)), (box, after[members][1])
    passed('an update keeps a tiled 70/30 card and an unfolded floating card exactly as they were')

    ipc.call('plugin', 'unload', str(library))
    assert 'hyprflip' not in {p['name'] for p in ipc.data('-j', 'plugin', 'list')}
    passed('the disposable install unloads cleanly')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    try:
        if any(p['name'] == 'hyprflip' for p in ipc.data('-j', 'plugin', 'list')):
            ipc.call('plugin', 'unload', str(library))
    except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    (root / 'install-cards-results.json').write_text(json.dumps(checks, indent=2))
