#!/usr/bin/env python3
"""Remove Hyprflip as scripts/bootstrap.py, install.py and install-setup.py put it in place.

The lines those installers added to hyprland.lua come out and Hyprland reloads without the plugin. Open cards come
apart into ordinary windows, with their apps still open. The plugin and its helper go. The Lua modules and the
configuration backups the installers made move to ~/.local/state/hyprflip/uninstalled-<time>/. Saved cards and
preferences stay in ~/.local/state/hyprflip; --purge removes that folder too.

If Hyprland reports a new configuration error once the lines are out, everything is put back as it was. The module
search path the installers added stays when another module still needs it. Run this inside the Hyprland session:
without one it changes only the files, and Hyprland reads them at its next start. Nothing here uses sudo.

  python3 scripts/uninstall.py [--dry-run] [--yes] [--purge]
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

project = Path(__file__).resolve().parent.parent
home = Path.home()
config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'hypr'
hyprland_lua = config / 'hyprland.lua'
library = home / '.local/lib/hyprflip'
state = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / 'hyprflip'
# The lines install.py and install-setup.py add, and docs/INSTALL.md's optional ones.
REQUIRES = {f'require("hypr.{name}")' for name in ('hyprflip', 'hyprflip-setup', 'hyprflip-preferences', 'hyprflip-mouse',
                                                   'hyprflip-navigation', 'hyprflip-containers')}
COMMENTS = {'-- Two-sided application windows.', '-- Hyprflip helpers and saved motion preferences.'}
MODULES = ('hyprflip.lua', 'hyprflip-setup.lua', 'hyprflip-preferences.lua', 'hyprflip-shortcuts.lua',
           'hyprflip-mouse.lua', 'hyprflip-navigation.lua', 'hyprflip-containers.lua')
# install.py's backups of hyprland.lua and of the modules, and the retired provider's
BACKUPS = re.compile(r'hyprflip[\w-]*\.lua\.bak-.+|hyprland\.lua\.bak-\d{8}-\d{6}')


def ctl(*args):
    result = subprocess.run(['hyprctl', *args], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip() or 'hyprctl ' + ' '.join(args) + ' failed')
    return result.stdout.strip()


def hyprland():
    """Whether a Hyprland session answers here."""
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') or not shutil.which('hyprctl'):
        return False
    try:
        ctl('version')
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False
    return True


def loaded():
    return any(p.get('name') == 'hyprflip' for p in json.loads(ctl('-j', 'plugin', 'list') or '[]'))


def errors():
    return {line for line in ctl('configerrors').splitlines() if line.strip()}


def without_requires(text):
    """hyprland.lua without the require lines Hyprflip's installers add, the comment each wrote above its line, and
    the blank line each put before them."""
    lines = text.splitlines(keepends=True)
    drop = {i for i, line in enumerate(lines) if line.strip() in REQUIRES}
    drop |= {i - 1 for i in drop if i > 0 and lines[i - 1].strip() in COMMENTS}
    for start in sorted(i for i in drop if i - 1 not in drop):
        end = start
        while end + 1 in drop:
            end += 1
        # an installer's own comment came after a blank line it added; a lone line keeps one blank line between others
        if start > 0 and not lines[start - 1].strip() and (lines[start].strip() in COMMENTS or end + 1 == len(lines)
                                                             or not lines[end + 1].strip()):
            drop.add(start - 1)
    return ''.join(line for i, line in enumerate(lines) if i not in drop)


def without_path(text, block):
    """hyprland.lua without the module search path block, which install.py puts first, followed by a blank line."""
    for found in (block + '\n', block):
        if found in text:
            return text.replace(found, '', 1)
    return text


def write(path, text):
    target = path.resolve()
    temporary = target.with_name(target.name + '.hyprflip-new')
    temporary.write_text(text)
    os.chmod(temporary, target.stat().st_mode & 0o777)
    temporary.replace(target)


def ask(question):
    if not sys.stdin.isatty():
        raise SystemExit('Nothing was changed: there is no terminal to ask on. Add --yes to remove Hyprflip.')
    return input(question + ' [y/N] ').strip().lower().startswith('y')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='show what would be removed, and change nothing')
    parser.add_argument('--yes', action='store_true', help='do not ask first')
    parser.add_argument('--purge', action='store_true', help='also remove the saved cards and preferences')
    args = parser.parse_args()

    original = hyprland_lua.read_text() if hyprland_lua.is_file() else None
    block = (project / 'examples/module-path.lua').read_text()
    candidates = []
    if original is not None:
        kept = without_requires(original)
        candidates = list(dict.fromkeys(text for text in (without_path(kept, block), kept) if text != original))
    files = [config / name for name in MODULES if (config / name).is_file() or (config / name).is_symlink()]
    files += sorted(path for path in config.glob('*.bak-*') if BACKUPS.fullmatch(path.name) and not path.is_dir())
    markers = [path for path in (state / 'installed-release', state / 'installed-commit') if path.exists()]
    session = hyprland()
    try:
        plugin = session and loaded()
        status = json.loads(ctl('hyprflip', 'status')) if plugin else {}
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'Nothing was changed: Hyprland did not answer ({error}).') from None
    if not (candidates or files or library.exists() or library.is_symlink() or markers or plugin):
        print('Hyprflip is not installed here.')
        return 0

    if plugin:
        parked = [card for card in status.get('containers', []) if card.get('workspace', {}).get('special')]
        if parked:
            raise SystemExit(f'{len(parked)} card(s) are parked out of sight on a special workspace. The program that '
                             'parked them, such as a card mode, has to bring them back first; then run this again.')
    print('Removes Hyprflip:')
    if candidates:
        print(f'  - its lines in {hyprland_lua}')
    if plugin:
        print('  - the plugin from this Hyprland session; open cards come apart into ordinary windows')
    if library.exists() or library.is_symlink():
        print(f'  - the plugin and its helper, {library}')
    if files:
        print(f"  - {len(files)} module(s) and backup(s) in {config}, moved to {state / 'uninstalled-<time>'}"
              if not args.purge else f'  - {len(files)} module(s) and backup(s) in {config}')
    print(f'  - its saved cards and preferences, {state}' if args.purge else
          f'Saved cards and preferences stay in {state}.')
    if args.dry_run:
        return 0
    if not args.yes and not ask('Remove Hyprflip?'):
        print('Nothing was changed.')
        return 0

    if plugin:
        ctl('hyprflip', 'finish')  # a turn in progress settles first
    before = errors() if session else set()
    keep = state / ('uninstalled-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    moved = []
    try:
        if files:
            keep.mkdir(parents=True)
            for path in files:
                moved.append((path, keep / path.name))
                shutil.move(path, keep / path.name)
        for number, text in enumerate(candidates or [None]):
            if text is not None:
                write(hyprland_lua, text)
            if not session:
                break
            ctl('reload')
            new = errors() - before
            if not new:
                break
            if number + 1 == len(candidates or [None]):
                raise RuntimeError('Hyprland reported: ' + sorted(new)[0])
    except Exception as error:
        if original is not None:
            write(hyprland_lua, original)
        for path, there in reversed(moved):
            shutil.move(there, path)
        if keep.is_dir() and not any(keep.iterdir()):
            keep.rmdir()
        if session:
            try:
                ctl('reload')
                if plugin and not loaded():
                    ctl('plugin', 'load', str(library / 'hyprflip.so'))
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                pass
        raise SystemExit(f'Hyprflip was not removed, and everything is as it was. {error}') from None

    if session and loaded():
        try:
            ctl('plugin', 'unload', str(library / 'hyprflip.so'))
        except RuntimeError as error:
            print('Hyprland kept the plugin loaded until you next log in:', error)
    if library.is_symlink():
        library.unlink()
    elif library.exists():
        shutil.rmtree(library)
    for path in markers:
        path.unlink()
    if args.purge:
        shutil.rmtree(state, ignore_errors=True)
    elif moved:
        print('Modules and backups:', keep)
    print('Hyprflip is removed.' + ('' if session else ' Hyprland reads the change when it next starts.'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
