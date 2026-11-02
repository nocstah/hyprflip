#!/usr/bin/env python3
"""Versioned, local JSON interface shared by OmaCards and Hyprflip's menus.

snapshot emits one JSON object. run accepts --request JSON and emits JSON lines.
Questions require {"reply": id, "value": choice}; focus handoffs require
{"resume": id}. {"cancel": true} cancels the operation, including launch waits.
unattended takes one --request JSON, asks nothing and prints one JSON line; a
SIGTERM cancels it until its batch goes out.
No user-controlled string is evaluated as a command.
"""
import argparse
from collections import deque
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
import json
import os
import re
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

import workflow as w
import shortcuts

PROTOCOL = 1
MAX_MESSAGE = 65536
# Shared with unattended stores, so OmaCards' tokens stay the same.
digest = w.digest


def identity(window):
    return {key: window.get(key) for key in
            ('address', 'pid', 'class', 'initialClass', 'workspace', 'floating',
             'mapped', 'grouped', 'fullscreen', 'hidden')}


def card_members(card, kind):
    return card['faces'] if kind == 'container' else [[card['front']], [card['back']]]


def card_token(card, kind, windows, instance):
    return digest({'instance': instance, 'kind': kind, 'card': card,
                   'windows': [identity(windows.get(a, {})) for f in card_members(card, kind) for a in f]})


def context(ipc, windows=None):
    windows = ipc.windows() if windows is None else windows
    anchor = ipc.data('-j', 'activewindow').get('address')
    return {'instance': (ipc.env or os.environ).get('HYPRLAND_INSTANCE_SIGNATURE', ''),
            'workspace': ipc.data('-j', 'activeworkspace').get('id'),
            'anchor': anchor if anchor in windows else None,
            'anchor_label': w.app_name(windows[anchor]) if anchor in windows else None,
            'anchor_token': digest(identity(windows[anchor])) if anchor in windows else None}


def validate_context(ipc, expected):
    if not isinstance(expected, dict):
        raise w.SetupError('Open Cards again to choose a target.')
    actual = context(ipc)
    if not actual['instance'] or expected.get('instance') != actual['instance']:
        raise w.SetupError('Hyprland restarted. Open Cards again.')
    if actual['workspace'] != expected.get('workspace'):
        raise w.SetupError('The workspace changed. Open Cards on the workspace you want.')
    anchor = expected.get('anchor')
    if anchor:
        window = ipc.windows().get(anchor)
        if not window or digest(identity(window)) != expected.get('anchor_token'):
            raise w.SetupError('The original app closed or moved. Open Cards again.')
    # A layer-shell popup can temporarily clear the active app, but it must
    # not let a stale panel take control after the user focuses another app.
    if actual['anchor'] not in (None, anchor):
        raise w.SetupError('Focus changed. Open Cards for the app you want.')


