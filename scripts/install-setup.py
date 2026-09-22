#!/usr/bin/env python3
"""Install guided creation and editing for an enabled Omarchy container trial."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import shortcuts
import workflow


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
    parser.add_argument('--backend-only', action='store_true', help='Install the OmaCards helper and motion preferences without container shortcuts')
    args = parser.parse_args()
    project, home = Path(__file__).resolve().parent.parent, Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'hypr'
    main_config = config / 'hyprland.lua'
    helper = home / '.local/lib/hyprflip/setup.py'
    module = config / ('hyprflip-preferences.lua' if args.backend_only else 'hyprflip-setup.lua')
    if not main_config.is_file():
        raise SystemExit('An existing Hyprland Lua configuration is required.')
    for binary in ('python3', 'omarchy-shell', 'notify-send', 'gio', 'gdbus'):
        if not shutil.which(binary):
            raise SystemExit(f'Guided setup requires {binary}. Install Python 3, GLib, libnotify and the Omarchy 4 shell.')
    ping = subprocess.run(['omarchy-shell', 'shell', 'ping'], capture_output=True, text=True, timeout=8,
                          env=os.environ | {'OMARCHY_SHELL_IPC_TIMEOUT': os.environ.get('OMARCHY_SHELL_IPC_TIMEOUT', '5s')})
    if ping.returncode or ping.stdout.strip() != 'ok':
        raise SystemExit('Start the Omarchy shell before installing guided setup.')
    if ctl('configerrors'):
        raise SystemExit('Resolve existing Hyprland configuration errors before installing.')
    state = json.loads(ctl('hyprflip', 'status'))
    if not args.backend_only and not state.get('container_provider'):
        raise SystemExit('Enable the matching Hyprflip container core and hy3 provider first.')
    available = ctl('repl', 'return hl.plugin.hyprflip.unfold ~= nil and hl.plugin.hyprflip.in_container ~= nil')
    if not args.backend_only and available != 'true':
        raise SystemExit('Update the container trial to the unfold build first.')
    preferences = shortcuts.read(workflow.Hyprctl())
    expected_chords = {preferences.get(i, (76, k)) for i, k in (('create', 'O'), ('edit', 'C'), ('library', 'L'), ('peek', 'space'))}
    conflicts = [b for b in json.loads(ctl('-j', 'binds')) if (b['modmask'], b['key'].lower()) in {(m, k.lower()) for m, k in expected_chords}
                 and not b.get('description', '').startswith('Hyprflip:')]
    if conflicts and not args.backend_only:
        keys = ', '.join('Super+Ctrl+Alt+' + b['key'].upper() for b in conflicts)
        raise SystemExit(keys + ' is assigned to another action; resolve that conflict first.')
    content = main_config.read_text()
    statement = 'require("hypr.hyprflip-preferences")' if args.backend_only else 'require("hypr.hyprflip-setup")'
    if statement not in [line.strip() for line in content.splitlines()]:
        content = content.rstrip() + '\n\n-- Hyprflip helpers and saved motion preferences.\n' + statement + '\n'
    replacements = {helper.parent / name: (project / 'scripts' / name).read_bytes()
                    for name in ('setup.py', 'workflow.py', 'control.py', 'shortcuts.py')}
    replacements.update({config / 'hyprflip-preferences.lua': (project / 'examples/preferences.lua').read_bytes(),
                         config / 'hyprflip-shortcuts.lua': (project / 'examples/shortcuts.lua').read_bytes(),
                         main_config: content.encode()})
    if not args.backend_only:
        replacements[module] = (project / 'examples/containers-setup.lua').read_bytes()
        # Keep user plugin settings/layout rules; route only these modules' existing binds.
        header = ('-- Share owned shortcuts with OmaCards.\n'
                  'local shortcuts = require("hypr.hyprflip-shortcuts")\n')
        for name in ('hyprflip.lua', 'hyprflip-containers.lua'):
            path = config / name
            if path.exists() and 'hypr.hyprflip-shortcuts' not in path.read_text():
                replacements[path] = (header + path.read_text().replace('hl.bind(', 'shortcuts.bind(')).encode()
    if args.backend_only:
        print('Install the OmaCards backend and persistent motion preferences; keep current shortcuts.')
    else:
        print('Super+Ctrl+Alt+O: unfold/fold an existing card, or choose its reverse side. Existing cards stay in place.')
        print('Super+Ctrl+Alt+C: edit the current card in OmaCards when enabled, or the native menu.')
        print('Super+Ctrl+Alt+L: search saved cards; Enter opens or switches directly.')
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
        expected = [('O', 'Hyprflip: unfold, fold or create a card'), ('C', 'Hyprflip: edit card'),
                    ('L', 'Hyprflip: open saved card')]
        if state.get('peek_available'): expected.append(('SPACE', 'Hyprflip: hold to peek at the other side'))
        for key, description in ([] if args.backend_only else expected):
            ident = shortcuts.DESCRIPTIONS[description]
            mask, key = preferences.get(ident, (76, key))
            matches = [b for b in binds if b['modmask'] == mask and b['key'].lower() == key.lower()]
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
