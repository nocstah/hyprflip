#!/usr/bin/env python3
"""Create and edit Hyprflip cards using Omarchy's native menu."""
import argparse
import configparser
from copy import deepcopy
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import fcntl
import hashlib
import html
import json
from itertools import combinations
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import uuid


class SetupError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


TRANSITIONS = {
    'flip': ('Flip', 'Turn sideways'),
    'vertical': ('Vertical flip', 'Turn top to bottom'),
    'slide': ('Slide', 'Move faces sideways'),
    'fade': ('Fade', 'Blend faces gently'),
    'dissolve': ('Dissolve', 'Experimental · Reveal in soft fragments'),
    'portal': ('Portal', 'Experimental · Reveal from the centre'),
    'instant': ('Instant', 'Switch without motion'),
}


class Hyprctl:
    def __init__(self, env=None):
        self.env = env

    def call(self, *args):
        result = subprocess.run(['hyprctl', *args], env=self.env, capture_output=True,
                                text=True, timeout=8)
        reply = result.stdout.strip()
        if result.returncode or reply.startswith('error') or 'Lua error' in reply:
            raise SetupError(reply.removeprefix('error: ').strip() or 'Hyprland is not responding.')
        return reply

    def data(self, *args):
        try:
            return json.loads(self.call(*args))
        except ValueError as error:
            raise SetupError('Hyprflip is unavailable. Load the container plugin and try again.') from error

    def windows(self):
        return {w['address']: w for w in self.data('-j', 'clients')}

    def status(self):
        return self.data('hyprflip', 'status')

    def action(self, action):
        return self.call('hyprflip', action)

    def save_transition(self, mode):
        if mode not in TRANSITIONS:
            raise SetupError('Choose a transition from the menu.')
        env = self.env if self.env is not None else os.environ
        root = Path(env.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'hyprflip'
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'transition'
        previous = path.read_bytes() if path.exists() else None
        old_mode = self.status()['transition']
        # This is a plain mode name, not a sourced configuration program.
        temporary = path.with_name('transition-' + uuid.uuid4().hex)
        try:
            temporary.write_text(mode + '\n')
            temporary.replace(path)
            self.call('eval', f'hl.config({{plugin={{hyprflip={{transition="{mode}"}}}}}})')
            if self.status()['transition'] != mode:
                raise SetupError('The transition preference could not be applied.')
        except Exception:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                temporary.write_bytes(previous)
                temporary.replace(path)
            if old_mode in TRANSITIONS:
                try:
                    self.call('eval', f'hl.config({{plugin={{hyprflip={{transition="{old_mode}"}}}}}})')
                except (SetupError, OSError, subprocess.TimeoutExpired):
                    pass
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def focus(self, address):
        if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
            raise SetupError('The selected window is no longer available.')
        self.call('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.data('-j', 'activewindow').get('address') == address:
                return
            time.sleep(.04)
        raise SetupError('The window could not receive focus. Close any fullscreen overlay and try again.')

    def focused(self, *operations):
        # Keep focus validation and the action together; a pointer/app focus
        # event can otherwise arrive between separate hyprctl requests.
        chunks = []
        for address, action in operations:
            if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
                raise SetupError('The selected window is no longer available.')
            name, _, argument = action.partition(' ')
            if not (name in ('mark', 'pair', 'release', 'unpair', 'other_side') and not argument or
                    name == 'other_side' and re.fullmatch(r'0x[0-9a-fA-F]+', argument) or
                    name == 'attach' and argument in ('horizontal', 'vertical') or
                    name == 'layout' and argument in ('horizontal', 'vertical', 'balance') or
                    name == 'arrange' and re.fullmatch(r'(horizontal|vertical)( 0x[0-9a-fA-F]+:[0-9.eE+-]+){1,3}', argument) or
                    name == 'preview' and argument in TRANSITIONS):
                raise SetupError('The card action is unavailable.')
            parameter = json.dumps(argument) if argument else ''
            chunks.append(f'''do
                local target = hl.get_window("address:{address}")
                assert(target, "The selected app closed. Open the picker again.")
                hl.dispatch(hl.dsp.focus({{window="address:{address}"}}))
                local current = hl.get_active_window()
                assert(current and current.address == target.address,
                       "The selected app could not receive focus. Close any overlay and try again.")
                assert(hl.plugin.hyprflip.{name}({parameter}))
            end''')
        self.call('eval', '\n'.join(chunks))

    def move(self, address, workspace):
        if not re.fullmatch(r'0x[0-9a-fA-F]+', address) or not 0 < workspace < 2**31:
            raise SetupError('The selected app or workspace is no longer available.')
        self.call('dispatch', f'hl.dsp.window.move({{window="address:{address}",workspace="{workspace}",follow=false}})')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            window = self.windows().get(address)
            if window and window['workspace']['id'] == workspace:
                return
            time.sleep(.04)
        raise SetupError('The app could not move to the card workspace. Open the picker and try again.')

    def tile(self, window):
        address = window['address']
        if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
            raise SetupError('The selected app is no longer available.')
        chilled = any(t.rstrip('*') == 'chillmode' for t in window.get('tags', []))
        if chilled:
            self.call('eval', f'assert(chillmode and chillmode.handoff and chillmode.handoff("{address}"), '
                      '"Chill mode needs the Hyprflip integration before this app can be tiled.")')
        else:
            self.call('dispatch', f'hl.dsp.window.float({{window="address:{address}",action="disable"}})')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = self.windows().get(address)
            if current and not current['floating']:
                return
            time.sleep(.04)
        raise SetupError('The app could not stay tiled. Check its floating window rule, then try again.')

    def restore_float(self, window):
        address = window['address']
        if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
            raise SetupError('The selected app is no longer available.')
        x, y = map(int, window['at'])
        width, height = map(int, window['size'])
        chilled = any(t.rstrip('*') == 'chillmode' for t in window.get('tags', []))
        if chilled:
            self.call('eval', f'assert(chillmode and chillmode.handback and '
                      f'chillmode.handback("{address}", {x}, {y}, {width}, {height}), '
                      '"Chill mode could not restore the app position.")')
        else:
            self.call('eval', f'hl.dispatch(hl.dsp.window.float({{window="address:{address}",action="enable"}})); '
                      f'hl.dispatch(hl.dsp.window.resize({{window="address:{address}",x={width},y={height}}})); '
                      f'hl.dispatch(hl.dsp.window.move({{window="address:{address}",x={x},y={y}}}))')


def clean(text, limit=120):
    return ' '.join(''.join(' ' if unicodedata.category(c).startswith('C') else c
                            for c in str(text)).split())[:limit]


def app_name(window):
    name = window.get('class') or window.get('initialClass') or 'Window'
    lower = name.lower()
    if 'gmail' in lower or 'mail.google.com' in lower:
        return 'Gmail'
    if 'whatsapp' in lower:
        return 'WhatsApp'
    return clean({'org.telegram.desktop': 'Telegram', 'brave-browser': 'Brave',
                  'foot': 'Terminal', 'kitty': 'Terminal', 'Alacritty': 'Terminal'}.get(name, name), 60)


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    detail: str = ''


def window_choices(windows):
    result, seen = [], set()
    for window in windows:
        label, detail = app_name(window), clean(window.get('title') or 'Open window')
        original, number = label, 1
        while (label, detail) in seen:
            number += 1
            label = f'{original} ({number})'
        seen.add((label, detail))
        result.append(Choice(window['address'], label, detail))
    return result


def workspace_name(window):
    workspace = window['workspace']
    number, name = workspace['id'], clean(workspace.get('name', ''), 40)
    return str(number) if not name or name == str(number) else f'{number} ({name})'


class Request:
    """A newer create/edit request supersedes a waiting picker."""
    def __init__(self, runtime, instance):
        suffix = hashlib.sha256(instance.encode()).hexdigest()[:16]
        self.current = runtime / f'hyprflip-setup-{suffix}.current'
        self.lock = runtime / f'hyprflip-setup-{suffix}.lock'
        self.token = uuid.uuid4().hex

    @contextmanager
    def exclusive(self):
        with self.lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def start(self):
        with self.exclusive():
            self.current.write_text(self.token)

    def check(self):
        if not self.current.exists() or self.current.read_text() != self.token:
            raise Cancelled()

    def finish(self):
        with self.exclusive():
            if self.current.exists() and self.current.read_text() == self.token:
                self.current.unlink()


class OmarchyMenu:
    def __init__(self, directory, request):
        self.directory, self.request, self.serial = directory, request, 0

    def request_value(self, prompt, rows=(), mode='select'):
        self.request.check()
        self.serial += 1
        selection = self.directory / f'{self.serial}.selection'
        done = self.directory / f'{self.serial}.done'
        payload = {'mode': mode, 'prompt': prompt, 'options': list(rows), 'width': 560,
                   'maxHeight': 560, 'selectionFile': str(selection), 'doneFile': str(done)}
        result = subprocess.run(['omarchy-shell', 'shell', 'summon', 'omarchy.menu', json.dumps(payload)],
                                capture_output=True, text=True, timeout=8,
                                env=os.environ | {'OMARCHY_SHELL_IPC_TIMEOUT': os.environ.get('OMARCHY_SHELL_IPC_TIMEOUT', '5s')})
        if result.returncode or result.stdout.strip() != 'ok':
            raise SetupError('The Omarchy menu is unavailable. Start the shell and try again.')
        deadline = time.monotonic() + 300
        while not done.exists():
            self.request.check()
            if time.monotonic() >= deadline:
                raise SetupError('Window selection expired. Press Escape, then open setup again.')
            time.sleep(.06)
        self.request.check()
        if not selection.exists():
            raise Cancelled()
        return selection.read_text().rstrip('\n')

    def input(self, prompt):
        return self.request_value(prompt, mode='input')

    def choose(self, prompt, choices):
        # The shell accepts <icon> TAB <label> TAB <detail> and returns label/detail.
        rows = ['\t' + c.label + ('\t' + c.detail if c.detail else '') for c in choices]
        selected = self.request_value(prompt, rows)
        for choice in choices:
            if selected == choice.label + ('\t' + choice.detail if choice.detail else ''):
                return choice.value
        raise SetupError('That window selection changed. Open setup again.')


class Setup:
    def __init__(self, ipc, menu):
        self.ipc, self.menu = ipc, menu

    def eligible(self, windows, state, workspace=None):
        owned = {a for card in state.get('containers', []) for face in card['faces'] for a in face}
        owned.update(a for pair in state.get('pairs', []) for a in (pair['front'], pair['back']))
        return {a: w for a, w in windows.items() if a not in owned and w.get('mapped', True)
                and (not w.get('floating') or state.get('workspace_protection'))
                and not any(w.get(k) for k in ('pinned', 'grouped', 'fullscreen', 'hidden'))
                and w['workspace']['id'] > 0 and (workspace is None or w['workspace']['id'] == workspace)}

    @contextmanager
    def reserve(self, selected, state, destination=None):
        tokens = []
        try:
            if state.get('workspace_protection'):
                workspaces = {w['workspace']['id'] for w in selected.values()}
                if destination is not None: workspaces.add(destination)
                for workspace in sorted(workspaces):
                    token = uuid.uuid4().hex
                    tokens.append(token)
                    self.ipc.action(f'reserve {workspace} {token}')
            yield
        finally:
            for token in tokens:
                try:
                    self.ipc.action('unreserve ' + token)
                except (SetupError, OSError, subprocess.TimeoutExpired):
                    pass  # A disconnected helper's reservation expires within a minute.

    def confirm_tiling(self, selected, label):
        floating = [w for w in selected.values() if w.get('floating')]
        if floating:
            answer = self.menu.choose('These apps need to be tiled', [
                Choice('tile', label, clean(', '.join(app_name(w) for w in floating), 110)),
                Choice('cancel', 'Cancel', 'Keep the current arrangement')])
            if answer != 'tile':
                raise Cancelled()

    def tile_selected(self, selected, tiled):
        for window in selected.values():
            if window.get('floating'):
                tiled.append(window)
                self.ipc.tile(window)

    def restore_floats(self, tiled):
        failures = []
        for original in reversed(tiled):
            try:
                current = self.eligible(self.ipc.windows(), self.ipc.status()).get(original['address'])
                if current and all(current[k] == original[k] for k in ('pid', 'class')):
                    self.ipc.restore_float(original)
            except (SetupError, OSError, subprocess.TimeoutExpired):
                failures.append(app_name(original))
        if failures:
            raise SetupError('The card could not be created. Restore the floating position of '
                             + ', '.join(failures) + '; the apps are still open.')

    def choose_window(self, prompt, candidates, workspace, prefix='', leading=()):
        """Local apps first; other workspaces are explicit, cancellable submenus."""
        ordered = sorted(candidates, key=lambda w: w['focusHistoryID'] if w.get('focusHistoryID', -1) >= 0 else 1_000_000)
        local = [w for w in ordered if w['workspace']['id'] == workspace]
        groups = {}
        for window in ordered:
            source = window['workspace']['id']
            if source != workspace:
                groups.setdefault(source, []).append(window)
        choices = list(leading) + [Choice(c.value, prefix + c.label, c.detail) for c in window_choices(local)]
        for source, apps in sorted(groups.items()):
            names = ', '.join(dict.fromkeys(app_name(w) for w in apps))
            choices.append(Choice(f'workspace:{source}', f'Add from workspace {workspace_name(apps[0])}',
                                  'Move an app here · ' + clean(names, 85)))
        while True:
            selected = self.menu.choose(prompt, choices)
            group = next((apps for source, apps in groups.items() if selected == f'workspace:{source}'), None)
            if group is None:
                if selected not in {c.value for c in choices}:
                    raise SetupError('That app selection changed. Open the picker again.')
                return selected
            subchoices = window_choices(group) + [Choice('back', 'Back to all apps')]
            selected = self.menu.choose(f'Workspace {workspace_name(group[0])}: move an app here', subchoices)
            if selected == 'back':
                continue
            if selected not in {w['address'] for w in group}:
                raise SetupError('That app selection changed. Open the picker again.')
            return selected

    def import_windows(self, selected, workspace, moved):
        for original in selected.values():
            if original['workspace']['id'] != workspace:
                # Record before IPC so a timeout after a successful move can
                # still be recovered. All menu choices precede the first move.
                moved.append(original)
                self.ipc.move(original['address'], workspace)

    def restore_imports(self, moved, workspace):
        failures = []
        for original in reversed(moved):
            address = original['address']
            try:
                current = self.eligible(self.ipc.windows(), self.ipc.status()).get(address)
                if (current and current['workspace']['id'] == workspace
                        and all(current[k] == original[k] for k in ('pid', 'class'))):
                    self.ipc.move(address, original['workspace']['id'])
            except (SetupError, OSError, subprocess.TimeoutExpired):
                failures.append(workspace_name(original))
        if failures:
            raise SetupError('The edit failed and an app could not return to workspace '
                             + ', '.join(failures) + '. It is still open; move it back manually.')

    def restore_focus(self, original):
        current = self.ipc.windows().get(original['address'])
        if (current and all(current[k] == original[k] for k in ('pid', 'class', 'workspace'))
                and self.ipc.data('-j', 'activeworkspace')['id'] == original['workspace']['id']
                and self.ipc.data('-j', 'activewindow').get('address') != original['address']):
            self.ipc.focus(original['address'])

    def prepare(self, front):
        windows, state = self.ipc.windows(), self.ipc.status()
        source = windows.get(front)
        if not source:
            raise SetupError('Focus the window you want on the front, then press Super+Ctrl+Alt+O.')
        if not state.get('container_provider'):
            raise SetupError('The container provider is unavailable. Load the matching Hyprflip and hy3 plugins.')
        workspace = source['workspace']['id']
        layouts = {w['id']: w['tiledLayout'] for w in self.ipc.data('-j', 'workspaces')}
        if workspace < 1 or layouts.get(workspace) != 'hy3':
            raise SetupError('Use a normal workspace with the hy3 container layout, then open setup again.')
        eligible = self.eligible(windows, state)
        if front not in eligible:
            if source.get('floating'):
                if any(tag.rstrip('*') == 'chillmode' for tag in source.get('tags', [])):
                    raise SetupError(f'{app_name(source)} is floating in Chill mode. '
                                     'Turn off Chill mode on this workspace, then open setup again.')
                raise SetupError(f'{app_name(source)} is floating. Tile it, then open setup again.')
            if source.get('fullscreen'):
                raise SetupError('Leave fullscreen, then open setup again.')
            raise SetupError('Choose an ungrouped, tiled window for the front.')
        candidates = [w for a, w in eligible.items() if a != front]
        if not candidates:
            raise SetupError('Open another ungrouped, tiled app, then press Super+Ctrl+Alt+O again.')
        back = self.choose_window(f'Back of {app_name(source)}: choose a window', candidates, workspace)
        if back not in {w['address'] for w in candidates}:
            raise SetupError('The selected window is no longer available.')
        selected = [front, back]
        # Older installed providers remain usable while the helper is updated.
        for count in range(2, state.get('container_max_panes', 2) + 1):
            remaining = [w for w in candidates if w['address'] not in selected]
            if not remaining:
                break
            names = ', '.join(app_name(windows[a]) for a in selected[1:])
            ordinal = 'second' if count == 2 else 'third'
            finish = 'Only one app' if count == 2 else 'Only two apps'
            extra = self.choose_window(f'Add a {ordinal} app to the back?', remaining, workspace, prefix='Add ',
                                       leading=[Choice('create', finish, clean(names, 90) + ' on the back')])
            if extra == 'create':
                break
            if extra not in {w['address'] for w in remaining}:
                raise SetupError('The selected companion is no longer available.')
            selected.append(extra)
        # All choices are complete before changing a mark, focus or layout.
        selected = deepcopy({a: windows[a] for a in selected})
        self.confirm_tiling(selected, 'Tile and create card')
        return selected

    def apply(self, selected):
        with self.reserve(selected, self.ipc.status()):
            self.apply_reserved(selected)

    def apply_reserved(self, selected, arrangement=None, destination=None):
        front, back, *extra = selected
        workspace = destination if destination is not None else selected[front]['workspace']['id']
        now, state = self.ipc.windows(), self.ipc.status()
        eligible = self.eligible(now, state)
        for address, original in selected.items():
            if address not in eligible or any(now[address][key] != original[key] for key in ('pid', 'class', 'workspace', 'floating')):
                raise SetupError('A selected window closed, moved or joined a group. Open setup again.')
        if self.ipc.data('-j', 'activeworkspace')['id'] != workspace:
            raise SetupError('The workspace changed. Return to the front window and open setup again.')
        if any(w.get('fullscreen') and w['workspace']['id'] == workspace for w in now.values()):
            raise SetupError('Close the fullscreen overlay on this workspace, then open setup again.')
        layouts = {w['id']: w['tiledLayout'] for w in self.ipc.data('-j', 'workspaces')}
        if not state.get('container_provider') or layouts.get(workspace) != 'hy3':
            raise SetupError('The container layout changed. Open setup again on a hy3 workspace.')
        created = None
        moved = []
        tiled = []
        try:
            self.tile_selected(selected, tiled)
            self.import_windows(selected, workspace, moved)
            self.ipc.focused((front, 'mark'), (back, 'pair'))
            created = next((c for c in self.ipc.status()['containers'] if c['faces'] == [[front], [back]]), None)
            if not created:
                raise SetupError('The card could not be created. Open setup again.')
            if arrangement:
                for face in arrangement['faces']:
                    first = face['windows'][0]
                    for companion in face['windows'][1:]:
                        self.ipc.focused((companion, 'mark'), (first, 'attach ' + face['axis']))
                    self.restore_ratios(face)
                    self.ipc.focus(face['windows'][face['focus']])
                face = arrangement['faces'][arrangement['active']]
                self.ipc.focus(face['windows'][face['focus']])
                restored = next((c for c in self.ipc.status()['containers'] if c['id'] == created['id']), None)
                if not restored or restored['faces'] != [f['windows'] for f in arrangement['faces']]:
                    raise SetupError('The saved card could not be rebuilt. Its apps are still open.')
            elif extra:
                # Prefer the longer axis, as temporary unfolding does. The
                # explicit H/V shortcuts remain available for other arrangements.
                axis = 'horizontal' if created['box'][2] >= created['box'][3] else 'vertical'
                for companion in extra:
                    self.ipc.focused((companion, 'mark'), (back, 'attach ' + axis))
            if not arrangement: self.ipc.focus(front)
        except Exception:
            # Remove only the card created here, never a pre-existing or edited
            # card. Do not close applications or try to replay a stale layout.
            current = self.ipc.status()
            previous_ids = {c['id'] for c in state.get('containers', [])}
            card = next((c for c in current['containers'] if
                         (created and c['id'] == created['id']) or
                         (not created and c['id'] not in previous_ids and
                          c['faces'] == [[front], [back]])), None)
            if card and all(a in selected for face in card['faces'] for a in face):
                self.ipc.focused((card['current'], 'unpair'))
            if current.get('marked') in selected:
                self.ipc.action('cancel')
            try:
                self.restore_imports(moved, workspace)
            finally:
                try:
                    self.restore_floats(tiled)
                finally:
                    self.restore_focus(selected[front])
            raise

    def restore_ratios(self, face):
        panes = face['windows']
        if len(panes) == 1: return
        axis = int(face['axis'] == 'vertical')
        for _ in range(2):
            # Move split boundaries, not individual target widths. First pass
            # spare space rightward, then leftward. A large pane can otherwise
            # try to take more than its immediate neighbour has and get refused.
            for sign, indices in ((-1, range(len(panes)-1)), (1, reversed(range(len(panes)-1)))):
                for index in indices:
                    time.sleep(.08)
                    windows = self.ipc.windows()
                    total = sum(windows[a]['size'][axis] for a in panes)
                    delta = round(sum(face['ratios'][:index+1]) * total -
                                  sum(windows[a]['size'][axis] for a in panes[:index+1]))
                    if sign * delta > 1:
                        pane = panes[index]
                        self.ipc.focus(pane)
                        x, y = (0, delta) if axis else (delta, 0)
                        self.ipc.call('dispatch', f'hl.dsp.window.resize({{window="address:{pane}",x={x},y={y},relative=true}})')
        time.sleep(.1)
        windows = self.ipc.windows()
        total = sum(windows[a]['size'][axis] for a in panes)
        if any(abs(windows[a]['size'][axis] / total - r) > .035 for a, r in zip(panes, face['ratios'])):
            raise SetupError('The saved split does not fit here. Make more room on this workspace, then restore again.')


@dataclass(frozen=True)
class EditPlan:
    anchor: str
    card: dict
    windows: dict
    action: str = ''
    candidate: str | None = None
    removal: str | None = None
    transition: str | None = None


class Edit(Setup):
    """Choose first, then revalidate the exact card and face before editing it."""
    def choose_transition(self, plan):
        while True:
            _, state = self.validate(plan)
            available = state.get('transition_modes', [])
            choices = [Choice(mode, label, ('Current · ' if state.get('transition') == mode else '') + detail)
                       for mode, (label, detail) in TRANSITIONS.items() if mode in available]
            mode = self.menu.choose('Transition for all cards', choices)
            if mode not in {c.value for c in choices}:
                raise SetupError('That transition is unavailable. Open Edit card again.')
            label = TRANSITIONS[mode][0]
            while True:
                options = [Choice('use', f'Use {label}', 'Apply to all cards'),
                           Choice('back', 'Back to transitions')]
                if mode != 'instant' and not plan.card['unfolded']:
                    options.insert(0, Choice('preview', f'Preview {label}', 'Turn over and back · Keep current preference'))
                answer = self.menu.choose(label, options)
                if answer == 'use': return mode
                if answer == 'back': break
                if answer != 'preview' or mode == 'instant' or plan.card['unfolded']:
                    raise SetupError('Choose a transition action from the menu.')
                self.validate(plan)
                self.ipc.focused((plan.anchor, 'preview ' + mode))
                deadline = time.monotonic() + 8
                while self.ipc.status().get('animating'):
                    if hasattr(self.menu, 'request'): self.menu.request.check()
                    if time.monotonic() >= deadline:
                        raise SetupError('The preview did not finish. Open Edit card again.')
                    time.sleep(.04)
                self.validate(plan)
    def validate(self, plan, focus=True):
        windows, state = self.ipc.windows(), self.ipc.status()
        card = next((c for c in state.get('containers', []) if c['id'] == plan.card['id']), None)
        if (not state.get('container_provider') or state.get('animating') or not card
                or any(card[k] != plan.card[k] for k in ('faces', 'active', 'current', 'unfolded'))):
            raise SetupError('The card changed. Focus the side you want and open Edit card again.')
        workspace = plan.windows[plan.anchor]['workspace']['id']
        layouts = {w['id']: w['tiledLayout'] for w in self.ipc.data('-j', 'workspaces')}
        if workspace < 1 or layouts.get(workspace) != 'hy3':
            raise SetupError('Edit card needs a normal workspace with the hy3 container layout.')
        for address, original in plan.windows.items():
            current = windows.get(address)
            if (not current or not current.get('mapped', True)
                    or any(current[k] != original[k] for k in ('pid', 'class', 'workspace'))
                    or any(current.get(k) for k in ('pinned', 'grouped'))
                    or current.get('floating') != original.get('floating')
                    or (current.get('floating') and address != plan.candidate)):
                raise SetupError('An app closed, moved or joined another group. Open Edit card again.')
        if focus and (self.ipc.data('-j', 'activeworkspace')['id'] != workspace
                or self.ipc.data('-j', 'activewindow').get('address') not in (None, plan.anchor)):
            raise SetupError('Focus changed. Return to the side you want and open Edit card again.')
        if any(w.get('fullscreen') and w['workspace']['id'] == workspace for w in windows.values()):
            raise SetupError('Leave fullscreen on this workspace, then open Edit card again.')
        if plan.candidate and plan.candidate not in self.eligible(windows, state):
            raise SetupError('That app is no longer available. Open Edit card and choose another app.')
        return windows, state

    def prepare(self, anchor):
        windows, state = self.ipc.windows(), self.ipc.status()
        card = next((c for c in state.get('containers', []) if any(anchor in f for f in c['faces'])), None)
        if not card:
            if any(anchor in (p['front'], p['back']) for p in state.get('pairs', [])):
                raise SetupError('This is a native window group. Use Super+Ctrl+Alt+U to ungroup it, '
                                 'then create a tiled card with O on a hy3 workspace to edit its apps.')
            raise SetupError('Focus an app in a Hyprflip card first. Use Super+Ctrl+Alt+O to create one.')
        members = {a: windows[a] for face in card['faces'] for a in face if a in windows}
        if anchor not in members or len(members) != sum(map(len, card['faces'])):
            raise SetupError('An app closed. Focus the card and open Edit card again.')
        plan = EditPlan(anchor, deepcopy(card), deepcopy(members))
        self.validate(plan)
        face = next(f for f in card['faces'] if anchor in f)
        name = app_name(windows[anchor])
        limit = state.get('container_max_panes', 2)
        choices = ([Choice('add', 'Add an app to this side', 'Choose an open app from any workspace')]
                   if len(face) < limit else [])
        if len(face) == 1:
            choices.append(Choice('unpair', 'Ungroup card', 'All apps stay open as separate windows'))
            prompt = f'Edit card: {name}'
        else:
            if state.get('layout_controls'):
                choices.append(Choice('layout', 'Layout of this side…', 'Beside · Stacked · Equal sizes'))
                other = next(f for f in card['faces'] if anchor not in f)
                if len(other) < limit:
                    choices.append(Choice('other_side', 'Move an app to the other side…',
                                          clean('Join ' + ', '.join(app_name(windows[a]) for a in other), 100)))
            choices += [Choice('release:' + c.value, f'Remove {c.label} from card',
                              ('Focused app · ' if c.value == anchor else '') + 'Keep open · ' + c.detail)
                       for c in window_choices([windows[anchor]] + [windows[a] for a in face if a != anchor])]
            prompt = (f'Edit card: this side is full ({limit} apps)' if len(face) >= limit
                      else f'Edit card: {len(face)} apps on this side')
        if state.get('transition_modes'):
            label = TRANSITIONS.get(state.get('transition'), ('Flip', ''))[0]
            choices.append(Choice('transition', 'Transition', label + ' · All cards'))
        choices.extend([Choice('save', 'Save card…', 'Reuse this arrangement after restarting'),
                        Choice('manage', 'Manage card…', 'Update saved card · Rename · Duplicate'),
                        Choice('saved', 'Open saved card…', 'Reuse open apps · Launch missing apps')])
        if state.get('repair_cards'):
            choices.insert(0, Choice('repair', 'Reopen missing apps', 'Restore closed apps from this card’s saved setup'))
        action = self.menu.choose(prompt, choices)
        if action not in {c.value for c in choices}:
            raise SetupError('That action is no longer available. Open Edit card again.')
        removal = None
        if action.startswith('release:'):
            removal, action = action.removeprefix('release:'), 'release'
        if action == 'layout':
            first, second = (windows[a] for a in face[:2])
            vertical = abs(first['at'][1] - second['at'][1]) > abs(first['at'][0] - second['at'][0])
            action = self.menu.choose('Layout of this side', [
                Choice('layout horizontal', 'Beside', 'Current layout' if not vertical else 'Arrange apps in a row'),
                Choice('layout vertical', 'Stacked', 'Current layout' if vertical else 'Arrange apps in a column'),
                Choice('layout balance', 'Equal sizes', 'Keep the current direction')])
            if action not in ('layout horizontal', 'layout vertical', 'layout balance'):
                raise SetupError('Choose a layout from the card menu.')
        if action == 'other_side':
            removal = self.menu.choose('Move to the other side',
                [Choice(c.value, c.label, ('Focused app · ' if c.value == anchor else '') + c.detail)
                 for c in window_choices([windows[anchor]] + [windows[a] for a in face if a != anchor])])
            if removal not in face: raise SetupError('That app is no longer on this side. Open the card menu again.')
        candidate = None
        if action == 'repair': return Saved(self.ipc, self.menu).prepare_repair(plan)
        if action == 'save': return Saved(self.ipc, self.menu).prepare_save(plan)
        if action == 'manage':
            result = Saved(self.ipc, self.menu).prepare_manage(plan)
            if result is None: raise Cancelled()
            return result
        if action == 'saved': return Saved(self.ipc, self.menu).prepare_restore()
        if action == 'transition':
            mode = self.choose_transition(plan)
            return EditPlan(anchor, plan.card, deepcopy(members), action, transition=mode)
        if action == 'add':
            windows, state = self.validate(plan)
            workspace = members[anchor]['workspace']['id']
            candidates = list(self.eligible(windows, state).values())
            if not candidates:
                raise SetupError('Open another ungrouped, tiled app, then choose Add an app to this side.')
            candidate = self.choose_window('Add an app to this side', candidates, workspace)
            if candidate not in {w['address'] for w in candidates}:
                raise SetupError('That app is no longer available. Open Edit card again.')
            members[candidate] = windows[candidate]
            self.confirm_tiling({candidate: windows[candidate]}, 'Tile and add to card')
        return EditPlan(anchor, plan.card, deepcopy(members), action, candidate, removal)

    def apply(self, plan):
        if isinstance(plan, SavedPlan): return Saved(self.ipc, self.menu).apply(plan)
        with self.reserve(plan.windows, self.ipc.status()):
            self.apply_reserved(plan)

    def apply_reserved(self, plan):
        windows, state = self.validate(plan)
        if plan.action not in ('add', 'release', 'unpair', 'transition', 'other_side',
                               'layout horizontal', 'layout vertical', 'layout balance'):
            raise SetupError('Choose an action in Edit card first.')
        if (plan.action == 'other_side' or plan.action.startswith('layout ')) and not state.get('layout_controls'):
            raise SetupError('Update the container plugins before changing the layout.')
        if plan.action == 'transition':
            self.ipc.save_transition(plan.transition)
            return
        if plan.action != 'add':
            try:
                if plan.action == 'other_side':
                    self.ipc.focused((plan.anchor, 'other_side ' + plan.removal))
                else:
                    self.ipc.focused((plan.removal or plan.anchor, plan.action))
            finally:
                if plan.action == 'release' and plan.removal and plan.removal != plan.anchor:
                    self.restore_focus(windows[plan.anchor])
            return
        # A temporary mark uses the same attach action as the direct shortcut.
        # A failed edit must never dissolve the existing card.
        marked = state.get('marked')
        workspace = windows[plan.anchor]['workspace']['id']
        moved = []
        tiled = []
        try:
            self.tile_selected({plan.candidate: plan.windows[plan.candidate]}, tiled)
            self.import_windows({plan.candidate: plan.windows[plan.candidate]}, workspace, moved)
            self.ipc.focus(plan.anchor)
            width, height = self.ipc.windows()[plan.anchor]['size']
            self.ipc.focused((plan.candidate, 'mark'),
                             (plan.anchor, 'attach ' + ('horizontal' if width >= height else 'vertical')))
        except Exception:
            recovery_error = None
            try:
                self.restore_imports(moved, workspace)
            except SetupError as error:
                recovery_error = error
            try:
                self.restore_floats(tiled)
            except SetupError as error:
                recovery_error = error
            try:
                if self.ipc.status().get('marked') == plan.candidate:
                    self.ipc.action('cancel')
                current = self.ipc.windows()
                if self.ipc.data('-j', 'activeworkspace')['id'] == workspace:
                    try:
                        if (marked in self.eligible(current, self.ipc.status(), workspace) and marked in windows
                                and all(current[marked][k] == windows[marked][k] for k in ('pid', 'class', 'workspace'))):
                            self.ipc.focused((marked, 'mark'))
                    finally:
                        if (plan.anchor in current and all(current[plan.anchor][k] == windows[plan.anchor][k]
                                                           for k in ('pid', 'class', 'workspace'))):
                            self.ipc.focus(plan.anchor)
            except (SetupError, OSError, subprocess.TimeoutExpired):
                pass
            if recovery_error:
                raise recovery_error
            raise
        self.ipc.focus(plan.candidate)


@dataclass(frozen=True)
class DesktopApp:
    id: str
    path: Path
    name: str
    wm_class: str
    digest: str
    visible: bool = True


class DesktopApps:
    """Read launcher metadata; GIO handles Exec, field codes and D-Bus activation."""
    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        self.apps = {}
        home = Path(self.env.get('HOME', Path.home()))
        paths = [self.env.get('XDG_DATA_HOME', str(home / '.local/share'))]
        paths += self.env.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':')
        seen = set()
        for path in paths:
            if not Path(path).is_absolute(): continue
            directory = Path(path) / 'applications'
            for desktop in sorted(directory.rglob('*.desktop')):
                identifier = '-'.join(desktop.relative_to(directory).parts)
                if identifier in seen: continue
                seen.add(identifier)  # Hidden entries mask lower-priority copies too.
                try:
                    content = desktop.read_bytes()
                    parser = configparser.ConfigParser(interpolation=None, strict=False)
                    parser.optionxform = str
                    parser.read_string(content.decode('utf-8'))
                    entry = parser['Desktop Entry']
                    if (entry.get('Type') != 'Application' or entry.get('Hidden') == 'true' or
                            not entry.get('Name') or not (entry.get('Exec') or entry.get('DBusActivatable') == 'true')):
                        continue
                    executable = entry.get('TryExec')
                    if executable and not shutil.which(executable, path=self.env.get('PATH', os.defpath)): continue
                    self.apps[identifier] = DesktopApp(identifier, desktop, clean(entry['Name'], 100),
                        entry.get('StartupWMClass', ''), hashlib.sha256(content).hexdigest(), entry.get('NoDisplay') != 'true')
                except (OSError, UnicodeError, configparser.Error, KeyError):
                    continue

    @staticmethod
    def valid_id(value):
        return (isinstance(value, str) and 8 < len(value) <= 512 and value.endswith('.desktop') and
                '/' not in value and '\\' not in value and clean(value, 512) == value)

    def infer(self, app):
        if entry := self.apps.get(app.get('desktop_id')): return entry
        classes = {c.casefold() for c in (app['class'], app['initial_class']) if c}
        entries = [e for e in self.apps.values() if e.id[:-8].casefold() in classes or
                   (e.wm_class and e.wm_class.casefold() in classes)]
        if len(entries) == 1: return entries[0]
        if entries: return None
        entries = [e for e in self.apps.values() if e.name.casefold() == app['label'].casefold()]
        return entries[0] if len(entries) == 1 else None

    def launch(self, entry):
        current = self.apps.get(entry.id)
        if current != entry or hashlib.sha256(entry.path.read_bytes()).hexdigest() != entry.digest:
            raise SetupError('An app launcher changed. Open Saved cards again.')
        return subprocess.Popen(['gio', 'launch', str(entry.path)], env=self.env, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Opening:
    """Cancellable native notification, closed by ID without touching another menu."""
    def __init__(self, name, labels, env):
        self.name, self.labels, self.env = name, labels, env

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='hyprflip-opening-')
        root = Path(self.directory.name)
        self.id, self.answer = root / 'id', root / 'answer'
        with self.id.open('w') as identifier, self.answer.open('w') as answer:
            # Omarchy uses this sender for feedback to an explicit user action,
            # so its cancel control stays visible even while chat alerts are silenced.
            self.process = subprocess.Popen(['notify-send', '--app-name=omarchy-action', '--transient',
                '--expire-time=22000', '--wait', '--action=default=Cancel', '--id-fd', str(identifier.fileno()),
                '--selected-action-fd', str(answer.fileno()), f'Opening “{self.name}”…',
                'Waiting for ' + html.escape(', '.join(self.labels)) + '. Click to cancel; opened apps stay open.'],
                env=self.env, pass_fds=(identifier.fileno(), answer.fileno()),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self

    def check(self):
        if self.answer.read_text().strip() == 'default': raise Cancelled()

    def __exit__(self, *_):
        try:
            identifier = self.id.read_text().strip()
            if identifier.isdecimal():
                subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.Notifications',
                    '--object-path', '/org/freedesktop/Notifications', '--method',
                    'org.freedesktop.Notifications.CloseNotification', identifier], env=self.env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            if self.process.poll() is None: self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=3)
            self.directory.cleanup()