def snapshot(ipc):
    base = {'protocol': PROTOCOL, 'available': False, 'cards': [], 'saved': [],
            'error': '', 'library_error': '', 'context': None, 'capabilities': {}}
    # The source commit bootstrap.py installed, if any; panels compare it with their pin.
    env = ipc.env if ipc.env is not None else os.environ
    recorded = Path(env.get('XDG_STATE_HOME', str(Path(env.get('HOME', str(Path.home()))) / '.local/state'))) / 'hyprflip/installed-commit'
    try:
        commit = recorded.read_text().strip()
        base['installed_commit'] = commit if re.fullmatch(r'[0-9a-f]{40}', commit) else None
    except OSError:
        base['installed_commit'] = None
    try:
        windows, state = ipc.windows(), ipc.status()
        ctx = context(ipc, windows)
        store = w.RecipeStore(ipc.env)
        try:
            recipes = store.read()
        except (w.SetupError, OSError) as error:
            recipes = {}
            base['library_error'] = str(error)
        matches = {name: w.Saved.open_cards(recipe, windows, state) for name, recipe in recipes.items()}
        catalog = w.DesktopApps(ipc.env)
        def icon(window):
            app = catalog.infer({'class': window.get('class', ''), 'initial_class': window.get('initialClass', ''),
                                 'label': w.app_name(window)})
            return app.icon if app else ''
        cards = []
        for kind, raw_cards in (('container', state.get('containers', [])), ('pair', state.get('pairs', []))):
            for card in raw_cards:
                faces = card_members(card, kind)
                if any(a not in windows for f in faces for a in f):
                    continue
                current = card['current']
                active = card.get('active', int(current == card.get('back')))
                names = sorted([name for name, opened in matches.items()
                                if kind == 'container' and any(c['id'] == card['id'] for c in opened)], key=str.casefold)
                face_rows = []
                for index, face in enumerate(faces):
                    layout = card.get('layouts', [{}, {}])[index]
                    face_rows.append({'index': index, 'axis': layout.get('axis', 'horizontal'),
                                      'panes': [{'address': a, 'label': w.app_name(windows[a]),
                                                 'title': w.clean(windows[a].get('title', '')), 'icon': icon(windows[a])} for a in face]})
                cards.append({'id': card['id'], 'kind': kind, 'key': f"{kind}:{card['id']}",
                              'token': card_token(card, kind, windows, ctx['instance']), 'faces': face_rows,
                              'current': current, 'active': active, 'unfolded': bool(card.get('unfolded')),
                              'fullscreen': bool(card.get('fullscreen')),
                              # Native dwindle/floating cards; only these fullscreen as a whole.
                              'native': kind == 'container' and bool(card.get('native_group')),
                              'floating': bool(card.get('floating', windows[current].get('floating'))),
                              'workspace': windows[current]['workspace']['id'],
                              'workspace_label': w.workspace_name(windows[current]), 'saved_names': names,
                              'name': names[0] if names else ' ↔ '.join(' + '.join(p['label'] for p in f['panes']) for f in face_rows)})
        saved = []
        for name in sorted(recipes, key=str.casefold):
            recipe, opened = recipes[name], matches[name]
            if opened:
                detail = 'Go to · Workspace ' + ', '.join(sorted({w.workspace_name(windows[c['current']]) for c in opened}))
            else:
                existing = w.Saved.free_apps(recipe, windows, state)
                remote = sorted({w.workspace_name(win) for win in existing if win['workspace']['id'] != ctx['workspace']})
                detail = 'Open here'
                if remote: detail += ' · Bring apps from ' + ', '.join(remote)
                if any(win.get('floating') for win in existing): detail += ' · Resize apps to fit'
            saved.append({'name': name, 'token': digest(recipe), 'open': bool(opened),
                          'workspace': recipe.get('workspace'),
                          'detail': ('Open on workspace ' + str(recipe['workspace'])) if recipe.get('workspace') else detail,
                          'description': w.Saved.describe(recipe)})
        try:
            duration = ipc.data('-j', 'getoption', 'plugin:hyprflip:duration_ms')['int']
        except (w.SetupError, KeyError):
            duration = None
        try:
            def enabled(option):
                value = ipc.data('-j', 'getoption', option)
                return value['bool'] if 'bool' in value else bool(value['int'])
            motion_enabled = enabled('animations:enabled') and enabled('plugin:hyprflip:enabled')
        except (w.SetupError, KeyError):
            motion_enabled = None
        base.update(available=True, cards=cards, saved=saved, context=ctx,
                    transition=state.get('transition', 'flip'), duration_ms=duration, motion_enabled=motion_enabled,
                    transition_modes=[{'value': mode, 'label': w.TRANSITIONS[mode][0],
                                       'detail': w.TRANSITIONS[mode][1]} for mode in state.get('transition_modes', []) if mode in w.TRANSITIONS],
                    animating=bool(state.get('animating')), capabilities={
                        'containers': bool(state.get('container_provider')),
                        'max_panes': state.get('container_max_panes', 1),
                        'layout': bool(state.get('layout_controls')),
                        'replace': bool(state.get('pane_replacement')),
                        'repair': bool(state.get('repair_cards')),
                        'peek': bool(state.get('peek_available'))})
        base['capabilities']['floating'] = bool(state.get('floating_cards'))
        base['capabilities']['appearance'] = type(state.get('card_frame')) is bool
        base['appearance'] = ('frame' if state['card_frame'] else 'classic') if base['capabilities']['appearance'] else None
        base['capabilities']['drag_to_add'] = bool(state.get('drag_to_add'))
        base['capabilities']['spacing'] = type(state.get('card_gap')) is int
        base['card_gap'] = state.get('card_gap')
        base['capabilities']['accent'] = type(state.get('accent_ring')) is bool
        base['accent_ring'] = state.get('accent_ring')
        base['accent_color'] = state.get('accent_color')
        # Only cores with whole-card fullscreen report its divider.
        base['capabilities']['divider'] = type(state.get('fullscreen_divider')) is int
        base['capabilities']['fullscreen'] = base['capabilities']['divider']
        base['fullscreen_divider'] = state.get('fullscreen_divider')
        base['divider_color'] = state.get('divider_color')
        try:
            base['shortcuts'] = shortcuts.snapshot(ipc)
        except (w.SetupError, OSError, KeyError, subprocess.TimeoutExpired):
            base['shortcuts'] = {'available': False, 'rows': [], 'occupied': []}
    except (w.SetupError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        base['error'] = str(error)
    return base


class Channel:
    """Bounded JSON-lines exchange; cancel messages are checked during waits."""
    def __init__(self, source=None, output=None):
        self.source, self.output = source or sys.stdin, output or sys.stdout
        self.buffer, self.messages, self.cancelled, self.serial = b'', deque(), False, 0
        self.request = None

    def send(self, kind, **payload):
        self.output.write(json.dumps({'type': kind, **payload}, ensure_ascii=False, allow_nan=False) + '\n')
        self.output.flush()

    def pump(self, timeout=0):
        if self.cancelled:
            raise w.Cancelled()
        if not select.select([self.source], [], [], timeout)[0]:
            return
        data = os.read(self.source.fileno(), 4096)
        if not data:
            raise w.Cancelled()
        self.buffer += data
        if len(self.buffer) > MAX_MESSAGE:
            raise w.SetupError('The panel response was too large. Open Cards again.')
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError) as error:
                raise w.SetupError('The panel sent an invalid response. Open Cards again.') from error
            if not isinstance(value, dict):
                raise w.SetupError('The panel sent an invalid response. Open Cards again.')
            if value.get('cancel') is True:
                self.cancelled = True
                raise w.Cancelled()
            if len(self.messages) >= 8:
                raise w.SetupError('Too many panel responses. Open Cards again.')
            self.messages.append(value)

    def wait(self, field, serial):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.request: self.request.check()
            if self.messages:
                value = self.messages.popleft()
                if type(value.get(field)) is not int or value[field] != serial:
                    raise w.SetupError('That panel choice expired. Open Cards again.')
                return value.get('value')
            self.pump(.1)
        raise w.SetupError('Card selection expired. Open Cards again.')

    def handoff(self):
        self.serial += 1
        self.send('handoff', id=self.serial)
        self.wait('resume', self.serial)


