#!/usr/bin/env python3
"""Reproduce expired native targets, then require subsequent windows to work."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--provider', type=Path, default=Path('build/containers/provider/upstream/libhy3.so'))
args = parser.parse_args()
env = environment(args.session)
root = args.session.parent
config = root / 'hyprland.lua'
original = config.read_text()
processes, loaded, checks = [], [], []


def ctl(*arguments):
    p = subprocess.run(['hyprctl', *arguments], env=env, capture_output=True, text=True, timeout=7)
    reply = p.stdout.strip()
    if p.returncode or reply.startswith('error') or 'Lua error' in reply:
        raise AssertionError((arguments, reply, p.stderr))
    return reply
def data(*args): return json.loads(ctl(*args))
def clients(): return {w['address']: w for w in data('-j', 'clients')}
def action(name): return ctl('hyprflip', name)
def focus(address): ctl('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
def wait(predicate):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('Windows did not settle')
def floating(address, enabled):
    ctl('dispatch', f'hl.dsp.window.float({{window="address:{address}",action="{"enable" if enabled else "disable"}"}})')
def layout(name):
    config.write_text(original.replace('layout="dwindle"', f'layout="{name}"'))
    ctl('reload')
    assert not ctl('configerrors')
    wait(lambda: all(w['tiledLayout'] == name for w in data('-j', 'workspaces') if w['id'] == 1))
def spawn():
    name = 'hyprflip-stale-' + str(len(processes))
    p = subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', name, 'sh', '-c', 'exec cat'],
                         env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(p)
    wait(lambda: any(w['class'] == name for w in clients().values()))
    address = next(a for a, w in clients().items() if w['class'] == name)
    wait(lambda: all(v > 30 for v in clients()[address]['size']))
    return p, address
def probe():
    p, address = spawn()
    assert not clients()[address]['floating']
    p.terminate(); p.wait(timeout=5)
    wait(lambda: address not in clients())
def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


try:
    assert not data('-j', 'plugin', 'list'), 'Use a fresh disposable compositor'
    for source, name in ((args.provider, 'stale-hy3.so'),
                         (Path('build/containers/core/hyprflip.so'), 'stale-core.so')):
        target = root / name
        shutil.copy2(source, target)
        ctl('plugin', 'load', str(target)); loaded.append(target)
    a, b = [w['address'] for w in clients().values() if w['class'] in ('hyprflip-front', 'hyprflip-back')]
    for _ in range(3):
        layout('dwindle')
        focus(a); action('mark'); focus(b); action('pair')
        assert len(data('hyprflip', 'status')['pairs']) == 1
        layout('hy3')
        action('unpair')
        probe()
        probe()
    passed('native groups can migrate into hy3, ungroup, close and reopen windows repeatedly')
    for _ in range(3):
        floating(a, True); floating(b, True)
        focus(a); action('mark'); focus(b); action('pair')
        assert len(data('hyprflip', 'status')['pairs']) == 1
        floating(a, False)
        focus(a); action('unpair')
        probe()
    passed('floating native pairs can return to tiling and ungroup without leaving expired targets')
    # Restore a balanced footprint before checking container minimum sizes.
    layout('dwindle'); layout('hy3')
    for _ in range(5):
        focus(a); action('mark'); focus(b); action('pair')
        assert len(data('hyprflip', 'status')['containers']) == 1
        action('unpair')
        floating(a, True); floating(a, False)
        probe()
    passed('container creation, removal and floating conversions still leave working layout targets')
    assert not data('hyprflip', 'status')['containers']
    assert not ctl('configerrors')
    (root / 'stale-target-results.json').write_text(json.dumps(checks, indent=2))
finally:
    for p in processes:
        if p.poll() is None:
            p.terminate(); p.wait(timeout=5)
    # A baseline failure can kill the disposable compositor. Cleanup must not
    # obscure that failure or connect to another session.
    try:
        config.write_text(original)
        ctl('reload')
        for library in reversed(loaded): ctl('plugin', 'unload', str(library))
    except (AssertionError, subprocess.TimeoutExpired):
        pass