class RecipeStore:
    """Small, versioned data file. Names and window titles are never commands."""
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.root = Path(env.get('XDG_STATE_HOME', str(Path(env.get('HOME', Path.home())) / '.local/state'))) / 'hyprflip'
        self.path = self.root / 'cards.json'

    @staticmethod
    def valid_name(name):
        return isinstance(name, str) and bool(name) and len(name) <= 64 and clean(name, 65) == name

    @staticmethod
    def validate(recipe):
        if not isinstance(recipe, dict) or type(recipe.get('active')) is not int or recipe['active'] not in (0, 1): raise ValueError()
        if not isinstance(recipe['faces'], list) or len(recipe['faces']) != 2: raise ValueError()
        for face in recipe['faces']:
            apps, ratios = face['apps'], face['ratios']
            if not isinstance(apps, list) or not isinstance(ratios, list) or not 1 <= len(apps) <= 3 or len(ratios) != len(apps): raise ValueError()
            if face['axis'] not in ('horizontal', 'vertical') or type(face['focus']) is not int or not 0 <= face['focus'] < len(apps):
                raise ValueError()
            if any(type(r) not in (float, int) or not math.isfinite(r) or not 0 < r <= 1 for r in ratios): raise ValueError()
            if abs(sum(ratios) - 1) > .001: raise ValueError()
            for app in apps:
                for key in ('class', 'initial_class', 'title', 'label'):
                    if not isinstance(app[key], str) or len(app[key]) > 512: raise ValueError()
                if not app['label']: raise ValueError()
                if 'desktop_id' in app and not DesktopApps.valid_id(app['desktop_id']): raise ValueError()

    def read(self):
        if not self.path.exists(): return {}
        try:
            if self.path.stat().st_size > 1024 * 1024: raise ValueError()
            data = json.loads(self.path.read_text())
            if type(data['version']) is not int or data['version'] != 1 or not isinstance(data['cards'], dict) or len(data['cards']) > 100: raise ValueError()
            for name, recipe in data['cards'].items():
                if not self.valid_name(name): raise ValueError()
                self.validate(recipe)
            return data['cards']
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            raise SetupError(f'Saved cards could not be read. Check {self.path}; it has not been overwritten.') from error

    def update(self, name, recipe, previous):
        self.change({name: previous}, {name: recipe})

    def change(self, expected, replacements):
        # Rename removes the source and creates the destination in one locked,
        # atomic write. Concurrent changes to either name must not be lost.
        for name in expected.keys() | replacements.keys():
            if not self.valid_name(name): raise SetupError('Use a card name between 1 and 64 characters.')
        for recipe in replacements.values():
            if recipe is not None: self.validate(recipe)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / 'cards.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cards = self.read()
            if any(cards.get(name) != previous for name, previous in expected.items()):
                raise SetupError('That saved card changed in another menu. Open Saved cards again.')
            for name, recipe in replacements.items():
                if recipe is None: cards.pop(name, None)
                else: cards[name] = recipe
            if len(cards) > 100: raise SetupError('You have 100 saved cards. Delete an unused one before saving another.')
            temporary = self.root / ('cards-' + uuid.uuid4().hex)
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as handle:
                    json.dump({'version': 1, 'cards': cards}, handle, ensure_ascii=False, indent=2, allow_nan=False)
                    handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class SavedPlan:
    action: str
    name: str
    recipe: dict
    previous: dict | None = None
    edit: EditPlan | None = None
    windows: dict | None = None
    arrangement: dict | None = None
    workspace: int | None = None
    focus: str | None = None
    launchers: dict | None = None
    chosen: list | None = None
    card: dict | None = None
    new_name: str | None = None