class PanelRequest(w.Request):
    def __init__(self, runtime, instance, channel):
        super().__init__(runtime, instance)
        self.channel = channel

    def check(self):
        super().check()
        self.channel.pump()


class PanelOpening:
    def __init__(self, menu, name, labels):
        self.menu, self.name, self.labels = menu, name, labels

    def __enter__(self):
        self.menu.channel.send('opening', name=self.name, labels=self.labels)
        return self

    def update(self, labels):
        if labels != self.labels:
            self.labels = labels
            self.menu.channel.send('opening', name=self.name, labels=labels)

    def check(self): self.menu.request.check()
    def __exit__(self, *_): pass


class PanelMenu:
    def __init__(self, channel, request, prefix=()):
        self.channel, self.request, self.prefix = channel, request, deque(prefix)

    def choose(self, prompt, choices):
        self.request.check()
        allowed = {c.value for c in choices}
        prompted = not self.prefix
        if self.prefix:
            result = self.prefix.popleft()
        else:
            self.channel.serial += 1
            self.channel.send('question', id=self.channel.serial, mode='select', prompt=prompt,
                              choices=[asdict(c) for c in choices])
            result = self.channel.wait('reply', self.channel.serial)
        if not isinstance(result, str) or result not in allowed:
            raise w.SetupError('That action is no longer available. Open Cards again.')
        if prompted:
            self.channel.handoff()
        return result

    def input(self, prompt):
        self.request.check()
        self.channel.serial += 1
        self.channel.send('question', id=self.channel.serial, mode='input', prompt=prompt, choices=[])
        value = self.channel.wait('reply', self.channel.serial)
        if not isinstance(value, str) or len(value) > 512:
            raise w.SetupError('Enter a short card name.')
        self.channel.handoff()
        return value

    def opening(self, name, labels): return PanelOpening(self, name, labels)


