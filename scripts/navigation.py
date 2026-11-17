"""The movement shortcuts, hyprflip-navigation.lua: whether they are on, and switching them on or off.

install-setup.py uses this from the source checkout. It also installs it beside the helper, with the shipped module as
navigation.lua, so that control.py can switch the shortcuts without the checkout (docs/PANEL_API.md).
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil

# examples/containers-navigation.lua as every release had it before installs recorded what they put in place (to
# 0.3.0-rc.22). docs/INSTALL.md had it copied by hand: such a copy, unchanged, is updated like the setup module.
RELEASED = {'45920f0ea8225562fe28c1c75ab15a2f56700d12b2078b7694cef2b2465e104a'}
STATEMENT = 'require("hypr.hyprflip-navigation")'
COMMENT = '-- Move whole Hyprflip cards with the normal movement shortcuts.'
KEYS = tuple([f'Move card or window to workspace {n}' for n in range(1, 11)]
             + [f'Move card or window silently to workspace {n}' for n in range(1, 11)]
             + [f'Move card or window {way}' for way in ('left', 'right', 'up', 'down')])


class Refused(Exception):
    """The shortcuts were not switched; the files are as they were."""


class Paths:
    """Where the module and its require line are, and what installs and the user's choice left beside them."""
    def __init__(self, env=None):
        env = os.environ if env is None else env
        home = Path(env['HOME']) if env.get('HOME') else Path.home()
        config = Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'hypr'
        self.state = Path(env.get('XDG_STATE_HOME') or home / '.local/state') / 'hyprflip'
        self.main, self.module = config / 'hyprland.lua', config / 'hyprflip-navigation.lua'
        # what an install put in place, and the user's last choice; uninstall.py removes both
        self.record, self.choice = self.state / 'navigation.sha256', self.state / 'navigation-choice'


def loaded(text):
    """Whether a configuration has the require line installs add."""
    return STATEMENT in (line.strip() for line in text.splitlines())


def with_statement(text):
    return text if loaded(text) else text.rstrip() + '\n\n' + COMMENT + '\n' + STATEMENT + '\n'


def without_statement(text):
    """The configuration without the require line, the comment an install wrote above it and the blank line before."""
    kept = []
    for line in text.splitlines(keepends=True):
        if line.strip() != STATEMENT:
            kept.append(line)
        elif kept and kept[-1].strip() == COMMENT:
            kept.pop()
            if kept and not kept[-1].strip():
                kept.pop()
    return ''.join(kept)


def edited(paths, data, shipped):
    """Whether a copy of the module has changes of the user's own: it is not the shipped module, a released one or
    the one an earlier install put in place."""
    try:
        recorded = paths.record.read_text().strip()
    except (OSError, UnicodeError):
        recorded = None
    return data != shipped and hashlib.sha256(data).hexdigest() not in RELEASED | {recorded}


def plan(paths, shipped, asked):
    """What an install does with the module: None, 'install', 'current' or 'update', or for a copy with changes of the
    user's own, 'replace' when asked for and 'kept' otherwise."""
    if not paths.module.is_file():
        return 'install' if asked else None
    data = paths.module.read_bytes()
    if data == shipped:
        return 'current'
    if not edited(paths, data, shipped):
        return 'update'
    return 'replace' if asked else 'kept'


def state(paths, shipped=None):
    """'on', 'edited' (on, with changes of the user's own) or 'off'. It loads only with both its file and its line."""
    try:
        if not (paths.module.is_file() and loaded(paths.main.read_text())):
            return 'off'
        data = paths.module.read_bytes()
    except (OSError, UnicodeError):
        return 'off'
    return 'edited' if edited(paths, data, shipped) else 'on'


def choice(paths):
    """The user's last choice, 'on' or 'off', or None when there was none since Hyprflip was installed."""
    try:
        value = paths.choice.read_text().strip()
    except (OSError, UnicodeError):
        return None
    return value if value in ('on', 'off') else None


