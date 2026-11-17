#!/usr/bin/env python3
"""Install guided card workflows with an automatically detected desktop menu."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import navigation as movement
import shortcuts
import workflow


def ctl(*args):
    # The status carries app- and user-chosen text (closed apps' classes,
    # workspace names), so this reads replies as workflow.Hyprctl.call does:
    # bytes that are not UTF-8 are replaced, and "Lua error" counts only in a
    # reply that is not JSON.
    result = subprocess.run(['hyprctl', *args], capture_output=True, encoding='utf-8', errors='replace', timeout=8)
    reply = result.stdout.strip()
    if (result.returncode or reply.startswith('error') or
            (not reply.startswith(('{', '[')) and 'Lua error' in reply)):
        raise RuntimeError(reply or result.stderr)
    return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--backend-only', action='store_true', help='Install the OmaCards helper and motion preferences without container shortcuts')
    parser.add_argument('--mouse-flip', action='store_true', help='Enable Super+Ctrl+Alt+middle-click to flip the focused card')
    parser.add_argument('--navigation', action='store_true',
                        help='Install the movement shortcuts that move a whole card (hyprflip-navigation.lua); '
                             'without it, an unchanged copy from before is still updated')
    parser.add_argument('--no-navigation', action='store_true',
                        help='Turn the movement shortcuts off: remove hyprflip-navigation.lua and its require line, '
                             'keeping a copy with changes of your own with the backup')
    args = parser.parse_args()
    if args.navigation and args.backend_only:
        parser.error('--navigation installs card shortcuts, which --backend-only leaves out')
    if args.navigation and args.no_navigation:
        parser.error('choose --navigation or --no-navigation')
    project, home = Path(__file__).resolve().parent.parent, Path.home()
    paths = movement.Paths()
    config, main_config, navigation = paths.main.parent, paths.main, paths.module
    helper = home / '.local/lib/hyprflip/setup.py'
    module = config / ('hyprflip-preferences.lua' if args.backend_only else 'hyprflip-setup.lua')
    shipped_navigation = (project / 'examples/containers-navigation.lua').read_bytes()
    if not main_config.is_file():
        raise SystemExit('An existing Hyprland Lua configuration is required.')
    for binary in ('python3', 'hyprctl', 'notify-send', 'gio', 'gdbus'):
        if not shutil.which(binary):
            raise SystemExit(f'Guided setup requires {binary}. Install Python 3, GLib and libnotify alongside Hyprland.')
    if not args.backend_only:
        try:
            backend = workflow.select_menu_backend()
        except workflow.SetupError as error:
            raise SystemExit(str(error)) from error
        print('Card menu:', backend, '(detected again whenever you open a menu)')
    if ctl('configerrors'):
        raise SystemExit('Resolve existing Hyprland configuration errors before installing.')
    state = json.loads(ctl('hyprflip', 'status'))
    if not args.backend_only and not state.get('container_provider'):
        raise SystemExit('Load a Hyprflip build with card support first. Dwindle needs only the core plugin.')
    available = ctl('repl', 'return hl.plugin.hyprflip.unfold ~= nil and hl.plugin.hyprflip.in_container ~= nil')
    if not args.backend_only and available != 'true':
        raise SystemExit('Update Hyprflip to a build with card controls first.')
    preferences = shortcuts.read(workflow.Hyprctl())
    # Cores with whole-card fullscreen report its divider width.
    fullscreen = type(state.get('fullscreen_divider')) is int
    expected_chords = set() if args.backend_only else {preferences.get(i, (76, k)) for i, k in
        (('create', 'O'), ('edit', 'C'), ('library', 'L'), ('find', 'K'), ('peek', 'space'))
        + ((('fullscreen', 'Return'),) if fullscreen else ())}
    if args.mouse_flip: expected_chords.add((76, 'mouse:274'))
    # Keys another module claims (hyprflip_claimed_keys) stay with it: they are no conflict, and it binds them.
    claimed = shortcuts.claims(lambda source: ctl('repl', source))
    conflicts = [b for b in json.loads(ctl('-j', 'binds')) if (b['modmask'], b['key'].lower()) in {(m, k.lower()) for m, k in expected_chords}
                 and not b.get('description', '').startswith('Hyprflip:') and (b['modmask'], b['key'].lower()) not in claimed]
    if conflicts:
        keys = ', '.join(shortcuts.label(b['modmask'], b['key'].upper() if len(b['key']) == 1 else b['key']) for b in conflicts)
        raise SystemExit(keys + ' is assigned to another action; resolve that conflict first.')
    content = main_config.read_text()
    bootstrap = (project / 'examples/module-path.lua').read_text()
    if bootstrap.splitlines()[0] not in content:
        content = bootstrap + '\n' + content
    statement = 'require("hypr.hyprflip-preferences")' if args.backend_only else 'require("hypr.hyprflip-setup")'
    if statement not in [line.strip() for line in content.splitlines()]:
        content = content.rstrip() + '\n\n-- Hyprflip helpers and saved motion preferences.\n' + statement + '\n'
    mouse_statement = 'require("hypr.hyprflip-mouse")'
    if args.mouse_flip and mouse_statement not in [line.strip() for line in content.splitlines()]:
        content = content.rstrip() + '\n' + mouse_statement + '\n'
    # The movement shortcuts: installed when asked for, updated while they are as an install or release left them,
    # and kept as they are when they have changes of their own, unless asked for again; or turned off.
    navigation_plan, navigation_edited = None, False
    if args.no_navigation:
        content = movement.without_statement(content)
        if navigation.is_file():
            navigation_plan = 'remove'
            navigation_edited = movement.edited(paths, navigation.read_bytes(), shipped_navigation)
    elif not args.backend_only:
        navigation_plan = movement.plan(paths, shipped_navigation, args.navigation)
    if args.navigation:
        content = movement.with_statement(content)
    navigation_loaded = navigation_plan not in (None, 'kept', 'remove') and movement.loaded(content)
    replacements = {helper.parent / name: (project / 'scripts' / name).read_bytes()
                    for name in ('setup.py', 'workflow.py', 'control.py', 'shortcuts.py', 'navigation.py')}
    # The shipped module beside the helper, from which control.py switches the shortcuts on. They need cards.
    beside = helper.parent / 'navigation.lua'
    if not args.backend_only:
        replacements[beside] = shipped_navigation
    elif beside.exists():
        replacements[beside] = None
    replacements.update({config / 'hyprflip-preferences.lua': (project / 'examples/preferences.lua').read_bytes(),
                         config / 'hyprflip-shortcuts.lua': (project / 'examples/shortcuts.lua').read_bytes(),
                         main_config: content.encode()})
    mouse_module = config / 'hyprflip-mouse.lua'
    if args.mouse_flip and not mouse_module.exists():
        replacements[mouse_module] = (project / 'examples/mouse.lua').read_bytes()
    if navigation_plan in ('install', 'update', 'replace'):
        replacements[navigation] = shipped_navigation
    elif navigation_plan == 'remove':
        replacements[navigation] = None
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
        def explain(ident, key, text):
            mask, key = preferences.get(ident, (76, key))
            owner = claimed.get((mask, key.lower()))
            print(shortcuts.label(mask, key) + ': ' + (f'left to {owner}, which claims it.' if owner else text))
        explain('create', 'O', 'unfold/fold an existing card, or choose its reverse side. Existing cards stay in place.')
        explain('edit', 'C', 'edit the current card in OmaCards when enabled, or the detected menu.')
        explain('library', 'L', 'search saved cards; Enter opens or switches directly.')
        explain('find', 'K', 'find an app on either face of any open card.')
        if state.get('peek_available'): explain('peek', 'space', 'hold to peek; release to return.')
        if fullscreen: explain('fullscreen', 'Return', 'fullscreen the whole card; press again to leave.')
    if args.mouse_flip: print('Super+Ctrl+Alt+middle-click: flip the focused card on release (optional).')
    if navigation_loaded:
        print('Super+Shift+1…0, Super+Shift+Alt+1…0 and Super+Shift+arrows: move a whole card; other windows move as before.')
    if args.no_navigation:
        print('Movement shortcuts off: Super+Shift+1…0, Super+Shift+Alt+1…0 and Super+Shift+arrows work as your '
              'desktop sets them.')
    if navigation_plan == 'replace':
        print(f'{navigation} had changes of your own; it is replaced, and your copy is kept with the backup.')
    elif navigation_edited:
        print(f'{navigation} had changes of your own; it is removed, and your copy is kept with the backup.')
    elif navigation_plan == 'kept':
        print(f'{navigation} has changes of your own, so it stays as it is; --navigation replaces it and keeps your '
              'copy with the backup. A workspace numbering of your own can go in hyprflip_workspace_id (docs/INSTALL.md).')
    if args.dry_run:
        return 0
    originals = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else (None, 0o644)
                 for p in replacements}
    backup = paths.state / ('guided-setup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
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
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, data, originals[path][1])
        ctl('reload')
        if errors := ctl('configerrors'):
            raise RuntimeError(errors)
        binds = json.loads(ctl('-j', 'binds'))
        expected = [('O', 'Hyprflip: unfold, fold or create a card'), ('C', 'Hyprflip: edit card'),
                    ('L', 'Hyprflip: open saved card'), ('K', 'Hyprflip: find an app in cards')]
        if state.get('peek_available'): expected.append(('SPACE', 'Hyprflip: hold to peek at the other side'))
        if fullscreen: expected.append(('Return', 'Hyprflip: fullscreen the whole card'))
        # The claims the reloaded configuration makes: a claimed key needs exactly one binding, its owner's.
        claimed_now = shortcuts.claims(lambda source: ctl('repl', source))
        for key, description in ([] if args.backend_only else expected):
            ident = shortcuts.DESCRIPTIONS[description]
            mask, key = preferences.get(ident, (76, key))
            matches = [b for b in binds if b['modmask'] == mask and b['key'].lower() == key.lower()]
            owner = claimed_now.get((mask, key.lower()))
            if owner and (len(matches) != 1 or matches[0].get('description', '').startswith('Hyprflip:')):
                raise RuntimeError(f'The {key} shortcut that {owner} claims did not register exactly once as its own.')
            if not owner and (len(matches) != 1 or matches[0]['description'] != description):
                raise RuntimeError('The guided ' + key + ' shortcut did not register exactly once.')
        if args.mouse_flip:
            matches = [b for b in binds if b['modmask'] == 76 and b['key'] == 'mouse:274']
            if len(matches) != 1 or matches[0]['description'] != 'Hyprflip: flip focused card with mouse':
                raise RuntimeError('The mouse flip shortcut did not register exactly once.')
        if navigation_loaded:
            for description in movement.KEYS:
                if sum(b.get('description') == description for b in binds) != 1:
                    raise RuntimeError(f'The shortcut "{description}" did not register exactly once.')
        if args.no_navigation:
            for description in movement.KEYS:
                if any(b.get('description') == description for b in binds):
                    raise RuntimeError(f'The shortcut "{description}" is still there.')
        if movement.memberships(json.loads(ctl('hyprflip', 'status'))) != movement.memberships(state):
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
    if navigation_plan in ('install', 'update', 'replace', 'current'):
        movement.record(paths, shipped_navigation)
    if args.no_navigation:
        paths.record.unlink(missing_ok=True)
    if args.navigation or args.no_navigation:
        movement.choose(paths, args.navigation)
    print('Guided setup installed; no compositor libraries replaced. Backup:', backup)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