def resolve_card(ipc, target, ctx):
    if not isinstance(target, dict) or target.get('kind') not in ('pair', 'container') or type(target.get('id')) is not int:
        raise w.SetupError('Choose a card first.')
    windows, state = ipc.windows(), ipc.status()
    kind = target['kind']
    card = next((c for c in state.get('containers' if kind == 'container' else 'pairs', []) if c['id'] == target['id']), None)
    if not card or card_token(card, kind, windows, ctx['instance']) != target.get('token'):
        raise w.SetupError('The card changed. Refresh Cards before editing it.')
    return card, windows, state


def edit_prefix(intent, pane, face, card, state):
    """Route stable choice IDs, never display text, through the existing editor."""
    members = card['faces'][face]
    if pane is not None and pane not in members:
        raise w.SetupError('That app is no longer on this side.')
    if intent in ('repair', 'unpair') and card.get('fullscreen'):
        raise w.SetupError('Leave card fullscreen, then try again.')
    if intent in ('save', 'manage', 'repair', 'unpair', 'add'):
        return [intent]
    if intent == 'remove' and pane:
        if len(members) == 1:
            raise w.SetupError('This is the only app on its side. Choose Ungroup card to keep all apps open.')
        return ['release:' + pane]
    if intent == 'replace' and pane:
        return ['replace'] + ([pane] if len(members) > 1 else [])
    if intent == 'other_side' and pane:
        return ['other_side', pane]
    if intent in ('horizontal', 'vertical', 'balance'):
        return ['layout', 'layout ' + intent]
    if intent in ('previous', 'next') and pane:
        index = members.index(pane)
        destination = index + (-1 if intent == 'previous' else 1)
        if not 0 <= destination < len(members):
            raise w.SetupError('That app is already at the edge of this side.')
        return ['layout', 'reorder'] + ([f'{index}:{destination}'] if len(members) > 2 else [])
    if intent in (None, ''):
        return []
    raise w.SetupError('Choose an available card action.')


