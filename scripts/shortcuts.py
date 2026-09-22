"""Hyprflip shortcut preferences. Values are data, never shell/Lua programs."""
import ctypes
import json
import os
from pathlib import Path
import re
import uuid

from workflow import SetupError

# Stable IDs are shared with examples/shortcuts.lua.
DEFINITIONS = (
    ('flip', 'Flip card', 'F', 'turn window over'),
    ('create', 'Create, unfold or fold', 'O', 'unfold, fold or create a card'),
    ('edit', 'Edit card', 'C', 'edit card'),
    ('library', 'Open saved cards', 'L', 'open saved card'),
    ('find', 'Find an app in cards', 'K', 'find an app in cards'),
    ('peek', 'Hold to peek', 'space', 'hold to peek at the other side'),
    ('unpair', 'Ungroup card', 'U', 'separate windows'),
    ('mark', 'Mark first app', 'M', 'mark first side'),
    ('pair', 'Pair with marked app', 'P', 'attach second side'),
    ('attach_h', 'Add app beside', 'H', 'attach pane beside'),
    ('attach_v', 'Add app below', 'V', 'attach pane below'),
    ('release', 'Remove focused app', 'E', 'release focused pane'),
    ('cancel', 'Cancel pairing', 'Escape', 'cancel pairing'),
)
BY_ID = {row[0]: row for row in DEFINITIONS}
DESCRIPTIONS = {'Hyprflip: ' + row[3]: row[0] for row in DEFINITIONS}
DESCRIPTIONS['Hyprflip: unfold or fold both faces'] = 'create'
MODS = ((64, 'Super'), (4, 'Ctrl'), (8, 'Alt'), (1, 'Shift'))


def normalize(mask, key):
    if type(mask) is not int or mask & ~77 or not mask & 76:
        raise SetupError('Include Super, Ctrl or Alt in the shortcut.')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,40}', key):
        raise SetupError('Press a letter, number, function key or navigation key.')
    xkb = ctypes.CDLL('libxkbcommon.so.0')
    xkb.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
    xkb.xkb_keysym_from_name.restype = ctypes.c_uint32
    symbol = xkb.xkb_keysym_from_name(key.encode(), 1)
    if not symbol or key.lower() in ('shift_l', 'shift_r', 'control_l', 'control_r',
                                    'alt_l', 'alt_r', 'super_l', 'super_r', 'meta_l', 'meta_r'):
        raise SetupError('Choose a key together with its modifiers.')
    return mask, key.upper() if len(key) == 1 else key


def label(mask, key):
    return '+'.join([name for bit, name in MODS if mask & bit] + [key.capitalize() if key.lower() == 'space' else key])


def path(ipc):
    env = ipc.env if ipc.env is not None else os.environ
    return Path(env.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'hyprflip/shortcuts'


def read(ipc):
    location = path(ipc)
    result = {}
    if not location.exists(): return result
    for line in location.read_text().splitlines():
        fields = line.split('\t')
        if len(fields) != 3 or fields[0] not in BY_ID:
            raise SetupError('The saved shortcuts file is invalid. Restore it from a backup.')
        try: result[fields[0]] = normalize(int(fields[1]), fields[2])
        except (ValueError, SetupError) as error:
            raise SetupError('The saved shortcuts file is invalid. Restore it from a backup.') from error
    return result


def chords(bind):
    return int(bind.get('modmask', 0)), str(bind.get('key', '')).lower()


def snapshot(ipc):
    binds = ipc.data('-j', 'binds')
    # All binds are returned for local conflict checks; never expose command arguments.
    occupied = [{'mask': b.get('modmask', 0), 'key': b.get('key', ''), 'keycode': b.get('keycode', 0),
                 'submap': b.get('submap', ''), 'universal': b.get('submap_universal') in (True, 'true'),
                 'id': DESCRIPTIONS.get(b.get('description')), 'label': b.get('description') or 'Another desktop action'}
                for b in binds]
    available = ipc.call('repl', 'local m=package.loaded["hypr.hyprflip-shortcuts"]; return m and m.version == 1 or false') == 'true'
    rows = []
    for ident, title, default, description in DEFINITIONS:
        matches = [b for b in binds if DESCRIPTIONS.get(b.get('description')) == ident and not b.get('submap')]
        current = matches[0] if len(matches) == 1 else None
        rows.append({'id': ident, 'label': title, 'mask': current['modmask'] if current else 76,
                     'key': current['key'] if current else '', 'default_mask': 76, 'default_key': default,
                     'shortcut': label(current['modmask'], current['key']) if current else 'Not assigned' if not matches else 'Multiple bindings',
                     'editable': available and current is not None and bool(current.get('key')) and not current.get('keycode')})
    return {'available': available, 'rows': rows, 'occupied': occupied}


def save(ipc, ident, mask, key):
    if ident not in BY_ID: raise SetupError('Choose a Hyprflip action.')
    mask, key = normalize(mask, key)
    state = snapshot(ipc)
    row = next(r for r in state['rows'] if r['id'] == ident)
    if not row['editable']:
        raise SetupError('Update the guided setup to enable shortcut editing.')
    # Refuse ambiguous source chords too: unbind must never remove somebody else's binding.
    old = (row['mask'], row['key'].lower())
    for bind in state['occupied']:
        chord = (bind['mask'], bind['key'].lower())
        if bind['id'] == ident and not bind['submap']: continue
        if chord == old or (chord == (mask, key.lower()) and (not bind['submap'] or bind['universal'])):
            raise SetupError(label(*chord) + ' is used by ' + bind['label'] + '. Choose another shortcut.')
        # Numeric physical bindings cannot reliably be compared with layout-dependent symbols.
        if bind['keycode'] and bind['mask'] == mask and (not bind['submap'] or bind['universal']):
            raise SetupError('A physical-key binding uses these modifiers. Choose different modifiers or edit that binding first.')
        # Some Hyprland builds omit both the symbol and code for configured
        # physical bindings. An empty key is unknown, not a free combination.
        if not bind['key'] and bind['mask'] == mask and (not bind['submap'] or bind['universal']):
            raise SetupError('Cannot check against “' + bind['label'] + '”: Hyprland did not report its key. Choose different modifiers.')
    preferences = read(ipc)
    location = path(ipc)
    previous = location.read_bytes() if location.exists() else None
    preferences[ident] = (mask, key)
    location.parent.mkdir(parents=True, exist_ok=True)
    temporary = location.with_name('.shortcuts-' + uuid.uuid4().hex)
    def apply(m, k):
        # ID, mask and keysym have a strict grammar, and JSON string escaping is valid here.
        reply = ipc.call('repl', 'return require("hypr.hyprflip-shortcuts").configure(' +
                         json.dumps(ident) + ',' + str(m) + ',' + json.dumps(k) + ')')
        if reply != 'true': raise SetupError('The shortcut could not be applied. Reopen Settings and try again.')
    try:
        temporary.write_text(''.join(f'{i}\t{m}\t{k}\n' for i, (m, k) in sorted(preferences.items())))
        temporary.replace(location)
        apply(mask, key)
        actual = next(r for r in snapshot(ipc)['rows'] if r['id'] == ident)
        if (actual['mask'], actual['key'].lower()) != (mask, key.lower()):
            raise SetupError('The shortcut did not register. Its previous setting was restored.')
    except Exception:
        if previous is None: location.unlink(missing_ok=True)
        else:
            temporary.write_bytes(previous)
            temporary.replace(location)
        apply(row['mask'], row['key'])
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return BY_ID[ident][1] + ': ' + label(mask, key)