class Saved(Setup):
    @property
    def store(self): return RecipeStore(getattr(self.ipc, 'env', None))

    @staticmethod
    def describe(recipe):
        return clean(' ↔ '.join(' + '.join(app['label'] for app in face['apps']) for face in recipe['faces']))

    @staticmethod
    def capture(card, windows):
        faces = []
        for side, members in enumerate(card['faces']):
            axis = 0
            if len(members) > 1:
                first, second = (windows[a] for a in members[:2])
                axis = int(abs(first['at'][1] - second['at'][1]) > abs(first['at'][0] - second['at'][0]))
            total = sum(windows[a]['size'][axis] for a in members)
            apps = [{'class': w.get('class', '')[:512], 'initial_class': w.get('initialClass', '')[:512],
                     'title': clean(w.get('title', ''), 512), 'label': app_name(w)} for w in (windows[a] for a in members)]
            remembered = min(members, key=lambda a: windows[a].get('focusHistoryID', -1)
                             if windows[a].get('focusHistoryID', -1) >= 0 else float('inf'))
            faces.append({'apps': apps, 'axis': 'vertical' if axis else 'horizontal',
                          'ratios': [windows[a]['size'][axis] / total for a in members], 'focus': members.index(remembered)})
            if layout := card.get('layouts', [None, None])[side]:
                faces[-1].update(axis=layout['axis'], ratios=list(layout['ratios']), focus=members.index(layout['focused']))
        return {'faces': faces, 'active': card['active']}

    def prepare_save(self, edit):
        windows, _ = Edit(self.ipc, self.menu).validate(edit)
        recipe = self.capture(edit.card, windows)
        name = self.menu.input('Name this card (e.g. Communications)').strip()
        if not self.store.valid_name(name): raise SetupError('Use a card name between 1 and 64 characters.')
        previous = self.store.read().get(name)
        if previous is not None and self.menu.choose(f'Replace saved card “{name}”?', [
                Choice('replace', 'Replace saved card', self.describe(recipe)),
                Choice('cancel', 'Cancel', 'Keep the previously saved arrangement')]) != 'replace': raise Cancelled()
        return SavedPlan('save', name, recipe, previous, edit=edit)

    @staticmethod
    def matches(app, candidates):
        same = [w for w in candidates if Saved.same_app(app, w)]
        exact = [w for w in same if clean(w.get('title', ''), 512) == app['title']]
        return exact[0]['address'] if len(exact) == 1 else (same[0]['address'] if len(same) == 1 else None)

    @staticmethod
    def same_app(app, window):
        return bool((app['class'] and window.get('class') == app['class']) or
                    (app['initial_class'] and window.get('initialClass') == app['initial_class']))

    @staticmethod
    def open_cards(recipe, windows, state):
        result = []
        for card in state.get('containers', []):
            matched = []
            for face, members in zip(recipe['faces'], card['faces']):
                if len(face['apps']) != len(members): break
                chosen = []
                for app in face['apps']:
                    match = Saved.matches(app, [windows[a] for a in members if a in windows and a not in chosen])
                    if not match: break
                    chosen.append(match)
                if len(chosen) != len(members): break
                matched.append(chosen)
            if len(matched) == 2: result.append(card)
        return result

    @staticmethod
    def surviving_slots(recipe, card, windows):
        """An unambiguous, order-preserving subset on each of the same faces."""
        chosen = []
        for face, members in zip(recipe['faces'], card['faces']):
            apps = face['apps']
            if not members or len(members) > len(apps) or any(a not in windows for a in members): return None
            matches = []
            for slots in combinations(range(len(apps)), len(members)):
                if all(Saved.same_app(apps[i], windows[a]) for i, a in zip(slots, members)):
                    score = sum(apps[i]['title'] == clean(windows[a].get('title', ''), 512) for i, a in zip(slots, members))
                    matches.append((score, slots))
            if not matches: return None
            best = max(score for score, _ in matches)
            matches = [slots for score, slots in matches if score == best]
            if len(matches) != 1: return None  # Never guess between indistinguishable slots.
            side = [None] * len(apps)
            for slot, address in zip(matches[0], members): side[slot] = address
            chosen.extend(side)
        return chosen if None in chosen else None

    def prepare_repair(self, edit):
        windows, state = Edit(self.ipc, self.menu).validate(edit)
        if not state.get('repair_cards'):
            raise SetupError('Update the container plugins before reopening missing apps.')
        recipes = self.store.read()
        matches = [(name, recipe, chosen) for name, recipe in sorted(recipes.items(), key=lambda item: item[0].casefold())
                   if (chosen := self.surviving_slots(recipe, edit.card, windows))]
        if not matches:
            if any(self.open_cards(recipe, windows, {'containers': [edit.card]}) for recipe in recipes.values()):
                raise SetupError('All apps from this card’s saved setup are already here.')
            raise SetupError('No saved setup uniquely matches this card’s remaining apps. Save the complete card first; '
                             'apps must still be on their original sides and distinguishable by app or title.')
        index = '0' if len(matches) == 1 else self.menu.choose('Which saved setup should fill this card?', [
            Choice(str(i), name, 'Reopen ' + ', '.join(app['label'] for app, address in
                zip((a for f in recipe['faces'] for a in f['apps']), chosen) if not address))
            for i, (name, recipe, chosen) in enumerate(matches)])
        if index not in map(str, range(len(matches))): raise Cancelled()
        name, recipe, chosen = matches[int(index)]
        return self.prepare_open(name, recipe, windows[edit.anchor]['workspace']['id'], edit.anchor, edit=edit, chosen=chosen)

    def validate_repair(self, plan):
        windows, state = Edit(self.ipc, self.menu).validate(plan.edit, focus=False)
        card = next(c for c in state['containers'] if c['id'] == plan.edit.card['id'])
        if not state.get('repair_cards') or card.get('layouts') != plan.edit.card.get('layouts'):
            raise SetupError('The card layout changed. Open Reopen missing apps again.')
        return windows, state

    def repair_reserved(self, plan, selected, arrangement):
        windows, state = self.validate_repair(plan)
        original = plan.edit
        additions = {a: w for a, w in selected.items() if a not in original.windows}
        eligible = self.eligible(windows, state)
        for address, previous in additions.items():
            if address not in eligible or any(windows[address][k] != previous[k] for k in ('pid', 'class', 'workspace', 'floating')):
                raise SetupError('An app to reopen changed. Open the card menu again.')
        before = self.capture(original.card, windows)
        targets = deepcopy(arrangement['faces'])
        for side, target in enumerate(targets):
            members = original.card['faces'][side]
            old = before['faces'][side]
            missing = sum(r for a, r in zip(target['windows'], target['ratios']) if a not in members)
            weights = dict(zip(members, old['ratios']))
            target['ratios'] = [weights[a] * (1 - missing) if a in weights else r
                                for a, r in zip(target['windows'], target['ratios'])]
            if len(members) > 1: target['axis'] = old['axis']
        expected = deepcopy(original.card['faces'])
        marked, moved, tiled, attempted = state.get('marked'), [], [], []

        def current():
            return next((c for c in self.ipc.status().get('containers', []) if c['id'] == original.card['id']), None)

        def guard():
            card = current()
            if (not card or card['faces'] != expected or card['unfolded'] != original.card['unfolded'] or
                    self.ipc.data('-j', 'activeworkspace')['id'] != plan.workspace):
                raise SetupError('The card changed while reopening apps. Open the card menu again.')
            if not attempted and any(card.get(k) != original.card.get(k) for k in ('active', 'current', 'layouts')):
                raise SetupError('The card layout changed. Open Reopen missing apps again.')
            live = self.ipc.windows()
            if any(a not in live or live[a]['pid'] != w['pid'] or live[a]['class'] != w['class'] or
                   not live[a].get('mapped', True) or any(live[a].get(k) for k in ('floating','grouped','pinned','fullscreen')) or
                   live[a]['workspace']['id'] != plan.workspace for a, w in selected.items()):
                raise SetupError('An app changed while reopening apps.')

        def arrange(side, members, layout):
            argument = layout['axis'] + ''.join(f' {a}:{r:.12g}' for a, r in zip(members, layout['ratios']))
            self.ipc.focused((members[0], 'arrange ' + argument))

        def selection():
            for side, face in enumerate(before['faces']):
                self.ipc.focus(original.card['faces'][side][face['focus']])
            self.ipc.focus(original.anchor)

        try:
            self.tile_selected(additions, tiled)
            self.import_windows(additions, plan.workspace, moved)
            for side, target in enumerate(targets):
                for address in target['windows']:
                    if address in original.windows: continue
                    guard()
                    attempted.append((side, address))
                    self.ipc.focused((address, 'mark'), (original.card['faces'][side][0], 'attach ' + target['axis']))
                    expected[side].append(address)
                if any(a in additions for a in target['windows']):
                    guard()
                    arrange(side, target['windows'], target)
                    expected[side] = list(target['windows'])
            guard()
            selection()
        except Exception as error:
            recovery = []
            # Only undo our own attachments, and only while every original
            # member still belongs to the same face of the same card.
            try:
                card = current()
                intact = card and all(set(members) <= set(card['faces'][s]) for s, members in enumerate(original.card['faces']))
                if intact and attempted:
                    for side, address in reversed(attempted):
                        card = current()
                        if card and address in card['faces'][side]: self.ipc.focused((address, 'release'))
                    card = current()
                    if card and card['faces'] == original.card['faces']:
                        for side in sorted({s for s, _ in attempted}): arrange(side, card['faces'][side], before['faces'][side])
                        selection()
                elif attempted:
                    recovery.append('The original card changed; its remaining apps were left in place.')
            except (SetupError, OSError, subprocess.TimeoutExpired) as failure: recovery.append(str(failure))
            for restore, args in ((self.restore_imports, (moved, plan.workspace)), (self.restore_floats, (tiled,))):
                try: restore(*args)
                except (SetupError, OSError, subprocess.TimeoutExpired) as failure: recovery.append(str(failure))
            if recovery: raise SetupError(str(error) + ' Recovery: ' + ' '.join(recovery)) from error
            raise
        finally:
            if attempted:
                active = self.ipc.data('-j', 'activewindow').get('address')
                try:
                    live, state = self.ipc.windows(), self.ipc.status()
                    if marked and marked in self.eligible(live, state): self.ipc.focused((marked, 'mark'))
                    else: self.ipc.action('cancel')
                finally:
                    if active and active in self.ipc.windows(): self.ipc.focus(active)

    def check_workspace(self, recipe, workspace):
        state = self.ipc.status()
        layouts = {w['id']: w['tiledLayout'] for w in self.ipc.data('-j', 'workspaces')}
        if not state.get('container_provider') or workspace < 1 or layouts.get(workspace) != 'hy3':
            raise SetupError('Open a card on a normal workspace with the hy3 container layout.')
        if any(len(face['apps']) > state.get('container_max_panes', 2) for face in recipe['faces']):
            raise SetupError('Update the container plugins before opening this card; it needs more apps per side.')

    def prepare_restore(self):
        workspace = self.ipc.data('-j', 'activeworkspace')['id']
        focus = self.ipc.data('-j', 'activewindow').get('address')
        while True:
            cards = self.store.read()
            windows, state = self.ipc.windows(), self.ipc.status()
            if not cards:
                card = next((c for c in state.get('containers', []) if any(focus in f for f in c['faces'])), None)
                choices = ([Choice('save', 'Save this card…', 'Give the current arrangement a name')]
                           if card else [Choice('close', 'Close', 'Create a card with Super+Ctrl+Alt+O, then save it from C')])
                if self.menu.choose('No saved cards yet', choices) == 'save' and card:
                    members = {a: windows[a] for face in card['faces'] for a in face}
                    return self.prepare_save(EditPlan(focus, deepcopy(card), deepcopy(members)))
                raise Cancelled()
            names = sorted(cards, key=str.casefold)
            choices = []
            for index, name in enumerate(names):
                recipe = cards[name]
                opened = self.open_cards(recipe, windows, state)
                if opened:
                    places = sorted({workspace_name(windows[c['current']]) for c in opened})
                    detail = 'Open · Workspace ' + ', '.join(places)
                else:
                    matches = [w for w in windows.values() if any(self.same_app(app, w)
                               for face in recipe['faces'] for app in face['apps'])]
                    remote = sorted({workspace_name(w) for w in matches if w['workspace']['id'] != workspace})
                    detail = 'Open here'
                    if remote: detail += ' · Bring apps from ' + ', '.join(remote)
                    if any(w.get('floating') for w in matches): detail += ' · Tile apps'
                choices.append(Choice(str(index), name, detail + ' · ' + self.describe(recipe)))
            choices.append(Choice('manage', 'Manage saved cards…', 'Rename · Duplicate · Review apps'))
            selected = self.menu.choose('Open saved card', choices)
            if selected == 'manage':
                result = self.prepare_manage()
                if result is not None: return result
                continue
            if selected not in map(str, range(len(names))): raise SetupError('Choose a saved card from the menu.')
            name = names[int(selected)]; recipe = cards[name]
            return self.prepare_named(name, recipe, workspace, focus)

    def prepare_named(self, name, recipe, workspace, focus):
        windows, state = self.ipc.windows(), self.ipc.status()
        opened = self.open_cards(recipe, windows, state)
        if opened:
            index = '0' if len(opened) == 1 else self.menu.choose('Choose an open card', [
                Choice(str(i), 'Workspace ' + workspace_name(windows[c['current']]), self.describe(recipe))
                for i, c in enumerate(opened)])
            if index not in map(str, range(len(opened))): raise Cancelled()
            card = opened[int(index)]
            members = {a: windows[a] for face in card['faces'] for a in face}
            return SavedPlan('goto', name, recipe, workspace=workspace, focus=focus,
                             card=deepcopy(card), windows=deepcopy(members))
        return self.prepare_open(name, recipe, workspace, focus)

    def prepare_manage(self, edit=None):
        cards = self.store.read()
        if not cards: raise SetupError('No saved cards yet. Choose Save card in the card menu first.')
        names = sorted(cards, key=str.casefold)
        related = []
        if edit:
            windows, _ = Edit(self.ipc, self.menu).validate(edit)
            # Layout and face transfers should not force retyping the name.
            # Two matching saved variants still require an explicit choice.
            for name, recipe in cards.items():
                remaining = [windows[a] for face in edit.card['faces'] for a in face]
                apps = [app for face in recipe['faces'] for app in face['apps']]
                if len(remaining) != len(apps): continue
                for app in apps:
                    address = self.matches(app, remaining)
                    if address is None: break
                    remaining = [w for w in remaining if w['address'] != address]
                else: related.append(name)
        if len(related) == 1:
            name = related[0]
        else:
            selected = self.menu.choose('Manage saved cards', [
                Choice(str(i), name, self.describe(cards[name])) for i, name in enumerate(names)])
            if selected not in map(str, range(len(names))): raise Cancelled()
            name = names[int(selected)]
        recipe = cards[name]
        workspace = self.ipc.data('-j', 'activeworkspace')['id']
        focus = self.ipc.data('-j', 'activewindow').get('address')
        opened = self.open_cards(recipe, self.ipc.windows(), self.ipc.status())
        choices = [Choice('open', 'Go to open card' if opened else 'Open here', self.describe(recipe))]
        if edit:
            choices.insert(0, Choice('update', 'Update saved card', 'Save the current apps, split sizes and visible side'))
        if not opened:
            choices += [Choice('review', 'Review apps and launchers…', 'Choose which apps to open'),
                        Choice('restore', 'Restore from open apps…', 'Choose windows yourself')]
        choices += [Choice('rename', 'Rename…', 'Change the saved name'),
                    Choice('duplicate', 'Duplicate…', 'Copy this saved setup under a new name'),
                    Choice('delete', 'Delete saved card', 'Keep all running apps and cards'),
                    Choice('back', 'Cancel' if edit else 'Back to saved cards')]
        action = self.menu.choose('Manage “' + name + '”', choices)
        if action not in {c.value for c in choices}: raise Cancelled()
        if action == 'back': return None
        if action == 'open': return self.prepare_named(name, recipe, workspace, focus)
        if action == 'review': return self.prepare_open(name, recipe, workspace, focus, review=True)
        if action == 'restore': return self.prepare_manual(name, recipe, workspace, focus)
        if action == 'update':
            return SavedPlan('update', name, recipe, recipe, edit=edit)
        if action in ('rename', 'duplicate'):
            prompt = f'Rename “{name}” to' if action == 'rename' else f'Name the copy of “{name}”'
            new_name = self.menu.input(prompt).strip()
            if not self.store.valid_name(new_name): raise SetupError('Use a card name between 1 and 64 characters.')
            if new_name in cards: raise SetupError('That saved name already exists. Choose a different name.')
            return SavedPlan(action, name, recipe, new_name=new_name)
        if self.menu.choose(f'Delete saved card “{name}”?', [Choice('delete', 'Delete saved card'),
                                                         Choice('cancel', 'Cancel')]) != 'delete': raise Cancelled()
        return SavedPlan('delete', name, recipe, recipe)

    def prepare_manual(self, name, recipe, workspace, focus):
        windows, state = self.ipc.windows(), self.ipc.status()
        self.check_workspace(recipe, workspace)
        eligible = self.eligible(windows, state)
        chosen = []
        slots = [(side, i, app) for side, face in enumerate(recipe['faces']) for i, app in enumerate(face['apps'])]
        for side, _, app in slots:
            candidates = [w for a, w in eligible.items() if a not in chosen]
            match = self.matches(app, candidates)
            if match is None:
                if not candidates: raise SetupError(f'Open an ungrouped app for {app["label"]}, then restore “{name}” again.')
                match = self.choose_window(f'{"Front" if side == 0 else "Back"}: choose {app["label"]}', candidates, workspace)
            if match not in eligible or match in chosen: raise SetupError('That window selection changed. Restore the card again.')
            chosen.append(match)
        while True:
            choices = [Choice('restore', 'Restore card here', f'Workspace {workspace} · {len(chosen)} apps')]
            for index, ((side, _, _), address) in enumerate(zip(slots, chosen)):
                w = windows[address]
                detail = f'Workspace {workspace_name(w)} · ' + clean(w.get('title', ''), 85)
                choices.append(Choice(str(index), f'{"Front" if side == 0 else "Back"} · {app_name(w)}', detail))
            choices.append(Choice('cancel', 'Cancel', 'Keep the current arrangement'))
            answer = self.menu.choose(f'Restore “{name}”: review apps', choices)
            if answer == 'restore': break
            if answer == 'cancel': raise Cancelled()
            if answer not in map(str, range(len(chosen))): raise SetupError('Choose an app from the review menu.')
            index = int(answer)
            candidates = [w for a, w in eligible.items() if a not in chosen or a == chosen[index]]
            chosen[index] = self.choose_window('Choose a different app', candidates, workspace)
        selected, arrangement = self.arrange(recipe, chosen, windows)
        self.confirm_tiling(selected, 'Tile and restore card')
        return SavedPlan('restore', name, recipe, recipe, windows=selected, arrangement=arrangement, workspace=workspace, focus=focus)

    @staticmethod
    def arrange(recipe, chosen, windows):
        arrangement = deepcopy(recipe)
        offset = 0
        for face in arrangement['faces']:
            count = len(face.pop('apps'))
            face['windows'] = chosen[offset:offset + count]; offset += count
        first, second = (face['windows'][0] for face in arrangement['faces'])
        order = [first, second] + [a for a in chosen if a not in (first, second)]
        selected = deepcopy({a: windows[a] for a in order})
        return selected, arrangement

    def choose_launcher(self, app, catalog):
        entries = sorted((e for e in catalog.apps.values() if e.visible), key=lambda e: (e.name.casefold(), e.id))
        if not entries: raise SetupError('No installed app launchers found. Open your apps, then choose Restore from open apps.')
        selected = self.menu.choose('Launcher for ' + app['label'], [Choice(e.id, e.name, e.id) for e in entries])
        if selected not in {e.id for e in entries}: raise SetupError('That app launcher is no longer available.')
        return catalog.apps[selected]

    def prepare_open(self, name, recipe, workspace, focus, review=False, edit=None, chosen=None):
        self.check_workspace(recipe, workspace)
        windows, state = self.ipc.windows(), self.ipc.status()
        eligible = self.eligible(windows, state)
        catalog = DesktopApps(getattr(self.ipc, 'env', None))
        apps = [app for face in recipe['faces'] for app in face['apps']]
        chosen, launchers = list(chosen) if chosen is not None else [None] * len(apps), {}
        for index, app in enumerate(apps):
            if chosen[index]: continue
            candidates = [w for a, w in eligible.items() if a not in chosen and self.same_app(app, w)]
            match = self.matches(app, candidates)
            if candidates and match is None:
                match = self.choose_window('Choose ' + app['label'], candidates, workspace)
                if match not in {w['address'] for w in candidates}: raise Cancelled()
            if not candidates:
                if any(self.same_app(app, w) for a, w in windows.items() if a not in chosen):
                    raise SetupError(app['label'] + ' is already open but unavailable. Leave fullscreen or release it from its card, then try again.')
                launchers[index] = catalog.infer(app) or self.choose_launcher(app, catalog)
            chosen[index] = match
        while review:
            detail = f'Workspace {workspace} · {len(chosen) - len(launchers)} open · {len(launchers)} to launch'
            choices = [Choice('open', 'Open card here', detail)]
            for index, app in enumerate(apps):
                side = 'Front' if index < len(recipe['faces'][0]['apps']) else 'Back'
                detail = ('Launch ' + launchers[index].name if index in launchers else
                          'Already open · Workspace ' + workspace_name(windows[chosen[index]]))
                choices.append(Choice(str(index), side + ' · ' + app['label'], detail))
            choices.append(Choice('cancel', 'Cancel', 'Keep the current arrangement'))
            answer = self.menu.choose(f'Open “{name}”', choices)
            if answer == 'open': break
            if answer == 'cancel': raise Cancelled()
            if answer not in map(str, range(len(apps))): raise SetupError('Choose an app from the review menu.')
            index = int(answer)
            if index in launchers: launchers[index] = self.choose_launcher(apps[index], catalog)
            else:
                candidates = [w for a, w in eligible.items() if a not in chosen or a == chosen[index]]
                chosen[index] = self.choose_window('Choose a different app', candidates, workspace)
                if chosen[index] not in {w['address'] for w in candidates}: raise Cancelled()
        selected = deepcopy({a: windows[a] for a in chosen if a})
        # Selecting Open here already requests this saved tiled arrangement.
        # Explicit review keeps the existing tiling offer for manual choices.
        if review: self.confirm_tiling(selected, 'Tile and open card')
        return SavedPlan('repair' if edit else 'open', name, recipe, windows=selected, workspace=workspace, focus=focus,
                         launchers=launchers, chosen=chosen, edit=edit)

    def check_plan(self, plan, focus=True):
        if self.store.read().get(plan.name) != plan.recipe:
            raise SetupError('That saved card changed. Open Saved cards again.')
        if focus and (self.ipc.data('-j', 'activeworkspace')['id'] != plan.workspace or
                      self.ipc.data('-j', 'activewindow').get('address') not in (None, plan.focus)):
            raise SetupError('Focus changed. Open Saved cards again on the workspace you want.')

    def apply_open(self, plan, timeout=20):
        request = getattr(self.menu, 'request', None)
        exclusive = request.exclusive if request else nullcontext
        check = request.check if request else lambda: None
        apps = [app for face in plan.recipe['faces'] for app in face['apps']]
        chosen, selected = list(plan.chosen), deepcopy(plan.windows)
        with exclusive():
            check(); self.check_plan(plan); self.check_workspace(plan.recipe, plan.workspace)
            windows, state = self.ipc.windows(), self.ipc.status()
            if plan.action == 'repair': windows, state = self.validate_repair(plan)
            eligible = self.eligible(windows, state)
            for address, original in selected.items():
                if plan.edit and address in plan.edit.windows: continue
                if address not in eligible or any(windows[address][k] != original[k] for k in ('pid', 'class', 'workspace', 'floating')):
                    raise SetupError('A selected app changed. Open Saved cards again.')
            for index in plan.launchers:
                if any(self.same_app(apps[index], w) for a, w in windows.items() if a not in chosen):
                    raise SetupError(apps[index]['label'] + ' just opened. Open Saved cards again to reuse it.')
        baseline = set(windows)
        catalog = DesktopApps(getattr(self.ipc, 'env', None))
        progress = Opening(plan.name, [apps[i]['label'] for i in plan.launchers], getattr(self.ipc, 'env', None))
        # A workspace lease stops Chill from floating existing panes while apps
        # start. No layout mutation happens until every app has been identified.
        with self.reserve(selected, state, plan.workspace):
            with progress if plan.launchers else nullcontext():
                processes = {}
                with exclusive():
                    check(); self.check_plan(plan)
                    for index, entry in plan.launchers.items():
                        processes[index] = catalog.launch(entry)
                deadline = time.monotonic() + timeout
                while True:
                    check()
                    if plan.launchers: progress.check()
                    if plan.action == 'repair': self.validate_repair(plan)
                    # Observe focus before clients: an app can map and focus
                    # between IPC replies. The later client list can identify
                    # it instead of mistaking our own launch for navigation.
                    active_window = self.ipc.data('-j', 'activewindow')
                    active = active_window.get('address')
                    workspace = self.ipc.data('-j', 'activeworkspace')['id']
                    windows, state = self.ipc.windows(), self.ipc.status()
                    eligible = self.eligible(windows, state)
                    for index, entry in plan.launchers.items():
                        if chosen[index]: continue
                        keys = {entry.wm_class, entry.id[:-8]} - {''}
                        candidates = [w for a, w in eligible.items() if a not in baseline and a not in chosen and
                            (self.same_app(apps[index], w) or w.get('class') in keys or w.get('initialClass') in keys)]
                        exact = [w for w in candidates if clean(w.get('title', ''), 512) == apps[index]['title']]
                        # Two windows from the same app may start in either
                        # order. A lone early window is not proof of its slot.
                        classes = {apps[index]['class'], apps[index]['initial_class']} - {''}
                        ambiguous_slots = any(i != index and not chosen[i] and
                            (classes & {apps[i]['class'], apps[i]['initial_class']} or entry.id == other.id)
                            for i, other in plan.launchers.items())
                        match = exact[0]['address'] if len(exact) == 1 else None
                        if match is None and len(candidates) == 1 and not ambiguous_slots:
                            match = candidates[0]['address']
                        if match:
                            chosen[index] = match
                            selected[match] = deepcopy(windows[match])
                        elif processes[index].poll() not in (None, 0):
                            raise SetupError('Could not launch ' + apps[index]['label'] + '. Open it yourself, then try the saved card again.')
                    allowed_focus = active in (None, plan.focus, *chosen)
                    # A new app may focus before its startup class is ready.
                    # Wait for identification, but never group that window or
                    # take focus from it unless it uniquely matches a slot.
                    if not allowed_focus and (not plan.launchers or active in baseline):
                        raise Cancelled()
                    focused = windows.get(active, active_window)
                    if workspace != plan.workspace and focused.get('workspace', {}).get('id') != workspace:
                        raise Cancelled()  # Includes navigating to an empty workspace.
                    if all(chosen):
                        if not allowed_focus: raise Cancelled()
                        break
                    if time.monotonic() >= deadline:
                        missing = ', '.join(app['label'] for app, address in zip(apps, chosen) if not address)
                        next_step = ('Open the card menu again to reuse them.' if plan.action == 'repair' else
                                     'Choose Restore from open apps to select them yourself.')
                        raise SetupError('Still waiting for ' + missing + '. Apps were left open. ' + next_step)
                    time.sleep(.12)
            with exclusive():
                check(); self.check_plan(plan, focus=False)
                active = self.ipc.data('-j', 'activewindow').get('address')
                workspace = self.ipc.data('-j', 'activeworkspace')['id']
                allowed = (None, plan.focus, *chosen) if plan.launchers else (None, plan.focus)
                if (active not in allowed or (workspace != plan.workspace and
                        (active not in selected or selected[active]['workspace']['id'] != workspace))):
                    raise Cancelled()
                # Original windows retain their snapshots so a move/close/group
                # while launching still fails the normal restore validation.
                selected, arrangement = self.arrange(plan.recipe, chosen, selected)
                if self.ipc.data('-j', 'activeworkspace')['id'] != plan.workspace:
                    self.ipc.call('dispatch', f'hl.dsp.focus({{workspace={plan.workspace}}})')
                with self.reserve(selected, self.ipc.status(), plan.workspace):
                    try:
                        if plan.action == 'repair': self.repair_reserved(plan, selected, arrangement)
                        else: self.apply_reserved(selected, arrangement, plan.workspace)
                    except Exception:
                        original_focus = self.ipc.windows().get(plan.focus)
                        if original_focus and self.ipc.data('-j', 'activewindow').get('address') != plan.focus:
                            self.restore_focus(original_focus)
                        raise
                remembered = deepcopy(plan.recipe)
                saved_apps = [app for face in remembered['faces'] for app in face['apps']]
                for index, entry in plan.launchers.items():
                    w = selected[chosen[index]]
                    saved_apps[index].update(desktop_id=entry.id, **{'class': w.get('class', '')[:512],
                        'initial_class': w.get('initialClass', '')[:512], 'title': clean(w.get('title', ''), 512),
                        'label': app_name(w)})
                if remembered != plan.recipe:
                    try: self.store.update(plan.name, remembered, plan.recipe)
                    except (SetupError, OSError):
                        return ('Reopened missing apps' if plan.action == 'repair' else 'Opened') + f' for “{plan.name}”. Launcher choices could not be saved; save the card again to remember them.'
        return f'Reopened missing apps in “{plan.name}”.' if plan.action == 'repair' else f'Opened “{plan.name}”.'

    def apply(self, plan):
        if plan.action in ('save', 'update'):
            windows, _ = Edit(self.ipc, self.menu).validate(plan.edit)
            # A resize while naming the card must not save stale proportions.
            recipe = self.capture(plan.edit.card, windows)
            catalog = DesktopApps(getattr(self.ipc, 'env', None))
            old_apps = [app for face in (plan.previous or {}).get('faces', []) for app in face['apps']]
            for face in recipe['faces']:
                for app in face['apps']:
                    previous = [old for old in old_apps if self.same_app(old,
                                {'class': app['class'], 'initialClass': app['initial_class']})]
                    exact = [old for old in previous if old['title'] == app['title']]
                    identifiers = {old.get('desktop_id') for old in (exact or previous)} - {None}
                    if len(identifiers) == 1: app['desktop_id'] = identifiers.pop()
                    elif entry := catalog.infer(app): app['desktop_id'] = entry.id
            self.store.update(plan.name, recipe, plan.previous)
            if plan.action == 'update': return f'Updated “{plan.name}”.'
            return f'Saved “{plan.name}”. Open it from the card menu whenever you need it.'
        if plan.action in ('rename', 'duplicate'):
            replacements = {plan.new_name: plan.recipe}
            if plan.action == 'rename': replacements[plan.name] = None
            self.store.change({plan.name: plan.recipe, plan.new_name: None}, replacements)
            return (f'Renamed to “{plan.new_name}”.' if plan.action == 'rename' else f'Saved a copy as “{plan.new_name}”.')
        if plan.action == 'delete':
            self.store.update(plan.name, None, plan.previous)
            return f'Deleted saved card “{plan.name}”.'
        if plan.action in ('open', 'repair'): return self.apply_open(plan)
        if plan.action == 'goto':
            self.check_plan(plan)
            windows, state = self.ipc.windows(), self.ipc.status()
            card = next((c for c in self.open_cards(plan.recipe, windows, state) if c['id'] == plan.card['id']), None)
            if not card or card['faces'] != plan.card['faces'] or any(
                    a not in windows or windows[a]['pid'] != w['pid'] for a, w in plan.windows.items()):
                raise SetupError('That open card changed. Open Saved cards again.')
            self.ipc.focus(card['current'])
            return
        if plan.action != 'restore': raise SetupError('Choose a saved card action first.')
        self.check_plan(plan)
        original_focus = self.ipc.windows().get(plan.focus)
        with self.reserve(plan.windows, self.ipc.status(), plan.workspace):
            try:
                self.apply_reserved(plan.windows, plan.arrangement, plan.workspace)
            except Exception:
                if original_focus: self.restore_focus(original_focus)
                raise
        return f'Restored “{plan.name}”.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--front', help='Create a card from this window address')
    mode.add_argument('--edit', help='Edit the side containing this window address')
    mode.add_argument('--cards', action='store_true', help='Open the card menu, including saved cards on an empty workspace')
    mode.add_argument('--launch', action='store_true', help='Search saved cards and open or switch to one directly')
    args = parser.parse_args()
    request = None
    try:
        ipc = Hyprctl()
        front = args.front or args.edit or ipc.data('-j', 'activewindow').get('address')
        runtime = Path(os.environ['XDG_RUNTIME_DIR'])
        request = Request(runtime, os.environ['HYPRLAND_INSTANCE_SIGNATURE'])
        request.start()
        with tempfile.TemporaryDirectory(prefix='hyprflip-setup-', dir=runtime) as directory:
            menu = OmarchyMenu(Path(directory), request)
            if args.launch:
                flow = Saved(ipc, menu)
                selected = flow.prepare_restore()
            elif args.cards and not any(front in f for c in ipc.status().get('containers', []) for f in c['faces']):
                choices = [Choice('saved', 'Open saved card…', 'Reuse open apps · Launch missing apps')]
                if front: choices.insert(0, Choice('create', 'Create a card', 'Choose another app for the back'))
                action = menu.choose('Hyprflip cards', choices)
                flow = Saved(ipc, menu) if action == 'saved' else Setup(ipc, menu)
                selected = flow.prepare_restore() if action == 'saved' else flow.prepare(front)
            else:
                flow = (Edit if args.edit or args.cards else Setup)(ipc, menu)
                selected = flow.prepare(args.edit or front)
            # Launch waits must not hold the request lock: opening C again can
            # supersede them. apply_open locks only launch and commit sections.
            opening = isinstance(selected, SavedPlan) and selected.action in ('open', 'repair')
            with nullcontext() if opening else request.exclusive():
                request.check()
                message = flow.apply(selected)
                if message:
                    subprocess.run(['notify-send', '--app-name=Hyprflip', 'Hyprflip', message], check=False)
        return 0
    except Cancelled:
        return 0
    except (SetupError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        message = str(error)
        subprocess.run(['notify-send', '--app-name=Hyprflip', 'Hyprflip', message], check=False)
        print(message)
        return 1
    finally:
        if request:
            request.finish()


if __name__ == '__main__':
    raise SystemExit(main())