def run_operation(ipc, payload, menu):
    if not isinstance(payload, dict) or type(payload.get('protocol')) is not int or payload['protocol'] != PROTOCOL:
        raise w.SetupError('OmaCards and the Hyprflip helper need matching protocol versions.')
    action, ctx = payload.get('action'), payload.get('context')
    if action not in ('flip', 'unfold', 'floating', 'edit', 'create', 'open', 'manage', 'transition', 'preview', 'duration', 'shortcut', 'appearance', 'spacing', 'accent', 'divider', 'fullscreen'):
        raise w.SetupError('Choose an available card action.')
    validate_context(ipc, ctx)
    request = menu.request
    card = None
    if action in ('flip', 'unfold', 'floating', 'fullscreen', 'edit', 'preview'):
        card, windows, state = resolve_card(ipc, payload.get('target'), ctx)
        if windows[card['current']]['workspace']['id'] != ctx['workspace']:
            raise w.SetupError('Go to this card’s workspace before editing it.')
        if state.get('animating'):
            raise w.SetupError('Wait for the turn to finish, then try again.')
        if action in ('unfold', 'edit', 'fullscreen') and payload['target']['kind'] != 'container':
            raise w.SetupError('Create a multi-app card with O to use these controls.')
        if action == 'fullscreen':
            if type(state.get('fullscreen_divider')) is not int:
                raise w.SetupError('Update Hyprflip to fullscreen whole cards.')
            if not card.get('native_group'):
                raise w.SetupError('Whole-card fullscreen works on dwindle and floating cards.')
        if action == 'preview' and (payload.get('mode') not in w.TRANSITIONS or
                                   payload['mode'] not in state.get('transition_modes', [])):
            raise w.SetupError('Choose an available transition.')
        if action == 'edit':
            face = payload.get('face', card['active'])
            if type(face) is not int or face not in (0, 1):
                raise w.SetupError('Choose Front or Back.')
            menu.prefix.extend(edit_prefix(payload.get('intent'), payload.get('pane'), face, card, state))

    menu.channel.handoff()
    validate_context(ipc, ctx)
    if card:
        card, windows, state = resolve_card(ipc, payload['target'], ctx)
    if action in ('flip', 'unfold', 'floating', 'fullscreen', 'preview', 'edit', 'create'):
        anchor = card['current'] if card else ctx.get('anchor')
        if action == 'edit':
            anchor = (card['current'] if card['current'] in card['faces'][face] else card['faces'][face][0])
            if face != card['active'] and not card.get('unfolded'):
                # Hyprland cannot focus a hidden provider pane directly. The
                # UI explicitly calls this "Show and edit Front/Back".
                with request.exclusive():
                    request.check()
                    ipc.focused((card['current'], 'flip'))
                deadline = time.monotonic() + 8
                while True:
                    request.check()
                    latest = ipc.status()
                    shown = next((c for c in latest.get('containers', []) if c['id'] == card['id']), None)
                    if not shown or shown['faces'] != card['faces']:
                        raise w.SetupError('The card changed while turning. Open Cards again.')
                    if not latest.get('animating'):
                        if shown['active'] != face:
                            raise w.SetupError('The other side could not be shown. Open Cards again.')
                        break
                    if time.monotonic() > deadline:
                        raise w.SetupError('The turn has not finished. Return to the card.')
                    time.sleep(.04)
        if not anchor:
            raise w.SetupError('Focus the app you want on the front, then choose Create card.')
        ipc.focus(anchor)

    if action in ('flip', 'unfold', 'floating', 'fullscreen', 'preview'):
        command = action
        if action == 'preview':
            mode = payload.get('mode')
            if mode not in w.TRANSITIONS or mode not in state.get('transition_modes', []):
                raise w.SetupError('Choose an available transition.')
            command = 'preview ' + mode
        with request.exclusive():
            request.check()
            ipc.focused((anchor, command))
        if action == 'preview':
            deadline = time.monotonic() + 8
            while ipc.status().get('animating'):
                request.check()
                if time.monotonic() > deadline:
                    raise w.SetupError('The preview has not finished. Return to the card.')
                time.sleep(.04)
            kind = payload['target']['kind']
            finished = next((c for c in ipc.status().get('containers' if kind == 'container' else 'pairs', [])
                             if c['id'] == card['id']), None)
            if not finished or card_members(finished, kind) != card_members(card, kind) or finished['current'] != card['current']:
                raise w.SetupError('The preview was interrupted. Return to the card and try again.')
        return ''

    if action in ('transition', 'duration'):
        with request.exclusive():
            request.check()
            if action == 'transition':
                mode = payload.get('mode')
                if mode not in w.TRANSITIONS or mode not in ipc.status().get('transition_modes', []):
                    raise w.SetupError('Choose an available transition.')
                ipc.save_transition(mode)
            else:
                ipc.save_duration(payload.get('duration_ms'))
        return 'Motion updated for all cards.'

    if action == 'shortcut':
        with request.exclusive():
            request.check()
            return shortcuts.save(ipc, payload.get('binding'), payload.get('mask'), payload.get('key'))

    if action == 'appearance':
        with request.exclusive():
            request.check()
            ipc.save_appearance(payload.get('style'))
        return 'Card appearance updated for all cards.'

    if action == 'spacing':
        with request.exclusive():
            request.check()
            ipc.save_spacing(payload.get('gap'))
        return 'App spacing updated for all cards.'

    if action == 'accent':
        enabled = payload.get('enabled')
        with request.exclusive():
            request.check()
            if enabled and payload.get('color') is not None:
                ipc.save_accent_color(payload['color'])
            ipc.save_accent_ring(enabled)
        return 'Accent ring on for all cards.' if enabled else 'Accent ring off.'

    if action == 'divider':
        width = payload.get('width')
        if type(width) is not int or not 0 <= width <= 16:
            raise w.SetupError('Choose a divider between 0 and 16 pixels.')
        with request.exclusive():
            request.check()
            if payload.get('color') is not None:
                ipc.save_divider_color(payload['color'])
            ipc.save_fullscreen_divider(width)
        return 'Fullscreen divider off.' if width == 0 else 'Fullscreen divider updated for all cards.'

    if action == 'create':
        flow = w.Setup(ipc, menu)
        plan = flow.prepare(anchor)
    elif action == 'edit':
        flow = w.Edit(ipc, menu)
        plan = flow.prepare(anchor)
    else:
        flow = w.Saved(ipc, menu)
        name = payload.get('name')
        recipes = flow.store.read()
        if not isinstance(name, str) or name not in recipes or digest(recipes[name]) != payload.get('recipe_token'):
            raise w.SetupError('That saved card changed. Refresh the library.')
        if action == 'open':
            plan = flow.prepare_named(name, recipes[name], ctx['workspace'], ctx.get('anchor'))
        else:
            # The helper owns ordering and validates this stable selection.
            menu.prefix.append(str(sorted(recipes, key=str.casefold).index(name)))
            plan = flow.prepare_manage()
            if plan is None: raise w.Cancelled()
    if menu.prefix:
        raise w.SetupError('The card editor changed. Update OmaCards and the Hyprflip helper together.')
    menu.channel.handoff()
    opening = isinstance(plan, w.SavedPlan) and plan.action in ('open', 'repair')
    with nullcontext() if opening else request.exclusive():
        request.check()
        return flow.apply(plan) or ''


