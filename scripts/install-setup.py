#!/usr/bin/env python3
"""Install guided creation and editing for an enabled Omarchy container trial."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess


def ctl(*args):
    result = subprocess.run(['hyprctl', *args], capture_output=True, text=True, timeout=8)
    reply = result.stdout.strip()
    if result.returncode or reply.startswith('error') or 'Lua error' in reply:
        raise RuntimeError(reply or result.stderr)
    return reply


def memberships(state):
    return sorted([tuple(tuple(face) for face in c['faces']) for c in state.get('containers', [])]
                  + [((p['front'],), (p['back'],)) for p in state.get('pairs', [])])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    project, home = Path(__file__).resolve().parent.parent, Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'hypr'
    main_config = config / 'hyprland.lua'
    helper = home / '.local/lib/hyprflip/setup.py'
    module = config / 'hyprflip-setup.lua'
    if not main_config.is_file():
        raise SystemExit('An existing Hyprland Lua configuration is required.')
    for binary in ('python3', 'omarchy-shell', 'notify-send'):
        if not shutil.which(binary):
            raise SystemExit('Guided setup requires Python 3 and the running Omarchy 4 shell.')
    ping = subprocess.run(['omarchy-shell', 'shell', 'ping'], capture_output=True, text=True, timeout=8,
                          env=os.environ | {'OMARCHY_SHELL_IPC_TIMEOUT': os.environ.get('OMARCHY_SHELL_IPC_TIMEOUT', '5s')})
    if ping.returncode or ping.stdout.strip() != 'ok':
        raise SystemExit('Start the Omarchy shell before installing guided setup.')
    if ctl('configerrors'):
        raise SystemExit('Resolve existing Hyprland configuration errors before installing.')
    state = json.loads(ctl('hyprflip', 'status'))
    if not state.get('container_provider'):
        raise SystemExit('Enable the matching Hyprflip container core and hy3 provider first.')
    available = ctl('repl', 'return hl.plugin.hyprflip.unfold ~= nil and hl.plugin.hyprflip.in_container ~= nil')
    if available != 'true':
        raise SystemExit('Update the container trial to the unfold build first.')
    keys = ('O', 'C', 'SPACE')
    conflicts = [b for b in json.loads(ctl('-j', 'binds')) if b['modmask'] == 76 and b['key'].upper() in keys
                 and not b.get('description', '').startswith('Hyprflip:')]
    if conflicts:
        keys = ', '.join('Super+Ctrl+Alt+' + b['key'].upper() for b in conflicts)
        raise SystemExit(keys + ' is assigned to another action; resolve that conflict first.')
    content = main_config.read_text()
    statement = 'require("hypr.hyprflip-setup")'
    if statement not in [line.strip() for line in content.splitlines()]:
        content = content.rstrip() + '\n\n-- Guided creation when O is used on a window without a card.\n' + statement + '\n'
    replacements = {helper: (project / 'scripts/setup.py').read_bytes(),
                    module: (project / 'examples/containers-setup.lua').read_bytes(),
                    main_config: content.encode()}
    print('Super+Ctrl+Alt+O: unfold/fold an existing card, or choose its reverse side. Existing cards stay in place.')
    print('Super+Ctrl+Alt+C: edit the current side using the app picker.')
    if state.get('peek_available'): print('Super+Ctrl+Alt+Space: hold to peek; release to return.')
    if args.dry_run:
        return 0
    originals = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else (None, 0o644)
                 for p in replacements}
    state_root = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state'))
    backup = state_root / 'hyprflip' / ('guided-setup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    for path, (data, _) in originals.items():
        if data is not None:
            (backup / path.name).write_bytes(data)
    (backup / 'files.json').write_text(json.dumps({str(p): data is not None for p, (data, _) in originals.items()}, indent=2) + '\n')

    def atomic(path, data, mode):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.hyprflip-new')
        temporary.write_bytes(data)
        os.chmod(temporary, mode)
        temporary.replace(path)

    try:
        for path, data in replacements.items():
            atomic(path, data, originals[path][1])
        ctl('reload')
        if errors := ctl('configerrors'):
            raise RuntimeError(errors)
        binds = json.loads(ctl('-j', 'binds'))
        expected = [('O', 'Hyprflip: unfold, fold or create a card'), ('C', 'Hyprflip: edit card')]
        if state.get('peek_available'): expected.append(('SPACE', 'Hyprflip: hold to peek at the other side'))
        for key, description in expected:
            matches = [b for b in binds if b['modmask'] == 76 and b['key'].upper() == key]
            if len(matches) != 1 or matches[0]['description'] != description:
                raise RuntimeError('The guided ' + key + ' shortcut did not register exactly once.')
        if memberships(json.loads(ctl('hyprflip', 'status'))) != memberships(state):
            raise RuntimeError('Card membership changed during installation.')
    except BaseException:
        for path, (data, mode) in originals.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, data, mode)
        ctl('reload')
        print('Previous files restored. Configuration errors:', ctl('configerrors'))
        raise
    print('Guided setup installed; no compositor libraries replaced. Backup:', backup)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