def write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.hyprflip-new')
    temporary.write_bytes(data)
    os.chmod(temporary, mode)
    temporary.replace(path)


def record(paths, shipped):
    """What an install put in place, so that a later one can tell it from changes of the user's own."""
    write(paths.record, hashlib.sha256(shipped).hexdigest().encode() + b'\n')


def choose(paths, enabled):
    write(paths.choice, b'on\n' if enabled else b'off\n')


def memberships(status):
    return sorted([tuple(tuple(face) for face in c['faces']) for c in status.get('containers', [])]
                  + [((p['front'],), (p['back'],)) for p in status.get('pairs', [])])


def errors(call):
    return {line.strip() for line in call('configerrors').splitlines() if line.strip()}


def switch(enabled, call, paths, shipped, now=datetime.now):
    """Switch the shortcuts on (the shipped module, loaded) or off (neither the module nor its line), reload Hyprland
    and check that they all came or all went, and that no card changed. call(*args) runs hyprctl and returns its reply.

    Records the choice. Returns the backup folder when it keeps a copy with changes of the user's own, else None.
    Raises Refused, with every file as it was, when that check or the reload fails; only configuration errors that
    were not there before count, so that the shortcuts can go off when their module is what fails.
    """
    try:
        text = paths.main.read_text()
        current = paths.module.read_bytes() if paths.module.is_file() else None
    except FileNotFoundError:
        raise Refused('An existing Hyprland Lua configuration is required.') from None
    except (OSError, UnicodeError) as error:
        raise Refused(f'Hyprland\'s configuration could not be read: {error}') from None
    originals = {paths.main: text.encode(), paths.module: current}
    targets = {paths.main: (with_statement if enabled else without_statement)(text).encode(),
               paths.module: shipped if enabled else None}
    changes = {path: data for path, data in targets.items() if data != originals[path]}
    kept = paths.module in changes and current is not None and edited(paths, current, shipped)
    if changes:
        modes = {path: path.stat().st_mode & 0o777 if originals[path] is not None else 0o644 for path in changes}
        before = errors(call)
        try:
            cards = memberships(json.loads(call('hyprflip', 'status')))
        except Exception:  # no Hyprflip core to ask: no card to keep either
            cards = None
        backup = paths.state / ('navigation-' + now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True)
        for path in changes:
            if originals[path] is not None:
                (backup / path.name).write_bytes(originals[path])
        (backup / 'files.json').write_text(json.dumps({str(p): originals[p] is not None for p in changes}, indent=2) + '\n')
        try:
            for path, data in changes.items():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    write(path, data, modes[path])
            call('reload')
            if new := errors(call) - before:
                raise Refused('Hyprland reported: ' + sorted(new)[0])
            binds = json.loads(call('-j', 'binds'))
            for description in KEYS:
                if sum(b.get('description') == description for b in binds) != (1 if enabled else 0):
                    raise Refused(f'The shortcut "{description}" ' + ('did not register exactly once.' if enabled else
                                                                     'is still there.'))
            if cards is not None and memberships(json.loads(call('hyprflip', 'status'))) != cards:
                raise Refused('A card changed while Hyprland reloaded.')
        except BaseException as error:
            try:
                for path in changes:
                    if originals[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        write(path, originals[path], modes[path])
            except OSError as failure:
                raise Refused(f'{error} The files could not be put back ({failure}); they are in {backup}.') from None
            shutil.rmtree(backup, ignore_errors=True)
            try:
                call('reload')
            except Exception:
                pass
            if not isinstance(error, Exception):
                raise
            reason = str(error).strip() or type(error).__name__
            raise Refused(reason.rstrip('.') + '. The shortcuts are as they were.') from None
    if enabled:
        record(paths, shipped)
    else:
        paths.record.unlink(missing_ok=True)
    choose(paths, enabled)
    return backup if kept else None