# A signal only sets this while an unattended action runs. The action looks
# at it where stopping still leaves every app where it was.
interrupted = False


def interrupt(*_):
    global interrupted
    interrupted = True


ADDRESS = re.compile(r'0x[0-9a-fA-F]{1,16}')
# The fields each unattended action takes besides protocol and action, and those it needs.
FIELDS = {'capabilities': set(), 'list': {'store', 'name'}, 'delete': {'store', 'name', 'token', 'lock_ms'},
          'open': {'store', 'name', 'recipe', 'workspace', 'bind', 'owned', 'focus', 'launch', 'timeout_ms', 'lock_ms'},
          'save': {'store', 'name', 'card', 'members', 'previous', 'base', 'keep', 'floating', 'owned', 'lock_ms'}}
REQUIRED = {'capabilities': set(), 'list': {'store'}, 'delete': {'store', 'name', 'token'},
            'open': {'workspace'}, 'save': {'store', 'name', 'card', 'members', 'previous'}}


def unattended_request(payload, env):
    """The request, checked before anything asks Hyprland or reads a store.

    Raises Unfinished with the code that says what is wrong.
    """
    def number(value, low, high): return type(value) is int and low <= value <= high
    def addresses(value, low):
        return (isinstance(value, list) and low <= len(value) <= 10 and len(set(map(str, value))) == len(value) and
                all(isinstance(a, str) and ADDRESS.fullmatch(a) for a in value))
    def untitled(recipe):
        # A definition that travels in a request never carries a title.
        try:
            w.RecipeStore.validate(recipe)
        except (ValueError, KeyError, TypeError, AttributeError):
            return False
        return all(app['title'] == '' for face in recipe['faces'] for app in face['apps'])

    if not isinstance(payload, dict) or type(payload.get('protocol')) is not int or payload['protocol'] != PROTOCOL:
        raise w.Unfinished('invalid_request')
    action = payload.get('action')
    if (not isinstance(action, str) or action not in FIELDS or set(payload) - FIELDS[action] - {'protocol', 'action'} or
            REQUIRED[action] - set(payload)):
        raise w.Unfinished('invalid_request')
    get = payload.get
    if 'name' in payload and not w.RecipeStore.valid_name(payload['name']): raise w.Unfinished('invalid_name')
    if 'lock_ms' in payload and not number(payload['lock_ms'], 0, 30000): raise w.Unfinished('invalid_request')
    if 'owned' in payload and not (isinstance(payload['owned'], list) and len(payload['owned']) <= 8 and
                                   all(isinstance(c, str) and 0 < len(c) <= 512 for c in payload['owned'])):
        raise w.Unfinished('invalid_request')
    if action == 'delete' and not (isinstance(payload['token'], str) and re.fullmatch(r'[0-9a-f]{64}', payload['token'])):
        raise w.Unfinished('invalid_request')
    if action == 'open':
        # A stored definition by name, from the caller's store, or one in the request.
        if ('name' in payload) == ('recipe' in payload) or 'name' in payload and 'store' not in payload:
            raise w.Unfinished('invalid_request')
        if 'recipe' in payload and not untitled(payload['recipe']): raise w.Unfinished('invalid_request')
        if not number(payload['workspace'], 1, 2**31 - 1): raise w.Unfinished('unsupported_workspace')
        if ('bind' in payload and not addresses(payload['bind'], 0) or
                get('focus') is not None and not (isinstance(payload['focus'], str) and ADDRESS.fullmatch(payload['focus'])) or
                type(get('launch', True)) is not bool or 'timeout_ms' in payload and not number(payload['timeout_ms'], 1000, 60000)):
            raise w.Unfinished('invalid_request')
    if action == 'save':
        previous, keep = payload['previous'], get('keep', [])
        if (not number(payload['card'], 1, 2**63 - 1) or not addresses(payload['members'], 1) or
                previous is not None and not (isinstance(previous, str) and re.fullmatch(r'[0-9a-f]{64}', previous)) or
                'base' in payload and (previous is not None or not untitled(payload['base'])) or
                get('floating') is not None and type(payload['floating']) is not bool):
            raise w.Unfinished('invalid_request')
        # Closed apps to keep, each by its place in the definition it replaces, which there must be.
        if (not isinstance(keep, list) or len(keep) > 10 or
                not all(isinstance(k, dict) and set(k) == {'face', 'index'} and number(k['face'], 0, 1) and
                        number(k['index'], 0, 4) for k in keep) or
                len({(k['face'], k['index']) for k in keep}) != len(keep) or keep and previous is None and 'base' not in payload):
            raise w.Unfinished('invalid_request')
    # Never the library, nor a file anyone else could write or swap.
    if 'store' in payload and not w.RecipeStore.valid_path(payload['store'], env): raise w.Unfinished('invalid_store')
    return payload


