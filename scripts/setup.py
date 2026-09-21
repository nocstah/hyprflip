#!/usr/bin/env python3
"""Create and edit Hyprflip cards using Omarchy's native menu."""
import argparse
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
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
            self.ipc.focus(front); self.ipc.action('mark')
            self.ipc.focus(back); self.ipc.action('pair')
            created = next((c for c in self.ipc.status()['containers'] if c['faces'] == [[front], [back]]), None)
            if not created:
                raise SetupError('The card could not be created. Open setup again.')
            if arrangement:
                for face in arrangement['faces']:
                    first = face['windows'][0]
                    for companion in face['windows'][1:]:
                        self.ipc.focus(companion); self.ipc.action('mark')
                        self.ipc.focus(first); self.ipc.action('attach ' + face['axis'])
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
                    self.ipc.focus(companion); self.ipc.action('mark')
                    self.ipc.focus(back); self.ipc.action('attach ' + axis)
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
                self.ipc.focus(card['current']); self.ipc.action('unpair')
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
        for _ in range(4):
            for pane, ratio in zip(panes[:-1], face['ratios'][:-1]):
                time.sleep(.08)
                windows = self.ipc.windows()
                delta = round(ratio * sum(windows[a]['size'][axis] for a in panes) - windows[pane]['size'][axis])
                if abs(delta) > 1:
                    self.ipc.focus(pane)
                    x, y = (0, delta) if axis else (delta, 0)
                    self.ipc.call('dispatch', f'hl.dsp.window.resize({{x={x},y={y},relative=true}})')
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
                self.ipc.focus(plan.anchor)
                self.ipc.action('preview ' + mode)
                deadline = time.monotonic() + 8
                while self.ipc.status().get('animating'):
                    if hasattr(self.menu, 'request'): self.menu.request.check()
                    if time.monotonic() >= deadline:
                        raise SetupError('The preview did not finish. Open Edit card again.')
                    time.sleep(.04)
                self.validate(plan)
    def validate(self, plan):
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
        if (self.ipc.data('-j', 'activeworkspace')['id'] != workspace
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
            choices += [Choice('release:' + c.value, f'Remove {c.label} from card',
                              ('Focused app · ' if c.value == anchor else '') + 'Keep open · ' + c.detail)
                       for c in window_choices([windows[anchor]] + [windows[a] for a in face if a != anchor])]
            prompt = (f'Edit card: this side is full ({limit} apps)' if len(face) >= limit
                      else f'Edit card: {len(face)} apps on this side')
        if state.get('transition_modes'):
            label = TRANSITIONS.get(state.get('transition'), ('Flip', ''))[0]
            choices.append(Choice('transition', 'Transition', label + ' · All cards'))
        choices.extend([Choice('save', 'Save card…', 'Reuse this arrangement after restarting'),
                        Choice('saved', 'Restore saved card…', 'Use apps that are already open')])
        action = self.menu.choose(prompt, choices)
        if action not in {c.value for c in choices}:
            raise SetupError('That action is no longer available. Open Edit card again.')
        removal = None
        if action.startswith('release:'):
            removal, action = action.removeprefix('release:'), 'release'
        candidate = None
        if action == 'save': return Saved(self.ipc, self.menu).prepare_save(plan)
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
        if plan.action not in ('add', 'release', 'unpair', 'transition'):
            raise SetupError('Choose an action in Edit card first.')
        if plan.action == 'transition':
            self.ipc.save_transition(plan.transition)
            return
        self.ipc.focus(plan.anchor)
        if plan.action != 'add':
            try:
                if plan.removal:
                    self.ipc.focus(plan.removal)
                self.ipc.action(plan.action)
            finally:
                if plan.removal and plan.removal != plan.anchor:
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
            self.ipc.focus(plan.candidate); self.ipc.action('mark')
            self.ipc.focus(plan.anchor)
            width, height = self.ipc.windows()[plan.anchor]['size']
            self.ipc.action('attach ' + ('horizontal' if width >= height else 'vertical'))
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
                            self.ipc.focus(marked); self.ipc.action('mark')
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
        if not self.valid_name(name): raise SetupError('Use a card name between 1 and 64 characters.')
        if recipe is not None: self.validate(recipe)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / 'cards.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cards = self.read()
            if cards.get(name) != previous:
                raise SetupError('That saved card changed in another menu. Open Saved cards again.')
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


class Saved(Setup):
    @property
    def store(self): return RecipeStore(getattr(self.ipc, 'env', None))

    @staticmethod
    def describe(recipe):
        return clean(' ↔ '.join(' + '.join(app['label'] for app in face['apps']) for face in recipe['faces']))

    @staticmethod
    def capture(card, windows):
        faces = []
        for members in card['faces']:
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
        same = [w for w in candidates if (app['class'] and w.get('class') == app['class']) or
                (app['initial_class'] and w.get('initialClass') == app['initial_class'])]
        exact = [w for w in same if clean(w.get('title', ''), 512) == app['title']]
        return exact[0]['address'] if len(exact) == 1 else (same[0]['address'] if len(same) == 1 else None)

    def prepare_restore(self):
        workspace = self.ipc.data('-j', 'activeworkspace')['id']
        focus = self.ipc.data('-j', 'activewindow').get('address')
        cards = self.store.read()
        if not cards: raise SetupError('No saved cards yet. Focus an existing card, press Super+Ctrl+Alt+C, then choose Save card.')
        while True:
            names = sorted(cards, key=str.casefold)
            selected = self.menu.choose('Saved cards', [Choice(str(i), name, self.describe(cards[name])) for i, name in enumerate(names)])
            if selected not in map(str, range(len(names))): raise SetupError('Choose a saved card from the menu.')
            name = names[int(selected)]; recipe = cards[name]
            choice = self.menu.choose(name, [Choice('restore', 'Restore on this workspace', self.describe(recipe)),
                                           Choice('delete', 'Delete saved card', 'Keep all running apps and cards'),
                                           Choice('back', 'Back to saved cards')])
            if choice == 'back': continue
            if choice == 'delete':
                if self.menu.choose(f'Delete saved card “{name}”?', [Choice('delete', 'Delete saved card'),
                                                                 Choice('cancel', 'Cancel')]) != 'delete': raise Cancelled()
                return SavedPlan('delete', name, recipe, recipe)
            if choice != 'restore': raise Cancelled()
            break
        windows, state = self.ipc.windows(), self.ipc.status()
        layouts = {w['id']: w['tiledLayout'] for w in self.ipc.data('-j', 'workspaces')}
        if not state.get('container_provider') or workspace < 1 or layouts.get(workspace) != 'hy3':
            raise SetupError('Restore a card on a normal workspace with the hy3 container layout.')
        if any(len(face['apps']) > state.get('container_max_panes', 2) for face in recipe['faces']):
            raise SetupError('Update the container plugins before restoring this card; it needs more apps per side.')
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
        arrangement = deepcopy(recipe)
        offset = 0
        for face in arrangement['faces']:
            count = len(face.pop('apps'))
            face['windows'] = chosen[offset:offset + count]; offset += count
        first, second = (face['windows'][0] for face in arrangement['faces'])
        order = [first, second] + [a for a in chosen if a not in (first, second)]
        selected = deepcopy({a: windows[a] for a in order})
        self.confirm_tiling(selected, 'Tile and restore card')
        return SavedPlan('restore', name, recipe, recipe, windows=selected, arrangement=arrangement, workspace=workspace, focus=focus)

    def apply(self, plan):
        if plan.action == 'save':
            windows, _ = Edit(self.ipc, self.menu).validate(plan.edit)
            # A resize while naming the card must not save stale proportions.
            recipe = self.capture(plan.edit.card, windows)
            self.store.update(plan.name, recipe, plan.previous)
            return f'Saved “{plan.name}”. Restore it from the card menu after reopening your apps.'
        if plan.action == 'delete':
            self.store.update(plan.name, None, plan.previous)
            return f'Deleted saved card “{plan.name}”.'
        if plan.action != 'restore': raise SetupError('Choose a saved card action first.')
        if self.store.read().get(plan.name) != plan.recipe:
            raise SetupError('That saved card changed. Open Saved cards again.')
        if (self.ipc.data('-j', 'activeworkspace')['id'] != plan.workspace or
                self.ipc.data('-j', 'activewindow').get('address') not in (None, plan.focus)):
            raise SetupError('Focus changed. Open Saved cards again on the workspace you want.')
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
            if args.cards and not any(front in f for c in ipc.status().get('containers', []) for f in c['faces']):
                choices = [Choice('saved', 'Restore saved card…', 'Use apps that are already open')]
                if front: choices.insert(0, Choice('create', 'Create a card', 'Choose another app for the back'))
                action = menu.choose('Hyprflip cards', choices)
                flow = Saved(ipc, menu) if action == 'saved' else Setup(ipc, menu)
                selected = flow.prepare_restore() if action == 'saved' else flow.prepare(front)
            else:
                flow = (Edit if args.edit or args.cards else Setup)(ipc, menu)
                selected = flow.prepare(args.edit or front)
            with request.exclusive():
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
