#!/usr/bin/env python3
"""Update an already-enabled container trial and reconstruct its existing cards.

Keeps Hyprglass loaded. Does not enable layouts, add bindings, or launch apps.
Library paths must match the configured installation. Backups include recovery
metadata for this compositor session; they are not portable saved setups.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dry-run', action='store_true')
parser.add_argument('--library-root', type=Path, default=Path.home() / '.local/lib/hyprflip')
parser.add_argument('--state-dir', type=Path, default=Path.home() / '.local/state/hyprflip')
args = parser.parse_args()
project = Path(__file__).resolve().parent.parent
libraries = [(args.library_root / 'hyprflip.so', project / 'build/containers/core/hyprflip.so'),
             (args.library_root / 'containers/libhy3.so', project / 'build/containers/provider/upstream/libhy3.so')]
reservation = 'upgrade-' + uuid.uuid4().hex


def ctl(*arguments, check=True):
    result = subprocess.run(['hyprctl', *map(str, arguments)], capture_output=True, text=True, timeout=10)
    output = result.stdout.strip()
    if check and (result.returncode or output.startswith('error') or 'Lua error' in output or 'could not be loaded' in output):
        raise RuntimeError((arguments, output, result.stderr))
    return output


def state(): return json.loads(ctl('hyprflip', 'status'))
def clients(): return {w['address']: w for w in json.loads(ctl('-j', 'clients'))}
def focus(address):
    ctl('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: json.loads(ctl('-j', 'activewindow')).get('address') == address)


def focused(*operations):
    # A separate focus command (even followed by a successful focus poll) leaves
    # a gap for pointer events or application activation before mark/attach.
    # Select, verify and act within one compositor event-loop callback. Keep a
    # mark and the operation consuming it in the same callback as well.
    chunks = []
    for address, operation in operations:
        selector = json.dumps('address:' + address)
        chunks.append(f'''do
            local target = hl.get_window({selector})
            assert(target, "A card member closed during restoration")
            hl.dispatch(hl.dsp.focus({{window={selector}}}))
            local current = hl.get_active_window()
            assert(current and current.address == target.address,
                   "Could not focus the expected card member")
            {operation}
        end''')
    ctl('eval', '\n'.join(chunks))


def wait(predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.05)
    raise RuntimeError('Compositor state did not settle')


def atomic(path, data):
    temporary = path.with_name(path.name + '.hyprflip-new')
    temporary.write_bytes(data)
    os.chmod(temporary, path.stat().st_mode & 0o777)
    temporary.replace(path)


def unload():
    # The core dissolves its cards before the layout tree is removed. Keep
    # Hyprglass mapped until all geometry callbacks have finished.
    names = {p['name'] for p in json.loads(ctl('-j', 'plugin', 'list'))}
    for workspace in card_workspaces:
        ctl('eval', f'if chillmode and chillmode.hold_workspace then assert(chillmode.hold_workspace({workspace},120), '
            '"Could not protect the workspace during the plugin update") end')
    for (library, _), name in zip(libraries, ('hyprflip', 'hy3')):
        if name in names:
            reply = ctl('plugin', 'unload', library)
            if reply != 'ok': raise RuntimeError(reply)


def load():
    for (library, _), name in zip(reversed(libraries), ('hy3', 'hyprflip')):
        names = {p['name'] for p in json.loads(ctl('-j', 'plugin', 'list'))}
        if name not in names:
            reply = ctl('plugin', 'load', library)
            if reply != 'ok': raise RuntimeError(reply)
    # Protect reconstructed cards before reload queues Omachill's auto sweep.
    if state().get('workspace_protection'):
        for workspace in card_workspaces:
            ctl('hyprflip', f'reserve {workspace} {reservation}-{workspace} 120')
    ctl('reload')
    errors = ctl('configerrors')
    if errors: raise RuntimeError(errors)
    wait(lambda: state()['container_provider'])


def restore(snapshot, saved):
    for pair in snapshot['pairs']:
        ctl('hyprflip', 'adopt', pair['front'], pair['back'])
    for card in snapshot['containers']:
        now = clients()
        members = [w for face in card['faces'] for w in face]
        if any(w not in now or any(now[w][key] != saved[w][key] for key in ('pid', 'class', 'workspace', 'floating')) for w in members):
            raise RuntimeError('A card member closed or changed during the update; recovery metadata was retained')
        front, back = card['faces'][0][0], card['faces'][1][0]
        if card.get('floating'):
            x, y, width, height = map(round, card['box'])
            focused((front, f'hl.dispatch(hl.dsp.window.resize({{x={width},y={height}}})); '
                            f'hl.dispatch(hl.dsp.window.move({{x={x},y={y}}}))'))
        focused((front, 'assert(hl.plugin.hyprflip.mark())'),
                (back, 'assert(hl.plugin.hyprflip.pair())'))
        for side, face in enumerate(card['faces']):
            layout = card.get('layouts', [None, None])[side]
            if len(face) >= 2:
                first, second = face[:2]
                dx = abs(saved[first]['at'][0] - saved[second]['at'][0])
                dy = abs(saved[first]['at'][1] - saved[second]['at'][1])
                axis = 0 if dx > dy else 1
                if layout: axis = int(layout['axis'] == 'vertical')
                for companion in face[1:]:
                    direction = 'horizontal' if axis == 0 else 'vertical'
                    focused((companion, 'assert(hl.plugin.hyprflip.mark())'),
                            (first, f'assert(hl.plugin.hyprflip.attach("{direction}"))'))
                # Restore the inner proportion even if the containing tile was
                # reflowed when hy3 reloaded. No application content is saved.
                total = sum(saved[w]['size'][axis] for w in face)
                ratios = {w: saved[w]['size'][axis] / total for w in face}
                if layout: ratios = dict(zip(face, layout['ratios']))
                exact = state().get('repair_cards')
                if exact:
                    argument = ('vertical' if axis else 'horizontal') + ''.join(f' {w}:{ratios[w]:.12g}' for w in face)
                    focused((first, f'assert(hl.plugin.hyprflip.arrange({json.dumps(argument)}))'))
                for _ in range(0 if exact else 4):
                    settled = True
                    # Work from the first pane towards the last: each resize
                    # adjusts its next neighbor without disturbing earlier panes.
                    for pane in face[:-1]:
                        time.sleep(.15)
                        now = clients()
                        desired = ratios[pane] * sum(now[w]['size'][axis] for w in face)
                        delta = round(desired - now[pane]['size'][axis])
                        if abs(delta) <= 1:
                            continue
                        settled = False
                        x, y = (delta, 0) if axis == 0 else (0, delta)
                        focused((pane, f'hl.dispatch(hl.dsp.window.resize({{x={x},y={y},relative=true}}))'))
                    if settled:
                        break
            remembered = min(face, key=lambda w: saved[w]['focusHistoryID'] if saved[w]['focusHistoryID'] >= 0 else float('inf'))
            if layout: remembered = layout['focused']
            focus(remembered)
        focused((card['current'], 'assert(hl.plugin.hyprflip.unfold())' if card.get('unfolded') else ''))
        restored = next((c for c in state()['containers'] if c['faces'] == card['faces']), None)
        if not restored or restored['current'] != card['current'] or bool(restored.get('unfolded')) != bool(card.get('unfolded')):
            raise RuntimeError('Could not restore a card; recovery metadata was retained')
        if bool(restored.get('floating')) != bool(card.get('floating')):
            raise RuntimeError('Could not restore the card mode; recovery metadata was retained')
        if card.get('floating'):
            x, y, width, height = card['box']
            rx, ry, rw, rh = restored['box']
            focused((card['current'], f'hl.dispatch(hl.dsp.window.resize({{x={width-rw},y={height-rh},relative=true}})); '
                                     f'hl.dispatch(hl.dsp.window.move({{x={x-rx},y={y-ry},relative=true}}))'))


for installed, built in libraries:
    if not installed.is_file() or not built.is_file():
        raise SystemExit('Build both libraries first; this updater requires an already-enabled container trial')
if ctl('configerrors'):
    raise SystemExit('Resolve existing configuration errors before updating')
monitors = json.loads(ctl('-j', 'monitors'))
if any('LOCK' in monitor.get('solitaryBlockedBy', []) for monitor in monitors):
    raise SystemExit('Unlock your desktop before updating Hyprflip; restoring cards requires window focus.')
plugins = {p['name'] for p in json.loads(ctl('-j', 'plugin', 'list'))}
if not {'hyprflip', 'hy3'} <= plugins:
    raise SystemExit('Both experimental plugins must already be loaded')
snapshot = state()
print(f"Update core and provider; preserve {len(snapshot['containers'])} container(s) and {len(snapshot['pairs'])} native pair(s).")
print('Applications stay open. Layout reload may rearrange the surrounding tiles.')
if not args.dry_run:
    ctl('hyprflip', 'finish')
    snapshot = state()
saved = clients()
layouts = {w['id']: w['tiledLayout'] for w in json.loads(ctl('-j', 'workspaces'))}
native_members = {w for c in snapshot['containers'] if c.get('native_group') for f in c['faces'] for w in f}
if any(w['grouped'] and not w['floating'] and layouts[w['workspace']['id']] == 'hy3' and a not in native_members for a,w in saved.items()):
    raise SystemExit('Separate native tiled groups on hy3 before updating the experimental layout')
active = json.loads(ctl('-j', 'activewindow')).get('address')
for card in snapshot['containers']:
    for face in card['faces']:
        for w in face:
            if saved[w]['fullscreen'] or ((saved[w]['floating'] or saved[w]['grouped']) and not card.get('native_group')):
                raise SystemExit('Leave fullscreen and complete any grouping changes before updating')
card_workspaces = {saved[w]['workspace']['id'] for card in snapshot['containers']
                   for face in card['faces'] for w in face}
if card_workspaces and ctl('repl', 'return chillmode ~= nil and chillmode.hold_workspace == nil') == 'true':
    raise SystemExit('Install the Omachill integration before updating active cards while Chill mode is loaded')
if any(w['fullscreen'] and w['workspace']['id'] in card_workspaces for w in saved.values()):
    raise SystemExit('Leave fullscreen or dismiss the screensaver covering a card workspace before updating')
if args.dry_run:
    raise SystemExit(0)
backup = args.state_dir / ('container-update-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
originals = {installed: installed.read_bytes() for installed, _ in libraries}
for path in originals:
    shutil.copy2(path, backup / path.name)
recovery = {'instance': os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'), 'status': snapshot,
            'active': active, 'monitors': [{k: m[k] for k in ('name', 'activeWorkspace', 'focused')} for m in monitors],
            'clients': {w: {k: item[k] for k in ('pid', 'class', 'workspace', 'floating', 'at', 'size', 'focusHistoryID')}
                        for w, item in saved.items()}}
(backup / 'recovery.json').write_text(json.dumps(recovery, indent=2) + '\n')
print('Backup:', backup, flush=True)
try:
    unload()
    for installed, built in libraries:
        atomic(installed, built.read_bytes())
    load()
    restore(snapshot, saved)
    ctl('reload')
    if ctl('configerrors'): raise RuntimeError(ctl('configerrors'))
    after = state()
    if len(after['containers']) != len(snapshot['containers']) or len(after['pairs']) != len(snapshot['pairs']):
        raise RuntimeError('The number of cards changed during update')
    (backup / 'result.json').write_text(json.dumps(after, indent=2) + '\n')
    print('Updated both libraries and restored the cards.', flush=True)
except BaseException:
    print('Update failed; restoring the previous libraries and cards.', flush=True)
    try:
        try:
            unload()
        finally:
            # A dead compositor cannot answer unload, but the next session must
            # still start with the previous files. Atomic replacement leaves any
            # surviving process's mapped library untouched.
            for path, data in originals.items(): atomic(path, data)
            print('Previous library files restored on disk.', flush=True)
        load()
        restore(snapshot, saved)
    except Exception as error:
        print(f'Recovery needs attention: {error}. Metadata: {backup / "recovery.json"}', flush=True)
    raise
finally:
    try:
        for workspace in card_workspaces:
            ctl('hyprflip', f'unreserve {reservation}-{workspace}', check=False)
            ctl('eval', f'if chillmode and chillmode.hold_workspace then chillmode.hold_workspace({workspace},0) end', check=False)
        # Reconstructing cards can visit several monitors. Restore each monitor's
        # selected workspace, then the original application focus.
        for monitor in monitors:
            number = monitor['activeWorkspace']['id']
            ctl('dispatch', f'hl.dsp.focus({{workspace="{number}"}})', check=False)
        if active and active in clients(): focus(active)
    except Exception as error:
        # Keep the original failure visible when IPC disappeared during update.
        print(f'Could not restore desktop focus: {error}', flush=True)