def run_unattended(raw, ipc, env):
    """Runs one unattended request and returns its reply and exit code. It never raises.

    No reply carries an exception's text or a window title: each code has a
    fixed message, and labels name apps by their labels.
    """
    def failed(code, labels=(), **details):
        return {'protocol': PROTOCOL, 'ok': False, 'code': code, 'message': w.Unfinished.MESSAGES[code],
                'labels': list(labels), 'launched': [], **details}, 1
    try:
        if not isinstance(raw, str) or len(raw.encode('utf-8', 'surrogateescape')) > MAX_MESSAGE:
            raise w.Unfinished('invalid_request')
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError) as error:
            raise w.Unfinished('invalid_request') from error
        request = unattended_request(payload, env)
        if not env.get('XDG_RUNTIME_DIR') or not env.get('HYPRLAND_INSTANCE_SIGNATURE'): raise w.Unfinished('unavailable')
        flow, action = w.Unattended(ipc, request.get('store')), request['action']
        def cancelled(): return interrupted
        if action == 'capabilities': result = flow.capabilities()
        elif action == 'list': result = flow.listing(request.get('name'))
        elif action == 'delete': result = flow.delete(request['name'], request['token'], request.get('lock_ms', 5000), cancelled)
        elif action == 'open': result = flow.open(request, cancelled)
        else: result = flow.save(request, cancelled)
        return {'protocol': PROTOCOL, 'ok': True, **result}, 0
    except w.Unfinished as stop:
        return failed(stop.code, stop.labels, **stop.details)
    except w.CoreUnavailable:
        # Hyprland answered, without a core: that is no reason to try again soon.
        return failed('unavailable')
    except (w.SetupError, OSError, subprocess.TimeoutExpired):
        return failed('hyprland')
    except Exception:
        return failed('internal')


