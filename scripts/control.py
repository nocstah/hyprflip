#!/usr/bin/env python3
"""Versioned, local JSON interface shared by OmaCards and Hyprflip's menus.

snapshot emits one JSON object. run accepts --request JSON and emits JSON lines.
Questions require {"reply": id, "value": choice}; focus handoffs require
{"resume": id}. {"cancel": true} cancels the operation, including launch waits.
No user-controlled string is evaluated as a command.
"""
import argparse
from collections import deque
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
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


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


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
                existing = [win for win in windows.values() if any(w.Saved.same_app(app, win)
                            for face in recipe['faces'] for app in face['apps'])]
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
    if action not in ('flip', 'unfold', 'floating', 'edit', 'create', 'open', 'manage', 'transition', 'preview', 'duration', 'shortcut', 'appearance', 'spacing'):
        raise w.SetupError('Choose an available card action.')
    validate_context(ipc, ctx)
    request = menu.request
    card = None
    if action in ('flip', 'unfold', 'floating', 'edit', 'preview'):
        card, windows, state = resolve_card(ipc, payload.get('target'), ctx)
        if windows[card['current']]['workspace']['id'] != ctx['workspace']:
            raise w.SetupError('Go to this card’s workspace before editing it.')
        if state.get('animating'):
            raise w.SetupError('Wait for the turn to finish, then try again.')
        if action in ('unfold', 'edit') and payload['target']['kind'] != 'container':
            raise w.SetupError('Create a multi-app card with O to use these controls.')
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
    if action in ('flip', 'unfold', 'floating', 'preview', 'edit', 'create'):
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

    if action in ('flip', 'unfold', 'floating', 'preview'):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('snapshot', 'run'))
    parser.add_argument('--request', default='{}')
    args = parser.parse_args()
    ipc = w.Hyprctl()
    if args.command == 'snapshot':
        print(json.dumps(snapshot(ipc), ensure_ascii=False, allow_nan=False))
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
