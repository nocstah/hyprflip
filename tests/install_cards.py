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
output = None


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
    # Mirror a typical Omarchy desktop: 4K at 1.5x, and dwindle's smart and
    # preserved splits, under which a dissolved card's tiles reflow.
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + f'''
hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})
hl.workspace_rule({{workspace="95",monitor="{output}"}})
hl.config({{animations={{enabled=false}},general={{gaps_in=14,gaps_out=24}},
    dwindle={{smart_split=true,preserve_split=true,force_split=2}}}})
''')
    ipc.call('reload')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    out = install()
    assert 'hyprflip' in {p['name'] for p in ipc.data('-j', 'plugin', 'list')}, out
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    passed('a fresh install loads the plugin from the disposable home')

    ipc.call('dispatch', 'hl.dsp.focus({workspace=95})')
    # A neighbouring tile, so the card's place in the layout matters.
    neighbor = spawn('neighbor')
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

    # With smart_split, re-inserted tiles split whatever is under the cursor.
    nx, ny = ipc.windows()[neighbor]['at']; nw, nh = ipc.windows()[neighbor]['size']
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={nx + nw // 2},y={ny + nh // 4}}})')
    out = install()
    assert 'Keeping 2 open card(s)' in out, out
    time.sleep(.3)
    after = {tuple(x for f in card['faces'] for x in f): (shape(card), card['box']) for card in ipc.status()['containers']}
    assert set(after) == set(before), (before, after)
    for members, (described, box) in before.items():
        assert after[members][0] == described, (described, after[members][0])
        assert all(abs(p - q) <= 4 for p, q in zip(after[members][1], box)), (described['floating'], box, after[members][1])
    passed('an update keeps a tiled 70/30 card beside its neighbour and an unfolded floating card exactly as they were')

    # Dwindle can reflow a workspace while a tiled card is briefly separate
    # tiles. Displace the card deliberately; the installer's correction must
    # put it back in its saved tile.
    import card_restore
    tiled = next(c for c in ipc.status()['containers'] if not c['floating'])
    line, saved = card_restore.describe(tiled), tuple(tiled['box'])
    ipc.focus(tiled['current'])
    for message in ('togglesplit', 'swapsplit'):
        ipc.call('dispatch', f'hl.dsp.layout("{message}")')
    displaced = tuple(next(c for c in ipc.status()['containers'] if not c['floating'])['box'])
    assert sum(abs(p - q) for p, q in zip(displaced, saved)) > 50, (saved, displaced)
    os.environ.update({k: v for k, v in env.items() if k in ('HYPRLAND_INSTANCE_SIGNATURE', 'XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY')})
    card_restore.settle(line)
    settled = tuple(next(c for c in ipc.status()['containers'] if not c['floating'])['box'])
    assert all(abs(p - q) <= 4 for p, q in zip(settled, saved)), (saved, displaced, settled)
    passed('a tiled card displaced by a layout reflow is returned to its saved tile')

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
    try:
        if output: ipc.call('output', 'remove', output)
    except Exception: pass
    (root / 'install-cards-results.json').write_text(json.dumps(checks, indent=2))