def print_unattended(reply, code):
    """Prints the reply as one line and returns the exit code; a reader that went away gets nothing more."""
    try:
        line = json.dumps(reply, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError):
        line, code = json.dumps({'protocol': PROTOCOL, 'ok': False, 'code': 'internal',
                                 'message': w.Unfinished.MESSAGES['internal'], 'labels': [], 'launched': []}), 1
    try:
        print(line, flush=True)
    except BrokenPipeError:
        # Python would try stdout again at exit; it goes to /dev/null instead.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('snapshot', 'run', 'accent-color', 'unattended'))
    parser.add_argument('--request', default='{}')
    parser.add_argument('--color', help='accent-color: the theme accent as #RRGGBB')
    args = parser.parse_args()
    ipc = w.Hyprctl()
    if args.command == 'unattended':
        # A reader that goes away is a failed print, never a signal; SIGTERM
        # and SIGINT only ask the action to stop where it safely can.
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, interrupt)
        signal.signal(signal.SIGINT, interrupt)
        return print_unattended(*run_unattended(args.request, ipc, os.environ))
    if args.command == 'snapshot':
        print(json.dumps(snapshot(ipc), ensure_ascii=False, allow_nan=False))
        return 0
    if args.command == 'accent-color':
        # Follows the desktop theme without a panel request; unchanged colors
        # are not rewritten or dispatched.
        try:
            ipc.save_accent_color(args.color)
        except (w.SetupError, OSError, KeyError, subprocess.TimeoutExpired) as error:
            print(json.dumps({'ok': False, 'message': str(error)}))
            return 1
        print(json.dumps({'ok': True, 'message': ''}))
        return 0
    channel, request = Channel(), None
    try:
        if len(args.request.encode()) > MAX_MESSAGE:
            raise w.SetupError('The card request was too large.')
        payload = json.loads(args.request)
        request = PanelRequest(Path(os.environ['XDG_RUNTIME_DIR']), os.environ['HYPRLAND_INSTANCE_SIGNATURE'], channel)
        channel.request = request
        request.start()
        def cancel(*_):
            channel.cancelled = True
            raise w.Cancelled()
        signal.signal(signal.SIGTERM, cancel)
        signal.signal(signal.SIGINT, cancel)
        message = run_operation(ipc, payload, PanelMenu(channel, request))
        channel.send('done', message=message)
        return 0
    except w.Cancelled:
        channel.send('cancelled', message='Cancelled. Opened apps stay open.')
        return 0
    except (w.SetupError, OSError, KeyError, TypeError, ValueError, subprocess.TimeoutExpired) as error:
        channel.send('error', message=str(error))
        return 1
    finally:
        if request: request.finish()


if __name__ == '__main__':
    raise SystemExit(main())
