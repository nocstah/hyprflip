"""Cards another program opens and saves unattended: its store, the quiet core and the shared steps."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dwindle_test import DwindleIPC
from panel_control_test import control
import repair_test
from setup_test import setup, window

# The move an unattended commit sends, in its batch, for each app it brings to the workspace.
MOVE = re.compile(r'dispatch hl\.dsp\.window\.move\(\{window="address:(0x[0-9a-fA-F]+)",'
                  r'workspace="([^"]+)",follow=(true|false)\}\)')
USAGE = ('Use card <id> flip, card <id> show <front|back>, card <id> ungroup or '
         'card <id> workspace <number|name:<name>|special[:<name>]> [silent].')
# The one focus give_back sends: the pointer stays where it is.
NO_WARP = re.compile(r'function\(\) local focus = hl\.dsp\.focus\(\{ window = "address:(0x[0-9a-fA-F]+)" \}\) '
                     r'local was = hl\.get_config\("cursor\.no_warps"\) == true hl\.config\(\{ cursor = \{ no_warps = true \} \}\) '
                     r'local ok, err = pcall\(hl\.dispatch, focus\) hl\.config\(\{ cursor = \{ no_warps = was \} \}\) '
                     r'if not ok then error\(err\) end end')
REFUSED = 'Those apps are gone or no longer fit; they stay open as separate windows.'
BUSY = 'Finish the active grab or drag before restoring a card.'


class QuietIPC(DwindleIPC):
    """The core as another program drives it: by card id and in batches.

    Four loose apps on dwindle workspace 2 and no card yet. Every call lands in
    log, in order, and time passes only when the code under test sleeps.
    """
    def __init__(self):
        super().__init__()
        self.snapshot.update(containers=[], marked=None, workspace_protection=True,
                             floating_cards=True, card_ungroup=True)
        for w in self.clients.values(): w['grouped'] = []
        self.log, self.later, self.now = [], [], 0.
        # refuse: the message every restore gets back, such as the core's busy refusal.
        self.next_card, self.refuse = 10, None
        self.specials = {'special:park': -98}
        # The pointer, which a plain focus puts in the middle of its window.
        self.pointer = [1500, 300]
        # Faults to inject: apps that cannot move, a batch whose reply is lost
        # after or before it ran, a failing dispatch, and a hook after a batch.
        self.stuck, self.lost, self.failing, self.after_batch = set(), None, None, None

    # The clock that replaces workflow's time module.
    def monotonic(self): return self.now

    def sleep(self, seconds):
        self.now += seconds
        while self.later and self.later[0][0] <= self.now:
            self.later.pop(0)[1]()

    def at(self, when, action):
        """Run action once the code under test has slept until when."""
        self.later.append((when, action))
        self.later.sort(key=lambda event: event[0])

    def windows(self):
        self.log.append(('windows',))
        return deepcopy(self.clients)

    def status(self):
        self.log.append(('status',))
        return deepcopy(self.snapshot)

    def data(self, *args):
        self.log.append(('data', *args))
        if args == ('-j', 'workspaces'):
            ids = {self.workspace} | {w['workspace']['id'] for w in self.clients.values()}
            return [{'id': i, 'tiledLayout': self.layout, 'monitorID': 0} for i in sorted(ids)]
        if args == ('-j', 'monitors'):
            # A 4K screen at scale 1.5 with a 40 px bar on top.
            return [{'id': 0, 'x': 0, 'y': 0, 'width': 3840, 'height': 2160, 'scale': 1.5, 'transform': 0,
                     'reserved': [0, 40, 0, 0]}]
        return super().data(*args)

    def focus(self, address):
        self.log.append(('focus', address))
        super().focus(address)
        if self.clients[address]['workspace']['id'] > 0: self.workspace = self.clients[address]['workspace']['id']
        at, size = self.clients[address]['at'], self.clients[address]['size']
        self.pointer = [at[0] + size[0] // 2, at[1] + size[1] // 2]

    def call(self, *args):
        # Dispatches outside a batch, such as giving the keyboard back.
        self.log.append(('call', *args)); self.mutations.append(('call', *args))
        if self.failing: raise self.failing
        command = args[1] if len(args) == 2 and args[0] == 'dispatch' else ''
        if focus := re.fullmatch(r'hl\.dsp\.focus\(\{window="address:(0x[0-9a-fA-F]+)"\}\)', command):
            self.active = focus.group(1)
            window = self.clients[self.active]
            self.pointer = [window['at'][0] + window['size'][0] // 2, window['at'][1] + window['size'][1] // 2]
        elif focus := NO_WARP.fullmatch(command):
            if focus.group(1) in self.clients: self.active = focus.group(1)
        elif workspace := re.fullmatch(r'hl\.dsp\.focus\(\{workspace=(\d+)\}\)', command):
            self.workspace = int(workspace.group(1))
        return 'ok'

    def tile(self, window):
        self.log.append(('tile', window['address'])); self.mutations.append(('tile', window['address']))
        self.clients[window['address']]['floating'] = False

    def restore_float(self, window):
        self.log.append(('restore_float', window['address'])); self.mutations.append(('restore_float', window['address']))
        self.clients[window['address']].update(floating=True, at=list(window['at']), size=list(window['size']))

    def move(self, address, workspace):
        self.log.append(('move', address, workspace)); self.mutations.append(('move', address, workspace))
        if address in self.stuck: raise setup.SetupError('The app could not move to the card workspace. Open the picker and try again.')
        place = self.place(workspace)
        if place is None or address not in self.clients:
            raise setup.SetupError('The selected app or workspace is no longer available.')
        self.clients[address]['workspace'] = {'id': place['id'], 'name': place['name']}

    def action(self, action):
        self.log.append(('action', action))
        answer = self.core(action)
        if answer is None: return super().action(action)
        self.mutations.append(('action', action))
        if not answer[0]: raise setup.SetupError(answer[1])
        return 'ok: ' + answer[1]

    def batch(self, commands):
        """One reply per command, as hyprctl --batch gives them."""
        self.log.append(('batch', tuple(commands))); self.mutations.append(('batch', tuple(commands)))
        if self.lost == 'before': raise subprocess.TimeoutExpired('hyprctl', 8)
        replies = []
        for command in commands:
            if move := MOVE.fullmatch(command):
                address, workspace, follow = move.groups()
                place = self.place(workspace)
                if place is None or address not in self.clients:
                    replies.append('error: That window or workspace does not exist.')
                    continue
                self.clients[address]['workspace'] = {'id': place['id'], 'name': place['name']}
                if follow == 'true': self.active, self.workspace = address, place['id']
                replies.append('ok')
            elif command.startswith('hyprflip ') and (answer := self.core(command[9:])):
                replies.append(('ok: ' if answer[0] else 'error: ') + answer[1])
            else:
                replies.append('error: unknown request')
        if self.after_batch: self.after_batch()
        if self.lost == 'after': raise subprocess.TimeoutExpired('hyprctl', 8)
        return replies

    def place(self, workspace):
        """A destination as status reports it, or None where the core refuses it."""
        if isinstance(workspace, int) or workspace.isdigit():
            number = int(workspace)
            return {'id': number, 'name': str(number), 'special': False} if 0 < number < 2**31 else None
        if not re.fullmatch(r'special(:[A-Za-z0-9_.-]+)?', workspace): return None
        name = workspace if ':' in workspace else 'special:special'
        number = self.specials.setdefault(name, min(self.specials.values()) - 1)
        return {'id': number, 'name': name, 'special': True}

    def core(self, action):
        """The plugin's answer, (ok, message), to an action another program sends; None for menu actions."""
        words = action.split()
        if words[:2] == ['restore', 'quiet']: return self.restore(words[2:])
        if words[:1] == ['reserve']:
            if len(words) == 3 and words[1].isdigit() and 0 < int(words[1]) < 2**31: return True, 'ok'
            return False, 'Use reserve <workspace> <token> [seconds].'
        if words[:1] == ['unreserve']: return True, 'ok'
        if words[:1] == ['card'] and len(words) > 2: return self.card_action(words[1], words[2:])
        return None

    def restore(self, words):
        if self.refuse: return False, self.refuse
        faces, layouts, side = [[], []], [None, None], None
        try:
            mode, active, unfolded = words[0], int(words[1]), int(words[2])
            rest = iter(words[7:])
            for token in rest:
                if token in ('front', 'back'):
                    side = int(token == 'back')
                    layouts[side] = dict(axis=next(rest), focused=next(rest), ratios=[])
                    continue
                address, ratio = token.split(':')
                faces[side].append(address); layouts[side]['ratios'].append(float(ratio))
        except (IndexError, StopIteration, TypeError, ValueError):
            return False, 'Use restore [quiet] <tiled|floating> <active> <unfolded> <x> <y> <w> <h> front ... back ...'
        if mode not in ('tiled', 'floating') or active not in (0, 1):
            return False, 'Use restore [quiet] <tiled|floating> <active> <unfolded> <x> <y> <w> <h> front ... back ...'
        if not all(faces): return False, 'A card needs apps on both faces.'
        members = faces[0] + faces[1]
        if any(a in face for card in self.snapshot['containers'] for face in card['faces'] for a in members):
            return False, 'An app in that card already belongs to another card.'
        if (any(a not in self.clients or self.clients[a]['fullscreen'] for a in members) or
                len({self.clients[a]['workspace']['id'] for a in members}) > 1):
            return False, 'Those apps are gone or no longer fit; they stay open as separate windows.'
        self.add_card(faces, active, layouts, unfolded=bool(unfolded), floating=mode == 'floating')
        return True, 'ok'

    def add_card(self, faces, active=0, layouts=None, unfolded=False, floating=False):
        """A native card, as a quiet restore makes it on its apps' workspace."""
        layouts = deepcopy(layouts) or [dict(axis='horizontal', focused=face[0], ratios=[1.] * len(face)) for face in faces]
        for layout in layouts:
            total = sum(layout['ratios']); layout['ratios'] = [r / total for r in layout['ratios']]
        members = [a for face in faces for a in face]
        workspace = self.clients[members[0]]['workspace']
        card = dict(id=self.next_card, faces=[list(face) for face in faces], active=active,
                    current=layouts[active]['focused'], unfolded=unfolded, box=[0, 0, 1000, 700], native_group=True,
                    fullscreen=False, floating=floating, workspace=dict(workspace, special=workspace['id'] < 0),
                    layouts=layouts)
        self.next_card += 1
        self.snapshot['containers'].append(card)
        for address in members: self.clients[address].update(grouped=list(members), floating=floating)
        # A quiet restore leaves the focus alone, unless it was on an app the card now hides.
        if self.active in members and self.active not in faces[active]: self.active = card['current']
        return card

    def card_action(self, text, words):
        if not text.isdigit() or not int(text): return False, USAGE
        card = next((c for c in self.snapshot['containers'] if c['id'] == int(text)), None)
        if card is None: return False, f'No card has id {text}. Read the ids from status.'
        members = [a for face in card['faces'] for a in face]
        if words == ['ungroup']:
            if card['fullscreen']: return False, 'Leave fullscreen before ungrouping the card.'
            self.snapshot['containers'].remove(card)
            for address in members: self.clients[address]['grouped'] = []
            return True, 'ok'
        if words[0] == 'workspace' and len(words) in (2, 3) and words[2:] in ([], ['silent']):
            place = self.place(words[1])
            if place is None: return False, 'Use a workspace number, name:<name>, special or special:<name>.'
            if card['fullscreen']: return False, 'Leave fullscreen before moving this container.'
            card['workspace'] = place
            for address in members: self.clients[address]['workspace'] = {'id': place['id'], 'name': place['name']}
            if len(words) == 2: self.workspace, self.active = place['id'], card['current']
            return True, 'ok'
        return False, USAGE


class UnattendedTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        # The calling program's own directory for its store.
        self.store_dir = self.root / 'omarelay'; self.store_dir.mkdir(mode=0o700)
        runtime = self.root / 'runtime'; runtime.mkdir(mode=0o700)
        self.env = dict(HYPRLAND_INSTANCE_SIGNATURE='unattended-test', XDG_RUNTIME_DIR=str(runtime),
                        XDG_STATE_HOME=str(self.root / 'state'), XDG_DATA_HOME=str(self.root / 'data'),
                        XDG_DATA_DIRS=str(self.root / 'system'), HOME=str(self.root / 'home'))
        for folder, name, fields in (('data', 'browser', 'Name=Browser'), ('data', 'terminal', 'Name=Terminal'),
                                     ('data', 'obsidian', 'Name=Obsidian'),
                                     ('system', 'gmail', 'Name=Gmail\nStartupWMClass=chrome-mail.google.com__-Default'),
                                     ('system', 'whatsapp', 'Name=WhatsApp\nStartupWMClass=chrome-web.whatsapp.com__-Default')):
            applications = self.root / folder / 'applications'; applications.mkdir(parents=True, exist_ok=True)
            (applications / (name + '.desktop')).write_text(f'[Desktop Entry]\nType=Application\n{fields}\nExec=/usr/bin/true\n')
        self.ipc = QuietIPC(); self.ipc.env = self.env
        self.store = str(self.store_dir / 'cards.json')
        # What each launch brings: (address, class, seconds) for a window that
        # maps on the active workspace and takes the keyboard, and exit codes.
        self.launched, self.arrivals, self.exits = [], {}, {}
        clock = SimpleNamespace(monotonic=lambda: self.ipc.monotonic(), sleep=lambda seconds: self.ipc.sleep(seconds))
        for patcher in (patch.object(setup.DesktopApps, 'launch', side_effect=self.launch),
                        patch.object(setup, 'time', clock)):
            patcher.start(); self.addCleanup(patcher.stop)

    def launch(self, entry):
        # gio never runs; a test decides when, or whether, a window appears.
        self.launched.append(entry.id)
        if entry.id in self.arrivals:
            address, name, after = self.arrivals[entry.id]
            self.ipc.at(self.ipc.now + after, lambda: self.appear(address, name))
        code = self.exits.get(entry.id)
        return Mock(poll=lambda: code)

    def appear(self, address, name, focus=True, title=''):
        """A new window as Hyprland maps it: on the active workspace, with the keyboard."""
        workspace = self.ipc.workspace
        self.ipc.clients[address] = window(address, **{'class': name, 'initialClass': name, 'title': title, 'at': [1220, 0],
                                                       'size': [600, 700], 'workspace': {'id': workspace, 'name': str(workspace)}})
        if focus: self.ipc.active = address

    def send(self, action, **fields):
        """The reply control.py prints for one request; its exit code agrees with ok."""
        reply, code = control.run_unattended(json.dumps({'protocol': 1, 'action': action, **fields}), self.ipc, self.env)
        self.assertEqual(code, 0 if reply['ok'] else 1, reply)
        self.assertEqual(reply['protocol'], 1)
        json.dumps(reply, ensure_ascii=True, allow_nan=False)
        return reply

    def keep(self, name, recipe):
        setup.RecipeStore(path=self.store, titles=False).change({name: None}, {name: recipe})

    def stored(self):
        return setup.RecipeStore(path=self.store, titles=False).read()

    def acme(self, title=''):
        """OmaRelay's card for a workspace: its browser in front, its terminal and the user's notes behind."""
        notes = self.app('obsidian', 'Obsidian', title) | {'desktop_id': 'obsidian.desktop'}
        return {'faces': [{'apps': [self.app('omarelay-acme', 'Workspace browser', title)], 'axis': 'horizontal',
                           'ratios': [1.], 'focus': 0},
                          {'apps': [self.app('omarelay.terminal.acme', 'Workspace terminal', title), notes],
                           'axis': 'vertical', 'ratios': [.6, .4], 'focus': 0}], 'active': 0}

    def park(self):
        """Herdr's stand-in has the keyboard on workspace 2; the caller's browser and terminal wait on special:park."""
        clients = self.ipc.clients
        clients['0xa'].update({'class': 'herdr', 'initialClass': 'herdr'})
        for address, name in (('0xb', 'omarelay-acme'), ('0xc', 'omarelay.terminal.acme')):
            clients[address].update({'class': name, 'initialClass': name, 'workspace': {'id': -98, 'name': 'special:park'}})
        self.ipc.active, self.ipc.workspace = '0xa', 2

    def opening(self, **fields):
        """An open of the stored acme card on workspace 2, binding the parked browser and terminal."""
        return {'store': self.store, 'name': 'acme', 'workspace': 2, 'bind': ['0xb', '0xc'],
                'owned': ['omarelay-acme', 'omarelay.terminal.acme'], 'focus': '0xa'} | fields

    def batches(self):
        return [entry[1] for entry in self.ipc.log if entry[0] == 'batch']

    def focusing(self):
        """Every dispatch that could move the keyboard or the workspace."""
        return [entry for entry in self.ipc.log if entry[0] in ('focus', 'call')]

    @staticmethod
    def app(name, label, title=''):
        return {'class': name, 'initial_class': name, 'title': title, 'label': label}

    def recipe(self, title=''):
        notes = self.app('obsidian', 'Obsidian', title) | {'desktop_id': 'obsidian.desktop'}
        return {'faces': [{'apps': [self.app('omarelay-acme', 'Workspace browser', title)], 'axis': 'horizontal',
                           'ratios': [1.], 'focus': 0},
                          {'apps': [notes, self.app('foot', 'Terminal', title)], 'axis': 'vertical',
                           'ratios': [.6, .4], 'focus': 1}], 'active': 1}

    def tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))

    def created(self):
        """A patch recording each file the store creates itself: its temporary file."""
        created, real = [], os.open
        def record(path, *args, **kwargs):
            created.append(Path(path))
            return real(path, *args, **kwargs)
        return created, patch.object(setup.os, 'open', side_effect=record)

    def refused_paths(self):
        """Store paths another program may not use, each for its own reason."""
        library = setup.RecipeStore(self.env); library.root.mkdir(parents=True, mode=0o700)
        (self.root / 'link').symlink_to(self.store_dir)
        (self.root / 'state-link').symlink_to(self.root / 'state')
        for name, mode in (('open', 0o777), ('shared', 0o770)):
            (self.root / name).mkdir(); os.chmod(self.root / name, mode)
        (self.root / 'file').write_text('')
        (self.store_dir / 'one.json').write_text('{}'); os.link(self.store_dir / 'one.json', self.store_dir / 'two.json')
        (self.store_dir / 'alias.json').symlink_to(self.store_dir / 'kept.json')
        (self.store_dir / 'folder.json').mkdir()
        mine = str(self.store_dir)
        return [None, mine.encode() + b'/cards.json', 'omarelay/cards.json', mine + '/../omarelay/cards.json',
                mine + '/./cards.json', mine + '//cards.json', str(self.root / 'link/cards.json'),
                str(self.root / 'open/cards.json'), str(self.root / 'shared/cards.json'),
                str(self.root / 'missing/cards.json'), str(self.root / 'file/cards.json'), mine + '/cards.txt',
                mine + '/cards.json.bak', mine + '/.json', mine + '/a b.json', mine + '/cärds.json',
                mine + '/' + 'x' * 65 + '.json', mine + '/one.json', mine + '/two.json', mine + '/alias.json',
                mine + '/folder.json', mine + '\0/cards.json', str(library.path), str(library.root / 'other.json'),
                str(self.root / 'state-link/hyprflip/other.json')]

    def test_store_path_is_checked_before_anything_is_read(self):
        (self.store_dir / 'kept.json').write_text('{"version":1,"cards":{}}')
        refused = self.refused_paths()
        before, valid = self.tree(), setup.RecipeStore.valid_path
        with (patch.object(setup.RecipeStore, 'read', side_effect=AssertionError('read')),
              patch.object(Path, 'open', side_effect=AssertionError('opened')),
              patch.object(setup.os, 'open', side_effect=AssertionError('created'))):
            for path in refused:
                with self.subTest(path=path): self.assertFalse(valid(path, self.env))
            for path in (self.store_dir / 'cards.json', self.store_dir / 'kept.json'):
                self.assertTrue(valid(str(path), self.env))
            # Every action that takes a store refuses these before anything else.
            for path in refused:
                if isinstance(path, bytes): continue
                for action, fields in (('list', {}), ('delete', {'name': 'acme', 'token': '0' * 64}),
                                       ('open', {'name': 'acme', 'workspace': 2}),
                                       ('save', {'name': 'acme', 'card': 10, 'members': ['0xa'], 'previous': None})):
                    with self.subTest(path=path, action=action):
                        self.assertEqual(self.send(action, store=path, **fields)['code'], 'invalid_store')
            os.chmod(self.store_dir, 0o755)
            self.assertTrue(valid(str(self.store_dir / 'cards.json'), self.env))
            # Another user's directory, or file, is never used.
            with patch.object(setup.os, 'getuid', return_value=os.getuid() + 1):
                self.assertFalse(valid(str(self.store_dir / 'cards.json'), self.env))
                self.assertFalse(valid(str(self.store_dir / 'kept.json'), self.env))
                self.assertEqual(self.send('list', store=str(self.store_dir / 'kept.json'))['code'], 'invalid_store')
        self.assertEqual(self.ipc.log, [])
        self.assertEqual(self.tree(), before)
        self.assertEqual((self.store_dir / 'kept.json').read_text(), '{"version":1,"cards":{}}')

    def test_store_path_keeps_lock_and_temp_beside_it_and_blanks_titles(self):
        path = self.store_dir / 'acme.json'
        store, recipe = setup.RecipeStore(path=str(path), titles=False), self.recipe('Inbox – private@example.com')
        created, recording = self.created()
        with recording: store.change({'Acme': None}, {'Acme': recipe})
        self.assertEqual([p.parent for p in created], [self.store_dir])
        self.assertRegex(created[0].name, r'^acme-[0-9a-f]{32}$')
        self.assertEqual(sorted(p.name for p in self.store_dir.iterdir()), ['acme.json', 'acme.lock'])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn('private@example.com', path.read_text())
        self.assertEqual(store.read(), {'Acme': setup.RecipeStore.untitled(recipe)})
        self.assertEqual(recipe['faces'][0]['apps'][0]['title'], 'Inbox – private@example.com')
        self.assertFalse((self.root / 'state').exists())
        # Its directory belongs to its program, which makes it; the store never does.
        gone = setup.RecipeStore(path=str(self.root / 'gone/acme.json'), titles=False)
        with self.assertRaises(OSError): gone.change({'Acme': None}, {'Acme': recipe})
        self.assertFalse((self.root / 'gone').exists())

    def test_default_library_names_are_unchanged(self):
        store = setup.RecipeStore(self.env)
        self.assertEqual((store.root, store.path), (self.root / 'state/hyprflip', self.root / 'state/hyprflip/cards.json'))
        self.assertEqual(setup.RecipeStore({'HOME': str(self.root / 'home')}).path,
                         self.root / 'home/.local/state/hyprflip/cards.json')
        created, recording = self.created()
        with recording: store.update('Acme', self.recipe('Inbox'), None)
        self.assertEqual([p.parent for p in created], [store.root])
        self.assertRegex(created[0].name, r'^cards-[0-9a-f]{32}$')
        self.assertEqual(sorted(p.name for p in store.root.iterdir()), ['cards.json', 'cards.lock'])
        self.assertEqual(stat.S_IMODE(store.root.stat().st_mode), 0o700)
        # The menus' library keeps titles, which tell apart two windows of one app.
        self.assertEqual(store.read(), {'Acme': self.recipe('Inbox')})
        self.assertEqual(list(self.store_dir.iterdir()), [])

    def test_corrupt_store_is_store_unreadable(self):
        path = self.store_dir / 'acme.json'
        store = setup.RecipeStore(path=str(path), titles=False)
        self.carded()
        # The last is nested deeper than the JSON parser goes, though still under the store's 1 MiB.
        for content in (b'broken json', b'\xff\xfe', b'{"version":2,"cards":{}}', b'{"version":1,"cards":{"Acme":{"active":0}}}',
                        b'{"version":1,"cards":' + b'[' * 500000 + b']' * 500000 + b'}'):
            path.write_bytes(content)
            with self.subTest(content=content[:40]):
                with self.assertRaisesRegex(setup.SetupError, 'could not be read.*has not been overwritten'): store.read()
                with self.assertRaisesRegex(setup.SetupError, 'has not been overwritten'):
                    store.change({'Acme': None}, {'Acme': self.recipe()})
                for action, fields in (('list', {}), ('delete', {'name': 'Acme', 'token': '0' * 64}),
                                       ('open', {'name': 'Acme', 'workspace': 2}), ('save', self.saving(name='Acme'))):
                    reply = self.send(action, **(fields | {'store': str(path)}))
                    self.assertEqual((reply['code'], reply['message']), ('store_unreadable', setup.Unfinished.MESSAGES['store_unreadable']))
                self.assertEqual(path.read_bytes(), content)
        # A recipe the store cannot keep is a ValueError, raised before the file is touched.
        path.write_bytes(b'{"version":1,"cards":{}}')
        for broken in ({'faces': [], 'active': 0}, {'active': 0}, {'faces': ['app'], 'active': 0}, 'card'):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                store.change({'Acme': None}, {'Acme': broken})
            self.assertEqual(path.read_bytes(), b'{"version":1,"cards":{}}')
        # A save the store refuses that way is store_unreadable too.
        with patch.object(setup.RecipeStore, 'change', side_effect=ValueError()):
            self.assertEqual(self.send('save', **self.saving(name='Acme', store=str(path)))['code'], 'store_unreadable')
        self.assertEqual(path.read_bytes(), b'{"version":1,"cards":{}}')
        self.assertEqual(sorted(p.name for p in self.store_dir.iterdir()), ['acme.json', 'acme.lock'])

    def test_tokens_are_the_digest_control_has_always_used(self):
        recipe = self.recipe()
        recipe['faces'][1]['apps'][0]['label'] = 'Obsidian – Notes'
        # Computed with control.digest before it moved; OmaCards keeps these tokens.
        self.assertEqual(setup.digest(recipe), '349d16d7613a13fae95c5c58a325289518bb7c2c94a087622b652daa09f3157d')
        self.assertEqual(setup.digest({'b': 1, 'a': [.1, 'é']}), '1b64701f50a913afd3586f5a6d3541f24ce3a067e9d57d8cecde00955bc37e13')
        self.assertIs(control.digest, setup.digest)
        with self.assertRaises(ValueError): setup.digest({'ratio': float('nan')})

    def test_lock_waits_poll_until_their_time_runs_out_or_they_are_cancelled(self):
        request = setup.Request(Path(self.env['XDG_RUNTIME_DIR']), 'unattended-test')
        with request.exclusive(timeout=.2): self.assertEqual(self.ipc.now, 0)
        holder = request.lock.open('a'); self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        with self.assertRaises(setup.Busy) as busy:
            with request.exclusive(timeout=.2): self.fail('The held lock was taken.')
        self.assertIsInstance(busy.exception, setup.SetupError)
        self.assertTrue(.2 <= self.ipc.now < .26, self.ipc.now)
        # Released while it waits, the lock is taken at the next try, 50 ms apart.
        start = self.ipc.now
        self.ipc.at(start + .12, lambda: fcntl.flock(holder, fcntl.LOCK_UN))
        with request.exclusive(timeout=1): self.assertAlmostEqual(self.ipc.now - start, .15)
        # cancelled() is asked before each try; with no timeout the wait ends only there.
        fcntl.flock(holder, fcntl.LOCK_EX)
        cancelled, start = Mock(side_effect=[False, False, True]), self.ipc.now
        with self.assertRaises(setup.Cancelled):
            with request.exclusive(cancelled=cancelled): self.fail('The held lock was taken.')
        self.assertEqual(cancelled.call_count, 3)
        self.assertAlmostEqual(self.ipc.now - start, .1)
        # A request cancelled before it starts never takes the lock, even a free one.
        fcntl.flock(holder, fcntl.LOCK_UN)
        with self.assertRaises(setup.Cancelled):
            with request.exclusive(timeout=1, cancelled=lambda: True): self.fail('The lock was taken.')
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_batch_is_one_request_whose_refusals_are_replies(self):
        ipc = setup.Hyprctl(self.env)
        commands = ['hyprflip card 3 workspace special:park silent', 'dispatch hl.dsp.layout("preselect r")',
                    'hyprflip card 9 workspace 2 silent']
        output = 'ok: ok\n\n\nok\n\n\nerror: No card has id 9. Read the ids from status.\n'
        with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
            self.assertEqual(ipc.batch(commands), ['ok: ok', 'ok', 'error: No card has id 9. Read the ids from status.'])
        run.assert_called_once_with(['hyprctl', '--batch', ' ; '.join(commands)], env=self.env,
                                    capture_output=True, text=True, timeout=8)
        # hyprctl 0.56 exits 0 after a batch that Hyprland never answered; its own last line says so.
        for code, output in ((0, "Couldn't connect to /run/user/1000/hypr/unattended-test/.socket.sock. (4)\n"),
                             (0, "Hyprland IPC didn't respond in time\nCouldn't read (6)\n"),
                             (0, 'HYPRLAND_INSTANCE_SIGNATURE was not set! (Is Hyprland running?) (3)\n'), (1, '')):
            with (patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, output, '')),
                  self.subTest(output=output), self.assertRaisesRegex(setup.SetupError, r'^Hyprland is not responding\.$')):
                ipc.batch(commands)
        for error in (subprocess.TimeoutExpired('hyprctl', 8), FileNotFoundError('hyprctl')):
            with (patch.object(setup.subprocess, 'run', side_effect=error),
                  self.assertRaisesRegex(setup.SetupError, r'^Hyprland is not responding\.$')):
                ipc.batch(commands)
        # Hyprland splits a request on ';' outside brackets, so a command that
        # could split, or swallow the next one, is never sent.
        for unsafe in ([], [''], [' '], ['hyprflip card 3 flip; hyprflip card 4 flip'],
                       ['dispatch hl.dsp.exec_cmd([[true]])'], ['hyprflip card 3 flip', None]):
            with patch.object(setup.subprocess, 'run') as run, self.subTest(unsafe=unsafe):
                with self.assertRaises(setup.SetupError): ipc.batch(unsafe)
                run.assert_not_called()

    def test_move_reaches_a_special_workspace_by_its_name(self):
        ipc, clients = setup.Hyprctl(self.env), {'0xe': window('0xe')}
        landing = {'id': -98, 'name': 'special:park'}
        def dispatch(*args): clients['0xe']['workspace'] = dict(landing)
        with (patch.object(ipc, 'call', side_effect=dispatch) as call,
              patch.object(ipc, 'windows', side_effect=lambda: deepcopy(clients))):
            ipc.move('0xe', 'special:park')
            call.assert_called_once_with(
                'dispatch', 'hl.dsp.window.move({window="address:0xe",workspace="special:park",follow=false})')
            # It waits for that name: an app that lands on another one is reported.
            with self.assertRaisesRegex(setup.SetupError, 'could not move'): ipc.move('0xe', 'special:other')
            self.assertGreaterEqual(self.ipc.now, 3)
            landing = {'id': 3, 'name': '3'}
            ipc.move('0xe', 3)
            self.assertEqual(call.call_args.args[1], 'hl.dsp.window.move({window="address:0xe",workspace="3",follow=false})')
            call.reset_mock()
            for workspace in ('special', 'special:', 'park', 'name:park', 'special:a b', 'special:park"', 'special:park\n',
                              'special:' + 'x' * 57, 0, -98, 2**31):
                with self.subTest(workspace=workspace), self.assertRaisesRegex(setup.SetupError, 'no longer available'):
                    ipc.move('0xe', workspace)
            call.assert_not_called()

    def test_apps_from_a_special_workspace_take_no_lease_and_go_back_by_name(self):
        ipc = self.ipc
        ipc.add_card([['0xa'], ['0xb']])
        ipc.move('0xd', 'special:park'); ipc.log.clear(); ipc.mutations.clear()
        flow, moved = setup.Setup(ipc, None), []
        selected = {a: w for a, w in ipc.windows().items() if a in ('0xc', '0xd')}
        with flow.reserve(selected, ipc.status(), 2):
            flow.import_windows(selected, 2, moved)
            # The core refuses the card, since 0xb belongs to another one.
            line = 'hyprflip restore quiet tiled 0 0 0 0 1000 700 front horizontal 0xd 0xd:1 back horizontal 0xb 0xb:1'
            self.assertEqual(ipc.batch([line]), ['error: An app in that card already belongs to another card.'])
            flow.restore_imports(moved, 2)
        lease, there, batch, back, release = ipc.mutations
        self.assertRegex(lease[1], r'^reserve 2 [0-9a-f]{32}$')
        self.assertEqual((there, batch, back), (('move', '0xd', 2), ('batch', (line,)), ('move', '0xd', 'special:park')))
        self.assertEqual(release, ('action', 'unreserve ' + lease[1].split()[2]))
        self.assertEqual(ipc.windows()['0xd']['workspace'], {'id': -98, 'name': 'special:park'})
        self.assertEqual([c['id'] for c in ipc.status()['containers']], [10])

    def test_launchers_come_from_the_class_alone_and_owned_apps_get_none(self):
        catalog = setup.DesktopApps(self.env)
        # Labels that name unrelated launchers: an own browser called Browser and a slug containing whatsapp.
        browser, team = self.app('omarelay-acme', 'Browser'), self.app('omarelay-whatsapp-team', 'WhatsApp')
        gmail, terminal = self.app('chrome-mail.google.com__-Default', 'Gmail'), self.app('foot', 'Terminal')
        def inferred(by_label): return [getattr(catalog.infer(a, by_label), 'id', None) for a in (browser, team, gmail, terminal)]
        self.assertEqual(inferred(True), ['browser.desktop', 'whatsapp.desktop', 'gmail.desktop', 'terminal.desktop'])
        self.assertEqual(inferred(False), [None, None, 'gmail.desktop', None])
        captured = {'faces': [{'apps': [browser, team]}, {'apps': [gmail, terminal]}], 'active': 0}
        # A launcher the reference remembered still wins, except for an owned app.
        reference = deepcopy(captured)
        reference['faces'][0]['apps'][0]['desktop_id'] = 'browser.desktop'
        reference['faces'][1]['apps'][1]['desktop_id'] = 'terminal.desktop'
        recipe = deepcopy(captured)
        setup.Saved.remember_launchers(recipe, reference, catalog, by_label=False, owned=('omarelay-acme', 'omarelay-whatsapp-team'))
        self.assertEqual([a.get('desktop_id') for f in recipe['faces'] for a in f['apps']],
                         [None, None, 'gmail.desktop', 'terminal.desktop'])
        # The menus still guess by label.
        recipe = deepcopy(captured)
        setup.Saved.remember_launchers(recipe, None, catalog)
        self.assertEqual([a.get('desktop_id') for f in recipe['faces'] for a in f['apps']],
                         ['browser.desktop', 'whatsapp.desktop', 'gmail.desktop', 'terminal.desktop'])

    def test_launched_windows_come_from_the_callers_candidates_and_failures_are_returned(self):
        catalog = setup.DesktopApps(self.env)
        gmail_class = 'chrome-mail.google.com__-Default'
        recipe = {'faces': [{'apps': [self.app('omarelay-acme', 'Workspace browser')], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0},
                            {'apps': [self.app(gmail_class, 'Gmail'), self.app('foot', 'Terminal')], 'axis': 'vertical',
                             'ratios': [.5, .5], 'focus': 0}], 'active': 1}
        apps = [a for face in recipe['faces'] for a in face['apps']]
        launchers = {1: catalog.apps['gmail.desktop'], 2: catalog.apps['terminal.desktop']}
        # Both launches exited with an error; Gmail's window still appeared, on a special workspace.
        exited = {1: Mock(poll=lambda: 1), 2: Mock(poll=lambda: 1)}
        candidates = {'0xa': window('0xa', **{'class': 'omarelay-acme'}),
                      '0xb': window('0xb', **{'class': gmail_class, 'title': 'Older inbox'}),
                      '0x20': window('0x20', **{'class': gmail_class, 'title': 'Inbox – private@example.com',
                                                'workspace': {'id': -98, 'name': 'special:park'}})}
        chosen = ['0xa', None, None]
        self.assertEqual(setup.Saved.identify_launched(apps, launchers, exited, chosen, candidates, {'0xa', '0xb'}), [2])
        self.assertEqual(chosen, ['0xa', '0x20', None])
        remembered = setup.Saved.remember_opened(recipe, {1: launchers[1]}, chosen, candidates)
        self.assertEqual(remembered['faces'][1]['apps'][0], {'class': gmail_class, 'initial_class': '', 'label': 'Gmail',
                         'title': 'Inbox – private@example.com', 'desktop_id': 'gmail.desktop'})
        self.assertNotIn('desktop_id', recipe['faces'][1]['apps'][0])
        self.assertEqual(remembered['faces'][1]['apps'][1], recipe['faces'][1]['apps'][1])

    def test_the_fake_core_answers_as_the_nested_suites_measured(self):
        # As card_id_workflows.py found: ok: ok for a plugin action, ok for a
        # dispatch and error: <refusal> for a refused one, in the batch's order.
        ipc = self.ipc
        line = 'restore quiet tiled 1 0 0 0 1000 700 front horizontal 0xa 0xa:1 back vertical 0xc 0xb:3 0xc:1'
        self.assertEqual(ipc.batch(['hyprflip ' + line]), ['ok: ok'])
        card = ipc.status()['containers'][0]
        self.assertEqual((card['id'], card['faces'], card['current'], card['layouts'][1]['ratios'], ipc.active),
                         (10, [['0xa'], ['0xb', '0xc']], '0xc', [.75, .25], '0xb'))
        replies = ipc.batch(['hyprflip card 10 workspace special:park silent',
                             'dispatch hl.dsp.window.move({window="address:0xd",workspace="special:park",follow=false})',
                             'hyprflip card 99 workspace 2 silent'])
        self.assertEqual(replies, ['ok: ok', 'ok', 'error: No card has id 99. Read the ids from status.'])
        self.assertEqual(ipc.status()['containers'][0]['workspace'], {'id': -98, 'name': 'special:park', 'special': True})
        self.assertEqual({w['workspace']['name'] for w in ipc.windows().values()}, {'special:park'})
        with self.assertRaisesRegex(setup.SetupError, r'^An app in that card already belongs to another card\.$'):
            ipc.action(line)
        self.assertEqual(ipc.action('card 10 ungroup'), 'ok: ok')
        self.assertEqual((ipc.status()['containers'], ipc.clients['0xb']['grouped'], ipc.workspace), ([], [], 2))
        self.assertEqual([entry[0] for entry in ipc.log],
                         ['batch', 'status', 'batch', 'status', 'windows', 'action', 'action', 'status'])

    # Listing and deleting.

    def test_list_reports_tokens_classes_and_launchers_without_titles(self):
        self.assertEqual(self.send('list', store=self.store), {'protocol': 1, 'ok': True, 'result': 'list', 'cards': {}})
        self.keep('acme', self.acme('Inbox – private@example.com'))
        self.keep('Notes', self.recipe() | {'floating': True})
        reply = self.send('list', store=self.store)
        self.assertNotIn('private@example.com', json.dumps(reply))
        acme = reply['cards']['acme']
        self.assertEqual(acme['token'], setup.digest(self.acme()))
        self.assertEqual((acme['active'], acme['floating'], reply['cards']['Notes']['floating']), (0, False, True))
        self.assertEqual(acme['faces'], [
            [{'class': 'omarelay-acme', 'initial_class': 'omarelay-acme', 'label': 'Workspace browser', 'launcher': False}],
            [{'class': 'omarelay.terminal.acme', 'initial_class': 'omarelay.terminal.acme', 'label': 'Workspace terminal',
              'launcher': False},
             {'class': 'obsidian', 'initial_class': 'obsidian', 'label': 'Obsidian', 'launcher': True}]])
        self.assertEqual(self.send('list', store=self.store, name='acme')['cards'], {'acme': acme})
        self.assertEqual(self.send('list', store=self.store, name='Gone')['cards'], {})
        self.assertEqual(self.send('list', store=self.store, name='')['code'], 'invalid_name')
        # Listing never asks Hyprland.
        self.assertEqual(self.ipc.log, [])

    def test_delete_requires_the_current_token(self):
        self.keep('acme', self.acme()); self.keep('Notes', self.recipe())
        token = self.send('list', store=self.store)['cards']['acme']['token']
        stale = self.send('delete', store=self.store, name='acme', token='0' * 64)
        self.assertEqual((stale['code'], stale['launched']), ('conflict', []))
        self.assertEqual(set(self.stored()), {'acme', 'Notes'})
        for token_value in ('A' * 64, '0' * 63, None, 7):
            with self.subTest(token=token_value):
                self.assertEqual(self.send('delete', store=self.store, name='acme', token=token_value)['code'], 'invalid_request')
        self.assertEqual(self.send('delete', store=self.store, name='acme', token=token)['result'], 'deleted')
        self.assertEqual(set(self.stored()), {'Notes'})
        self.assertEqual(self.send('delete', store=self.store, name='acme', token=token)['result'], 'absent')
        self.assertEqual(self.ipc.log, [])

    # Opening.

    def test_open_builds_with_one_batch_and_leaves_focus_workspace_and_current_alone(self):
        self.park(); self.keep('acme', self.acme())
        self.ipc.clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian', 'workspace': {'id': 3, 'name': '3'}})
        working, pointer = deepcopy(self.ipc.clients['0xa']), list(self.ipc.pointer)
        menus = setup.Request(Path(self.env['XDG_RUNTIME_DIR']), 'unattended-test')
        reply = self.send('open', **self.opening(bind=['0xb', '0xc', '0xd']))
        def slot(name, label, address, launcher=False):
            return {'class': name, 'initial_class': name, 'label': label, 'launcher': launcher, 'address': address}
        self.assertEqual(reply, {'protocol': 1, 'ok': True, 'result': 'opened', 'card': 10, 'token': setup.digest(self.acme()),
                                 'workspace': {'id': 2, 'name': '2', 'special': False},
                                 'slots': [[slot('omarelay-acme', 'Workspace browser', '0xb')],
                                           [slot('omarelay.terminal.acme', 'Workspace terminal', '0xc'),
                                            slot('obsidian', 'Obsidian', '0xd', True)]],
                                 'launched': [], 'unused': [], 'focus_returned': True})
        # The moves, front face first, then the restore: one request, which
        # gives the card the screen's free area since its front app was away.
        moves = tuple(f'dispatch hl.dsp.window.move({{window="address:{a}",workspace="2",follow=false}})'
                      for a in ('0xb', '0xc', '0xd'))
        self.assertEqual(self.batches(), [moves + ('hyprflip restore quiet tiled 0 0 0 40 2560 1400 front horizontal 0xb 0xb:1 '
                                                   'back vertical 0xc 0xc:0.6 0xd:0.4',)])
        self.assertEqual([m[0] for m in self.ipc.mutations], ['action', 'action', 'batch', 'action', 'action'])
        self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xb'], ['0xc', '0xd']])
        # The keyboard, the workspace, the pointer and the working tile stay as
        # they were, and a menu's request is never superseded.
        self.assertEqual(self.focusing(), [])
        self.assertEqual((self.ipc.active, self.ipc.workspace, self.ipc.pointer, self.ipc.clients['0xa']),
                         ('0xa', 2, pointer, working))
        self.assertFalse(menus.current.exists())

    def test_open_imports_bound_windows_from_a_special_workspace_silently(self):
        self.park(); self.keep('acme', self.acme())
        magic = self.ipc.place('special:magic')
        self.ipc.clients['0xc']['workspace'] = {'id': magic['id'], 'name': magic['name']}
        reply = self.send('open', **self.opening(launch=False))
        self.assertEqual((reply['result'], reply['slots'][1][1]['missing']), ('opened', 'not_launched'))
        (batch,) = self.batches()
        self.assertEqual([MOVE.fullmatch(c).groups() for c in batch[:-1]], [('0xb', '2', 'false'), ('0xc', '2', 'false')])
        self.assertEqual(batch[-1], 'hyprflip restore quiet tiled 0 0 0 40 2560 1400 front horizontal 0xb 0xb:1 '
                                    'back vertical 0xc 0xc:1')
        # A special workspace takes no lease; the destination does.
        leases = [m[1].split()[1] for m in self.ipc.mutations if m[0] == 'action' and m[1].startswith('reserve ')]
        self.assertEqual(leases, ['2'])
        self.assertEqual({self.ipc.clients[a]['workspace']['id'] for a in ('0xb', '0xc')}, {2})
        self.assertEqual((self.ipc.active, self.ipc.workspace, self.focusing()), ('0xa', 2, []))

    def test_open_takes_only_bound_windows(self):
        self.park(); self.keep('acme', self.acme())
        # A loose copy of the workspace browser and the user's notes, and a card
        # that already shows this definition: none of them is the caller's.
        clients = self.ipc.clients
        clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian'})
        for address, name in (('0xe', 'omarelay-acme'), ('0xf', 'omarelay.terminal.acme'), ('0x10', 'omarelay-acme')):
            clients[address] = window(address, **{'class': name, 'initialClass': name, 'at': [0, 0], 'size': [600, 700]})
        self.ipc.add_card([['0xe'], ['0xf']])
        before = deepcopy(self.ipc.snapshot['containers'][0])
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], reply['card'], reply['slots'][1][1]['missing']), ('opened', 11, 'open_elsewhere'))
        self.assertEqual(self.ipc.snapshot['containers'], [before, self.ipc.snapshot['containers'][1]])
        self.assertEqual(self.ipc.snapshot['containers'][1]['faces'], [['0xb'], ['0xc']])
        self.assertFalse(any(a in command for command in self.batches()[0] for a in ('0xd', '0xe', '0xf', '0x10')))
        self.assertEqual(self.launched, [])

    def test_open_never_launches_owned_or_label_matched_apps(self):
        clients = self.ipc.clients
        clients['0xc'].update({'class': 'notes', 'initialClass': 'notes'})
        # Each label names an installed launcher: Browser, Terminal and WhatsApp.
        recipe = {'faces': [{'apps': [self.app('omarelay-acme', 'Browser'), self.app('notes', 'Notes')],
                             'axis': 'horizontal', 'ratios': [.5, .5], 'focus': 1},
                            {'apps': [self.app('omarelay.terminal.acme', 'Terminal'), self.app('omarelay-whatsapp-team', 'WhatsApp'),
                                      self.app('foot', 'Terminal')], 'axis': 'vertical', 'ratios': [.3, .3, .4], 'focus': 2}],
                  'active': 0}
        reply = self.send('open', recipe=recipe, workspace=2, bind=['0xc', '0xd'], owned=['omarelay-acme', 'omarelay.terminal.acme'])
        self.assertEqual(reply['result'], 'opened')
        self.assertEqual([[s.get('missing') for s in face] for face in reply['slots']],
                         [['owned', None], ['owned', 'no_launcher', None]])
        self.assertEqual((self.launched, reply['launched']), ([], []))
        self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xc'], ['0xd']])

    def test_open_launches_by_stored_desktop_id_or_class_only(self):
        self.ipc.clients['0xc'].update({'class': 'notes', 'initialClass': 'notes'})
        gmail = 'chrome-mail.google.com__-Default'
        recipe = {'faces': [{'apps': [self.app('notes', 'Notes')], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0},
                            {'apps': [self.app('foot', 'Terminal'),
                                      # Its own launcher, remembered by id; its class names none.
                                      self.app('md.obsidian.Obsidian', 'Obsidian') | {'desktop_id': 'obsidian.desktop'},
                                      # A launcher whose StartupWMClass is the class, and one whose id is.
                                      self.app(gmail, 'Mail'), self.app('terminal', 'Console'),
                                      # Only its label names a launcher.
                                      self.app('helium', 'Browser')],
                             'axis': 'horizontal', 'ratios': [.2] * 5, 'focus': 0}], 'active': 0}
        self.arrivals.update({'obsidian.desktop': ('0x30', 'md.obsidian.Obsidian', .1), 'gmail.desktop': ('0x31', gmail, .15),
                              'terminal.desktop': ('0x32', 'terminal', .2)})
        reply = self.send('open', recipe=recipe, workspace=2, bind=['0xc', '0xd'], focus='0xa')
        self.assertEqual(self.launched, ['obsidian.desktop', 'gmail.desktop', 'terminal.desktop'])
        self.assertEqual(reply['launched'], [
            {'class': 'md.obsidian.Obsidian', 'initial_class': 'md.obsidian.Obsidian', 'wm_class': '',
             'desktop_id': 'obsidian.desktop', 'address': '0x30'},
            {'class': gmail, 'initial_class': gmail, 'wm_class': gmail, 'desktop_id': 'gmail.desktop', 'address': '0x31'},
            {'class': 'terminal', 'initial_class': 'terminal', 'wm_class': '', 'desktop_id': 'terminal.desktop', 'address': '0x32'}])
        self.assertEqual([s.get('missing') for s in reply['slots'][1]], [None, None, None, None, 'no_launcher'])
        self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xc'], ['0xd', '0x30', '0x31', '0x32']])
        self.assertEqual(self.ipc.snapshot['containers'][0]['layouts'][1]['ratios'], [.25] * 4)

    def test_open_reports_owned_open_elsewhere_not_launched_and_no_launcher(self):
        recipe = self.acme()
        recipe['faces'][0]['apps'].append(self.app('omarelay-acme-2', 'Workspace browser'))
        recipe['faces'][0]['ratios'] = [.5, .5]
        recipe['faces'][1]['apps'].append(self.app('slack', 'Slack'))
        recipe['faces'][1]['ratios'] = [.5, .3, .2]
        owned = ['omarelay-acme', 'omarelay-acme-2', 'omarelay.terminal.acme']
        for launch, expected in ((True, [['owned'], ['open_elsewhere', 'no_launcher']]),
                                 (False, [['owned'], ['not_launched', 'not_launched']])):
            with self.subTest(launch=launch):
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
                if launch: self.ipc.clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian',
                                                           'workspace': {'id': 3, 'name': '3'}})
                reply = self.send('open', recipe=recipe, workspace=2, bind=['0xb', '0xc'], owned=owned, launch=launch)
                self.assertEqual(reply['result'], 'opened')
                self.assertEqual([[s['missing'] for s in face if 'missing' in s] for face in reply['slots']], expected)
                self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xb'], ['0xc']])
                self.assertEqual(self.launched, [])

    def test_open_gives_the_keyboard_back_only_from_its_own_launches_on_the_same_workspace(self):
        back = [('call', 'dispatch', setup.Unattended.focus_command('0xa'))]
        # Another app's window takes the keyboard first; the new notes window then does.
        self.park(); self.keep('acme', self.acme()); pointer = list(self.ipc.pointer)
        self.arrivals['obsidian.desktop'] = ('0x30', 'obsidian', .2)
        self.ipc.at(.1, lambda: self.appear('0x40', 'slack'))
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], reply['focus_returned'], self.focusing()), ('opened', True, back))
        self.assertEqual((self.ipc.active, self.ipc.pointer), ('0xa', pointer))
        # Once the user has gone to another workspace, the keyboard stays with them.
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        def leave(): self.ipc.workspace, self.ipc.active = 5, None
        self.ipc.at(.1, leave)
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], self.focusing(), self.ipc.workspace), ('opened', [], 5))
        # The caller's window went to another workspace while the user stayed: focusing it would take
        # the user's screen there, so the keyboard stays with the new window.
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        self.ipc.at(.1, lambda: self.ipc.clients['0xa'].update(workspace={'id': 3, 'name': '3'}))
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], reply['focus_returned'], self.focusing(), self.ipc.workspace),
                         ('opened', False, [], 2))
        # Each new window gives it back once: a click on it later is the user's.
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        recipe = self.acme()
        recipe['faces'][1]['apps'][0] = self.app('chrome-mail.google.com__-Default', 'Gmail')
        self.arrivals.update({'obsidian.desktop': ('0x30', 'obsidian', .1)})
        self.ipc.at(.2, lambda: setattr(self.ipc, 'active', '0x30'))
        self.ipc.at(.3, lambda: self.appear('0x31', 'chrome-mail.google.com__-Default', focus=False))
        self.launched.clear()
        reply = self.send('open', recipe=recipe, workspace=2, bind=['0xb'], owned=['omarelay-acme'], focus='0xa')
        self.assertEqual((reply['result'], self.launched), ('opened', ['gmail.desktop', 'obsidian.desktop']))
        batch = next(i for i, entry in enumerate(self.ipc.log) if entry[0] == 'batch')
        self.assertEqual([e for e in self.ipc.log[:batch] if e[0] in ('focus', 'call')], back)
        # The click put the keyboard on an app that is now in the card, so it goes back once more.
        self.assertEqual((self.focusing(), self.ipc.active, reply['focus_returned']), (back * 2, '0xa', True))

    def test_open_gives_the_keyboard_back_from_a_window_that_maps_while_the_wait_reads(self):
        back = [('call', 'dispatch', setup.Unattended.focus_command('0xa'))]
        self.keep('acme', self.acme())
        for read in ('windows', 'data'):
            # The notes window maps and takes the keyboard while the windows, or
            # the keyboard, are being read. Either way it gives the keyboard back
            # during the wait, before the card is made.
            self.ipc = QuietIPC(); self.ipc.env = self.env; self.park(); self.launched.clear()
            def reading(*args, original=getattr(self.ipc, read), read=read):
                if (read == 'windows' or args == ('-j', 'activewindow')) and self.launched and '0x30' not in self.ipc.clients:
                    self.appear('0x30', 'obsidian')
                return original(*args)
            setattr(self.ipc, read, reading)
            reply = self.send('open', **self.opening())
            batch = next(i for i, entry in enumerate(self.ipc.log) if entry[0] == 'batch')
            self.assertEqual((reply['result'], [e for e in self.ipc.log[:batch] if e[0] in ('focus', 'call')]),
                             ('opened', back), read)
            self.assertEqual((self.focusing(), self.ipc.active, reply['focus_returned']), (back, '0xa', True))

    def test_open_focus_after_commit_never_fails_the_open(self):
        recipe = {'faces': [{'apps': [self.app('omarelay-acme', 'Workspace browser')], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0},
                            {'apps': [self.app('omarelay.terminal.acme', 'Workspace terminal')], 'axis': 'horizontal',
                             'ratios': [1.], 'focus': 0}], 'active': 0}
        def opened(prepare):
            # The browser is on the workspace with the keyboard, so the card's front face has it after the restore.
            self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
            self.ipc.clients['0xb']['workspace'] = {'id': 2, 'name': '2'}
            self.ipc.active = '0xb'
            prepare()
            reply = self.send('open', recipe=recipe, workspace=2, bind=['0xb', '0xc'], focus='0xa')
            self.assertEqual((reply['result'], self.ipc.snapshot['containers'][0]['faces']), ('opened', [['0xb'], ['0xc']]))
            return reply
        # It goes back to the caller's window, without moving the pointer.
        pointer = list(self.ipc.pointer)
        self.assertTrue(opened(lambda: None)['focus_returned'])
        self.assertEqual((self.ipc.active, self.ipc.pointer), ('0xa', pointer))
        self.assertEqual(self.focusing(), [('call', 'dispatch', setup.Unattended.focus_command('0xa'))])
        # A dispatch that fails, or a window that never takes the keyboard, leaves the card made.
        reply = opened(lambda: setattr(self.ipc, 'failing', setup.SetupError('Lua error: no window')))
        self.assertEqual((reply['focus_returned'], self.ipc.active), (False, '0xb'))
        self.assertLessEqual(self.ipc.now, .35)
        # The caller's window went to another workspace: nothing is sent.
        reply = opened(lambda: self.ipc.clients['0xa'].update(workspace={'id': 3, 'name': '3'}))
        self.assertEqual((reply['focus_returned'], self.focusing()), (False, []))

    def test_open_never_asks_or_notifies(self):
        self.park(); self.keep('acme', self.acme())
        self.arrivals['obsidian.desktop'] = ('0x30', 'obsidian', .2)
        spies = (patch.object(setup, 'Opening'), patch.object(setup, 'notify'), patch.object(setup.subprocess, 'Popen'),
                 patch.object(setup.subprocess, 'run'))
        with spies[0] as opening, spies[1] as notify, spies[2] as popen, spies[3] as run:
            self.assertEqual(self.send('open', **self.opening())['result'], 'opened')
            # A refused restore says so only in its reply.
            self.ipc = QuietIPC(); self.ipc.env = self.env; self.park(); self.ipc.refuse = REFUSED
            self.assertEqual(self.send('open', **self.opening(launch=False))['code'], 'refused')
        for spy in (opening, notify, popen, run): spy.assert_not_called()
        # Its menu answers nothing: any question would be a mistake in the code.
        menu = setup.Unattended(self.ipc, self.store).menu
        for ask in (lambda: menu.choose('Pick an app', []), lambda: menu.input('Name this card'),
                    lambda: menu.opening('acme', ['Obsidian'])):
            with self.assertRaises(RuntimeError): ask()

    def test_open_ignores_the_user_moving_around_during_a_launch(self):
        self.park(); self.keep('acme', self.acme())
        self.arrivals['obsidian.desktop'] = ('0x30', 'obsidian', .4)
        def wander(workspace, active):
            self.ipc.workspace, self.ipc.active = workspace, active
        self.ipc.clients['0xd']['workspace'] = {'id': 5, 'name': '5'}
        for when, workspace, active in ((.1, 5, '0xd'), (.2, 2, '0xa'), (.3, 5, '0xd')):
            self.ipc.at(when, lambda w=workspace, a=active: wander(w, a))
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], reply['workspace']['id']), ('opened', 2))
        self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xb'], ['0xc', '0x30']])
        self.assertEqual((self.ipc.workspace, self.focusing()), (5, []))
        self.assertGreaterEqual(self.ipc.now, .4)

    def test_open_reports_launch_failures_and_timeouts(self):
        self.park()
        recipe = self.acme()
        recipe['faces'][1]['apps'] += [self.app('chrome-mail.google.com__-Default', 'Gmail'), self.app('terminal', 'Console')]
        recipe['faces'][1]['ratios'] = [.4, .2, .2, .2]
        # Gmail exits with an error and no window; the terminal's launcher changed on disk.
        self.exits['gmail.desktop'] = 1
        real = self.launch
        def launch(entry):
            if entry.id == 'terminal.desktop': raise setup.SetupError('An app launcher changed. Open Saved cards again.')
            return real(entry)
        with patch.object(setup.DesktopApps, 'launch', side_effect=launch):
            reply = self.send('open', recipe=recipe, workspace=2, bind=['0xb', '0xc'], owned=['omarelay-acme'], timeout_ms=1000)
        self.assertEqual(reply['result'], 'opened')
        self.assertEqual([s.get('missing') for s in reply['slots'][1]], [None, 'timeout', 'launch_failed', 'launch_failed'])
        # Only the apps that started are reported, without a window.
        self.assertEqual([(row['desktop_id'], row['address']) for row in reply['launched']],
                         [('obsidian.desktop', None), ('gmail.desktop', None)])
        self.assertTrue(1 <= self.ipc.now < 1.1, self.ipc.now)
        self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xb'], ['0xc']])
        self.assertEqual(self.ipc.snapshot['containers'][0]['layouts'][1]['ratios'], [1.])

    def test_open_with_an_empty_face_is_incomplete_without_mutation_and_lists_launched_apps(self):
        self.park(); self.keep('acme', self.acme())
        reply = self.send('open', **self.opening(bind=['0xb'], timeout_ms=1000))
        self.assertEqual((reply['code'], reply['labels']), ('incomplete', ['Workspace terminal', 'Obsidian']))
        self.assertEqual(reply['launched'], [{'class': 'obsidian', 'initial_class': 'obsidian', 'wm_class': '',
                                              'desktop_id': 'obsidian.desktop', 'address': None}])
        self.assertEqual([[s.get('missing') for s in face] for face in reply['slots']], [[None], ['owned', 'timeout']])
        self.assertEqual(self.ipc.mutations, [])
        # A face that nothing could fill stops the open before anything starts.
        self.launched.clear(); self.ipc.now = 0
        reply = self.send('open', **self.opening(bind=['0xc']))
        self.assertEqual((reply['code'], reply['labels'], reply['launched']), ('incomplete', ['Workspace browser'], []))
        self.assertEqual((self.launched, self.ipc.now, self.ipc.mutations), ([], 0, []))

    def rollback_world(self):
        """The browser floats on special:park, the terminal is on workspace 3 and the notes float on workspace 2."""
        self.park(); self.keep('acme', self.acme())
        clients = self.ipc.clients
        clients['0xb'].update(floating=True, at=[300, 200], size=[900, 650])
        clients['0xc']['workspace'] = {'id': 3, 'name': '3'}
        clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian', 'floating': True, 'at': [40, 50], 'size': [500, 400]})
        return deepcopy(clients)

    def test_open_rolls_back_imports_including_special_origins_and_floats_when_restore_is_refused(self):
        before = self.rollback_world(); self.ipc.refuse = REFUSED
        reply = self.send('open', **self.opening(bind=['0xb', '0xc', '0xd']))
        self.assertEqual((reply['code'], reply['launched'], reply['labels']), ('refused', [], []))
        self.assertEqual((self.ipc.clients, self.ipc.snapshot['containers']), (before, []))
        steps = [m[:2] if m[0] != 'action' else ('action', m[1].split()[0]) for m in self.ipc.mutations]
        self.assertEqual(steps, [('action', 'reserve'), ('action', 'reserve'), ('tile', '0xb'), ('tile', '0xd'), ('batch', steps[4][1]),
                                 ('move', '0xc'), ('move', '0xb'), ('restore_float', '0xd'), ('restore_float', '0xb'),
                                 ('action', 'unreserve'), ('action', 'unreserve')])
        self.assertIn(('move', '0xb', 'special:park'), self.ipc.mutations)
        self.assertEqual(self.focusing(), [])

    def test_open_reports_rollback_failed_with_stranded_addresses(self):
        self.rollback_world(); self.ipc.refuse = REFUSED; self.ipc.stuck = {'0xc'}
        reply = self.send('open', **self.opening(bind=['0xb', '0xc', '0xd']))
        self.assertEqual((reply['code'], reply['stranded'], reply['launched']), ('rollback_failed', ['0xc'], []))
        self.assertEqual(self.ipc.clients['0xb']['workspace']['name'], 'special:park')
        self.assertTrue(self.ipc.clients['0xb']['floating'] and self.ipc.clients['0xd']['floating'])
        self.assertNotIn('could not move', json.dumps(reply))

    def test_open_trusts_status_when_the_batch_reply_is_lost(self):
        self.park(); self.keep('acme', self.acme()); self.ipc.lost = 'after'
        reply = self.send('open', **self.opening(launch=False))
        self.assertEqual((reply['result'], reply['card']), ('opened', 10))
        self.assertFalse(any(m[0] in ('move', 'restore_float') for m in self.ipc.mutations))
        # A request that never reached Hyprland moved nothing; the reply says so.
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park(); self.ipc.lost = 'before'
        reply = self.send('open', **self.opening(launch=False))
        self.assertEqual((reply['code'], self.ipc.snapshot['containers']), ('hyprland', []))
        self.assertEqual({self.ipc.clients[a]['workspace']['name'] for a in ('0xb', '0xc')}, {'special:park'})

    def test_open_maps_a_busy_restore_to_busy(self):
        before = self.rollback_world(); self.ipc.refuse = BUSY
        reply = self.send('open', **self.opening(bind=['0xb', '0xc', '0xd']))
        self.assertEqual((reply['code'], reply['message']), ('busy', setup.Unfinished.MESSAGES['busy']))
        self.assertEqual(self.ipc.clients, before)

    def test_open_maps_ipc_failure_to_hyprland(self):
        self.keep('acme', self.acme())
        # The real Hyprctl, whose hyprctl fails, times out or is missing.
        ipc, secret = setup.Hyprctl(self.env), 'Lua error: /home/someone/.config/hypr/secret.lua:9'
        request = json.dumps({'protocol': 1, 'action': 'open', **self.opening()})
        for failure in (subprocess.CompletedProcess([], 7, 'error: ' + secret, ''), subprocess.TimeoutExpired('hyprctl', 8),
                        FileNotFoundError(2, secret)):
            run = patch.object(setup.subprocess, 'run', **({'return_value': failure} if isinstance(failure, subprocess.CompletedProcess)
                                                         else {'side_effect': failure}))
            with self.subTest(failure=type(failure).__name__), run as called:
                reply, code = control.run_unattended(request, ipc, self.env)
                self.assertEqual((code, reply['code'], reply['message'], reply['launched']),
                                 (1, 'hyprland', setup.Unfinished.MESSAGES['hyprland'], []))
                self.assertNotIn('secret', json.dumps(reply))
                self.assertEqual(called.call_args.args[0][0], 'hyprctl')
        self.assertEqual(self.launched, [])

    def test_open_and_save_without_a_core_are_unavailable(self):
        # Hyprland answers, but no Hyprflip core is loaded: status replies "unknown request" with exit 0.
        # A caller waits for another core on unavailable; it tries again soon only on hyprland.
        self.keep('acme', self.acme())
        ipc = setup.Hyprctl(self.env)
        replies = {('hyprflip', 'status'): 'unknown request', ('-j', 'activeworkspace'): '{"id": 2}',
                   ('-j', 'activewindow'): '{"address": "0xa"}', ('-j', 'clients'): '[]'}
        def hyprctl(command, **kwargs): return subprocess.CompletedProcess(command, 0, replies[tuple(command[1:])] + '\n', '')
        unreachable = subprocess.CompletedProcess(['hyprctl'], 4, "Couldn't connect to /run/user/1000/hypr/x/.socket.sock. (4)\n", '')
        for run, code in (({'side_effect': hyprctl}, 'unavailable'), ({'return_value': unreachable}, 'hyprland')):
            for action, fields in (('open', self.opening()), ('save', self.saving())):
                with self.subTest(action=action, code=code), patch.object(setup.subprocess, 'run', **run):
                    reply, exit_code = control.run_unattended(json.dumps({'protocol': 1, 'action': action, **fields}), ipc, self.env)
                    self.assertEqual((exit_code, reply['code'], reply['message'], reply['launched']),
                                     (1, code, setup.Unfinished.MESSAGES[code], []))
        with patch.object(setup.subprocess, 'run', side_effect=hyprctl):
            reply, exit_code = control.run_unattended(json.dumps({'protocol': 1, 'action': 'capabilities'}), ipc, self.env)
        self.assertEqual((exit_code, reply['core']), (0, False))
        self.assertEqual(self.launched, [])

    def test_open_named_reports_not_found_and_unreadable(self):
        self.park(); self.keep('Notes', self.recipe())
        self.assertEqual(self.send('open', **self.opening())['code'], 'not_found')
        Path(self.store).write_text('{"version":1,"cards":{"acme":')
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['code'], reply['launched']), ('store_unreadable', []))
        self.assertNotIn(self.store, json.dumps(reply))
        self.assertEqual(Path(self.store).read_text(), '{"version":1,"cards":{"acme":')
        self.assertEqual((self.ipc.mutations, self.launched), ([], []))

    def test_open_commit_reports_conflict_and_changed(self):
        def changed_store():
            recipe = self.acme(); recipe['faces'][1]['ratios'] = [.5, .5]
            setup.RecipeStore(path=self.store, titles=False).change({'acme': self.acme()}, {'acme': recipe})
        def new_pid(): self.ipc.clients['0xc']['pid'] = 4242
        def moved(): self.ipc.clients['0xb']['workspace'] = {'id': 3, 'name': '3'}
        for change, code in ((changed_store, 'conflict'), (new_pid, 'changed'), (moved, 'changed')):
            with self.subTest(change=change.__name__):
                Path(self.store).unlink(missing_ok=True)
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.park(); self.keep('acme', self.acme())
                self.arrivals['obsidian.desktop'] = ('0x30', 'obsidian', .2)
                self.ipc.at(.1, change)
                reply = self.send('open', **self.opening())
                self.assertEqual(reply['code'], code)
                self.assertEqual([(row['desktop_id'], row['address']) for row in reply['launched']], [('obsidian.desktop', '0x30')])
                # Only the keyboard came back from the new window; nothing moved.
                self.assertEqual([m for m in self.ipc.mutations if m[0] != 'call'], [])
        self.assertEqual(reply['labels'], ['omarelay-acme'])

    def test_open_remembers_launched_desktop_ids(self):
        # The notes slot has no launcher yet; obsidian.desktop is found by its class.
        self.park()
        recipe = self.acme(); del recipe['faces'][1]['apps'][1]['desktop_id']
        recipe['faces'][1]['apps'][1]['label'] = 'obsidian'
        self.keep('acme', recipe)
        self.arrivals['obsidian.desktop'] = ('0x30', 'obsidian', .2)
        reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], reply['remembered']), ('opened', True))
        remembered = deepcopy(recipe); remembered['faces'][1]['apps'][1]['desktop_id'] = 'obsidian.desktop'
        self.assertEqual(self.stored()['acme'], remembered)
        self.assertEqual(reply['token'], setup.digest(self.stored()['acme']))
        self.assertEqual(reply['token'], self.send('list', store=self.store)['cards']['acme']['token'])
        # A write that fails leaves the open made, and says so.
        Path(self.store).unlink(); self.keep('acme', recipe)
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        with patch.object(setup.RecipeStore, 'change', side_effect=OSError(28, 'No space left on device')):
            reply = self.send('open', **self.opening())
        self.assertEqual((reply['result'], reply['remembered'], reply['token']), ('opened', False, setup.digest(recipe)))
        self.assertEqual(self.stored()['acme'], recipe)
        # Without a launch there is nothing to remember.
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        self.assertNotIn('remembered', self.send('open', **self.opening(launch=False)))

    def test_open_cancelled_during_wait_lock_wait_and_before_batch_moves_nothing(self):
        menus = setup.Request(Path(self.env['XDG_RUNTIME_DIR']), 'unattended-test')
        holder = menus.lock.open('a'); self.addCleanup(holder.close)
        def stop(): control.interrupted = True
        def check(reply, launched):
            self.assertEqual((reply['code'], reply['message']), ('cancelled', setup.Unfinished.MESSAGES['cancelled']))
            self.assertEqual([row['desktop_id'] for row in reply['launched']], launched)
            self.assertFalse(any(m[0] in ('batch', 'move') for m in self.ipc.mutations))
        taken, exclusive = [], setup.Request.exclusive
        @contextmanager
        def signalled(request, timeout=None, cancelled=None):
            # The signal comes just as the commit takes the lock.
            with exclusive(request, timeout, cancelled):
                taken.append(timeout)
                if len(taken) == 2: stop()
                yield
        for case in ('checks', 'wait', 'first lock', 'commit lock', 'commit lock taken', 'before the batch'):
            with self.subTest(case=case), patch.object(control, 'interrupted', False):
                Path(self.store).unlink(missing_ok=True)
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.park(); self.keep('acme', self.acme())
                self.arrivals['obsidian.desktop'] = ('0x30', 'obsidian', .2)
                self.launched.clear()
                lock = patch.object(setup.Request, 'exclusive', signalled) if case == 'commit lock taken' else nullcontext()
                if case == 'checks':
                    # The flag comes while the request is checked, under the first lock: nothing starts.
                    def checking(*args, data=self.ipc.data):
                        if args == ('-j', 'workspaces'): stop()
                        return data(*args)
                    self.ipc.data = checking
                elif case == 'wait':
                    self.ipc.at(.1, stop)
                elif case == 'first lock':
                    fcntl.flock(holder, fcntl.LOCK_EX); self.ipc.at(.1, stop)
                elif case == 'commit lock':
                    self.ipc.at(.1, lambda: fcntl.flock(holder, fcntl.LOCK_EX)); self.ipc.at(.3, stop)
                elif case == 'before the batch':
                    # The flag comes while an app is tiled for the card: it floats again.
                    self.ipc.clients['0xb']['floating'] = True
                    tile = self.ipc.tile
                    def tiled(window): tile(window); stop()
                    self.ipc.tile = tiled
                with lock: reply = self.send('open', **self.opening(launch=case != 'first lock'))
                check(reply, [] if case in ('checks', 'first lock') else ['obsidian.desktop'])
                if case == 'checks': self.assertEqual((self.launched, self.ipc.mutations), ([], []))
                if case == 'first lock': self.assertEqual(self.ipc.log, [])
                if case.startswith('commit'): self.assertEqual([m for m in self.ipc.mutations if m[0] != 'call'], [])
                if case == 'before the batch':
                    self.assertEqual([m[0] for m in self.ipc.mutations if m[0] != 'call'], ['action', 'tile', 'restore_float', 'action'])
                    self.assertTrue(self.ipc.clients['0xb']['floating'])
                fcntl.flock(holder, fcntl.LOCK_UN)

    def test_open_cancelled_after_the_batch_is_opened(self):
        self.park(); self.keep('acme', self.acme())
        with patch.object(control, 'interrupted', False):
            self.ipc.after_batch = lambda: setattr(control, 'interrupted', True)
            reply = self.send('open', **self.opening(launch=False))
            self.assertTrue(control.interrupted)
        self.assertEqual((reply['result'], self.ipc.snapshot['containers'][0]['faces']), ('opened', [['0xb'], ['0xc']]))

    def test_open_refuses_hy3_non_dwindle_fullscreen_and_bad_workspaces_before_any_mutation(self):
        self.keep('acme', self.acme())
        def refused(code, **fields):
            self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
            prepare = fields.pop('prepare', lambda: None); prepare()
            reply = self.send('open', **self.opening(**fields))
            self.assertEqual((reply['code'], reply['launched']), (code, []))
            self.assertEqual((self.ipc.mutations, self.launched), ([], []))
            return reply
        for layout in ('hy3', 'master', 'scrolling'):
            refused('unsupported_workspace', prepare=lambda layout=layout: setattr(self.ipc, 'layout', layout))
        refused('unsupported_workspace', workspace=7)
        for workspace in (0, -1, 2**31, '2', 2.0, True, None):
            refused('unsupported_workspace', workspace=workspace)
            self.assertEqual(self.ipc.log, [])
        refused('fullscreen', prepare=lambda: self.ipc.clients['0xd'].update(fullscreen=2))
        refused('unavailable', prepare=lambda: self.ipc.snapshot.pop('card_ungroup'))
        refused('unavailable', prepare=lambda: self.ipc.snapshot.update(native_cards=False))

    def test_open_inline_recipe_is_validated_never_stored_and_refuses_titles_before_ipc(self):
        self.park()
        titled, broken = self.acme('Inbox'), self.acme()
        broken['faces'][1]['ratios'] = [.6, .6]
        for recipe in (titled, broken, {'faces': [], 'active': 0}, 'acme', None):
            with self.subTest(recipe=recipe):
                self.assertEqual(self.send('open', recipe=recipe, workspace=2, bind=['0xb', '0xc'])['code'], 'invalid_request')
        both = self.send('open', **self.opening(recipe=self.acme()))
        neither = self.send('open', workspace=2, bind=['0xb', '0xc'])
        unstored = self.send('open', name='acme', workspace=2)
        self.assertEqual({both['code'], neither['code'], unstored['code']}, {'invalid_request'})
        self.assertEqual(self.ipc.log, [])
        reply = self.send('open', recipe=self.acme(), workspace=2, bind=['0xb', '0xc'], launch=False)
        self.assertEqual((reply['result'], reply['token']), ('opened', None))
        self.assertNotIn('remembered', reply)
        self.assertEqual(list(self.store_dir.iterdir()), [])

    def test_open_refuses_more_than_ten_bound_windows_and_carded_bound_windows(self):
        self.park(); self.keep('acme', self.acme())
        many = [hex(0x100 + i) for i in range(11)]
        for bind in (many, ['0xb', '0xb'], ['0xZZ'], ['address:0xb'], [11], '0xb', ['0x' + 'f' * 17]):
            with self.subTest(bind=bind):
                self.assertEqual(self.send('open', **self.opening(bind=bind))['code'], 'invalid_request')
        self.assertEqual(self.ipc.log, [])
        self.ipc.clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian'})
        for setting in ('card', 'pair', 'group'):
            with self.subTest(setting=setting):
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
                self.ipc.clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian'})
                if setting == 'card': self.ipc.add_card([['0xa'], ['0xd']])
                elif setting == 'pair': self.ipc.snapshot['pairs'] = [{'id': 4, 'front': '0xa', 'back': '0xd'}]
                else: self.ipc.clients['0xd']['grouped'] = ['0xa', '0xd']
                before = deepcopy(self.ipc.snapshot)
                reply = self.send('open', **self.opening(bind=['0xb', '0xc', '0xd']))
                self.assertEqual((reply['code'], reply['labels']), ('in_card', ['obsidian']))
                self.assertEqual((self.ipc.snapshot, self.ipc.mutations), (before, []))
        # A window that closed is a change, as for the menus.
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        self.assertEqual(self.send('open', **self.opening(bind=['0xb', '0xc', '0x99']))['code'], 'changed')

    def test_open_binds_only_windows_that_can_go_back_where_they_were(self):
        # A refused card sends each app back with Hyprctl.move: to a numbered workspace, or to a special
        # one by a plain name. An app on a named workspace, or on a special one with a space in its
        # name, could not go back, so it is never taken.
        self.keep('acme', self.acme())
        for place in ({'id': -1337, 'name': 'parked'}, {'id': -97, 'name': 'special:side panel'}):
            with self.subTest(place=place):
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
                self.ipc.clients['0xc']['workspace'] = place
                reply = self.send('open', **self.opening())
                self.assertEqual((reply['code'], reply['launched'], self.ipc.mutations, self.launched), ('changed', [], [], []))
                self.assertEqual(self.ipc.clients['0xc']['workspace'], place)

    def test_open_save_and_delete_check_owned_timeout_and_lock_at_their_bounds(self):
        # owned holds up to 8 classes, timeout_ms is 1 to 60 seconds and lock_ms up to 30 seconds.
        self.park(); self.keep('acme', self.acme())
        eight = ['omarelay-acme', 'omarelay.terminal.acme'] + [f'tool-{i}' for i in range(6)]
        for fields in ({'owned': eight + ['tool-6']}, {'owned': ['']}, {'owned': ['x' * 513]}, {'owned': 'omarelay-acme'},
                       {'timeout_ms': 999}, {'timeout_ms': 60001}, {'timeout_ms': 1500.}, {'lock_ms': -1}, {'lock_ms': 30001},
                       {'lock_ms': True}):
            with self.subTest(fields=fields):
                self.assertEqual(self.send('open', **self.opening(**fields))['code'], 'invalid_request')
                if 'timeout_ms' not in fields:
                    self.assertEqual(self.send('save', **self.saving(**fields))['code'], 'invalid_request')
        for lock_ms in (-1, 30001):
            self.assertEqual(self.send('delete', store=self.store, name='acme', token='0' * 64, lock_ms=lock_ms)['code'],
                             'invalid_request')
        self.assertEqual(self.ipc.log, [])
        # The bounds themselves are taken.
        for fields in ({'owned': eight, 'timeout_ms': 1000, 'lock_ms': 0}, {'owned': [], 'timeout_ms': 60000, 'lock_ms': 30000}):
            with self.subTest(fields=fields):
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
                self.assertEqual(self.send('open', **self.opening(launch=False, **fields))['result'], 'opened')

    def test_open_reports_unused_bound_windows(self):
        self.park(); self.keep('acme', self.acme())
        reply = self.send('open', **self.opening(bind=['0xd', '0xb', '0xc'], launch=False))
        self.assertEqual((reply['result'], reply['unused']), ('opened', ['0xd']))
        self.assertEqual(self.ipc.snapshot['containers'][0]['faces'], [['0xb'], ['0xc']])
        self.assertFalse(any('0xd' in command for command in self.batches()[0]))
        self.assertEqual(self.ipc.clients['0xd']['workspace'], {'id': 2, 'name': '2'})

    def test_open_moves_each_face_focus_to_the_nearest_slot_left(self):
        self.park()
        self.ipc.clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian'})
        # The front face's focus is on mail, which is not open: the notes after it are nearer than the
        # browser before it. On the back face, the focused terminal is all that is left.
        recipe = {'faces': [{'apps': [self.app('omarelay-acme', 'Workspace browser'), self.app('slack', 'Slack'),
                                      self.app('mail', 'Mail'), self.app('obsidian', 'Obsidian')],
                             'axis': 'horizontal', 'ratios': [.4, .1, .2, .3], 'focus': 2},
                            {'apps': [self.app('chat', 'Chat'), self.app('omarelay.terminal.acme', 'Workspace terminal')],
                             'axis': 'vertical', 'ratios': [.5, .5], 'focus': 1}], 'active': 0}
        reply = self.send('open', recipe=recipe, workspace=2, bind=['0xb', '0xc', '0xd'], launch=False)
        self.assertEqual([[s.get('missing') for s in face] for face in reply['slots']],
                         [[None, 'not_launched', 'not_launched', None], ['not_launched', None]])
        front, back = self.ipc.snapshot['containers'][0]['layouts']
        self.assertEqual((front['focused'], back['focused']), ('0xd', '0xc'))
        for share, wanted in zip(front['ratios'], [4 / 7, 3 / 7]): self.assertAlmostEqual(share, wanted)

    def test_box_is_the_front_tile_or_the_free_area_and_a_floating_card_is_centred(self):
        flow, windows = setup.Unattended(self.ipc, None), self.ipc.windows()
        arrangement = {'faces': [{'windows': ['0xb'], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0},
                                 {'windows': ['0xc'], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0}], 'active': 0}
        # A tiled card takes its front app's tile when that app is on the workspace already.
        self.assertEqual(flow.box(arrangement, False, 2, windows), [*windows['0xb']['at'], *windows['0xb']['size']])
        # From elsewhere, it takes the screen's free area: 4K at scale 1.5 below a 40 px bar.
        windows['0xb']['workspace'] = {'id': -98, 'name': 'special:park'}
        self.assertEqual(flow.box(arrangement, False, 2, windows), [0, 40, 2560, 1400])
        # A screen turned a quarter is as tall as it was wide, here with a 26 px bar on top.
        rotated = [{'id': 0, 'x': 3840, 'y': 0, 'width': 3840, 'height': 2160, 'scale': 1.5, 'transform': 1,
                    'reserved': [0, 26, 0, 0]}]
        data = self.ipc.data
        with patch.object(self.ipc, 'data', side_effect=lambda *args: rotated if args == ('-j', 'monitors') else data(*args)):
            self.assertEqual(flow.box(arrangement, False, 2, windows), [3840, 26, 1440, 2534])
        # A floating card keeps its front app's size, centred in the free area, wherever that app is.
        windows['0xb'].update(workspace={'id': 2, 'name': '2'}, size=[900, 650])
        self.assertEqual(flow.box(arrangement, True, 2, windows), [830, 415, 900, 650])

    def test_restore_line_words_an_arrangement_as_the_core_reads_it(self):
        arrangement = {'faces': [{'windows': ['0xb'], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0},
                                 {'windows': ['0xc', '0xd'], 'axis': 'vertical', 'ratios': [.6, .4], 'focus': 1}], 'active': 1}
        line = setup.Unattended.restore_line
        self.assertEqual(line(arrangement, [830., 415., 900, 650], True),
                         'restore quiet floating 1 0 830 415 900 650 front horizontal 0xb 0xb:1 back vertical 0xd 0xc:0.6 0xd:0.4')
        # Nothing else is ever sent: a box of anything but finite numbers, or anything but an address.
        for box in ([0, 0, float('nan'), 650], [0, 0, '900', 650], [0, 0, True, 650]):
            with self.subTest(box=box), self.assertRaises(setup.SetupError): line(arrangement, box, False)
        arrangement['faces'][1]['windows'][0] = '0xc ; dispatch exit'
        with self.assertRaises(setup.SetupError): line(arrangement, [0, 0, 900, 650], False)

    def test_open_waits_for_the_menu_lock_but_never_supersedes_a_menu(self):
        self.park(); self.keep('acme', self.acme())
        menus = setup.Request(Path(self.env['XDG_RUNTIME_DIR']), 'unattended-test')
        # A picker waits for an answer: its request is current and it holds the lock.
        menus.current.write_text('picker-token')
        holder = menus.lock.open('a'); self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        self.ipc.at(.2, lambda: fcntl.flock(holder, fcntl.LOCK_UN))
        reply = self.send('open', **self.opening(launch=False, lock_ms=1000))
        self.assertEqual(reply['result'], 'opened')
        self.assertTrue(.2 <= self.ipc.now < .3, self.ipc.now)
        fcntl.flock(holder, fcntl.LOCK_EX)
        self.ipc = QuietIPC(); self.ipc.env = self.env; self.park()
        reply = self.send('open', **self.opening(launch=False, lock_ms=300))
        self.assertEqual((reply['code'], self.ipc.log), ('busy', []))
        self.assertTrue(.3 <= self.ipc.now < .4, self.ipc.now)
        self.assertEqual(menus.current.read_text(), 'picker-token')

    def test_no_window_title_reaches_a_command(self):
        self.park()
        titles = {'0xa': 'Herdr — $(touch /tmp/pwned)', '0xb': 'Inbox; hyprctl dispatch exit', '0xc': "it's \"quoted\" `x`",
                  '0xd': 'Notes \\ [[ ]] ; dispatch'}
        for address, title in titles.items(): self.ipc.clients[address]['title'] = title
        self.ipc.clients['0xd'].update({'class': 'obsidian', 'initialClass': 'obsidian', 'workspace': {'id': 3, 'name': '3'}})
        self.keep('acme', self.acme())
        opened = self.send('open', **self.opening(bind=['0xb', '0xc', '0xd']))
        saved = self.send('save', store=self.store, name='acme', card=opened['card'], members=['0xb', '0xc', '0xd'],
                         previous=opened['token'])
        self.assertEqual((opened['result'], saved['result']), ('opened', 'saved'))
        sent = json.dumps(self.ipc.log)
        replies, kept = json.dumps([opened, saved]), Path(self.store).read_text()
        for title in titles.values():
            for part in ('pwned', 'Inbox', 'quoted', 'Notes'):
                if part in title:
                    self.assertNotIn(part, sent); self.assertNotIn(part, replies); self.assertNotIn(part, kept)

    def test_give_back_sends_nothing_to_the_active_window_and_otherwise_one_focus_without_a_warp(self):
        flow, pointer = setup.Unattended(self.ipc, None), list(self.ipc.pointer)
        # Any focus of the window that has the keyboard would warp the pointer, so none is sent.
        self.assertTrue(flow.give_back('0xb'))
        self.assertEqual(self.focusing(), [])
        self.assertTrue(flow.give_back('0xa'))
        self.assertEqual(self.focusing(), [('call', 'dispatch', setup.Unattended.focus_command('0xa'))])
        self.assertEqual((self.ipc.active, self.ipc.pointer), ('0xa', pointer))
        self.assertEqual(setup.Unattended.focus_command('0x5d'),
                         'function() local focus = hl.dsp.focus({ window = "address:0x5d" }) '
                         'local was = hl.get_config("cursor.no_warps") == true hl.config({ cursor = { no_warps = true } }) '
                         'local ok, err = pcall(hl.dispatch, focus) hl.config({ cursor = { no_warps = was } }) '
                         'if not ok then error(err) end end')
        self.assertNotIn(';', setup.Unattended.focus_command('0x5d'))
        # It waits at most 300 ms for the keyboard, and never raises.
        self.ipc.log.clear()
        self.ipc.failing = setup.SetupError('Lua error: the window is gone')
        start = self.ipc.now
        self.assertFalse(flow.give_back('0xc'))
        self.assertTrue(.3 <= self.ipc.now - start < .35)
        self.assertEqual(len(self.focusing()), 1)
        with patch.object(self.ipc, 'data', side_effect=OSError('hyprctl')):
            self.assertFalse(flow.give_back('0xc'))
        self.ipc.log.clear()
        for address in (None, '0xa ; dispatch exit', 'address:0xa', 7):
            self.assertFalse(flow.give_back(address))
        self.assertEqual(self.focusing(), [])

    # Saving.

    def carded(self, floating=False):
        """A live card, id 10: the workspace browser in front, its terminal and the user's notes behind.

        Their titles are never kept.
        """
        clients = self.ipc.clients
        for address, name, title in (('0xb', 'omarelay-acme', 'Inbox – private@example.com'),
                                     ('0xc', 'omarelay.terminal.acme', '~/secret-project'), ('0xd', 'obsidian', 'Diary')):
            clients[address].update({'class': name, 'initialClass': name, 'title': title})
        layouts = [dict(axis='horizontal', focused='0xb', ratios=[1.]), dict(axis='vertical', focused='0xc', ratios=[.6, .4])]
        return self.ipc.add_card([['0xb'], ['0xc', '0xd']], layouts=layouts, floating=floating)

    def saving(self, **fields):
        return {'store': self.store, 'name': 'acme', 'card': 10, 'members': ['0xb', '0xc', '0xd'], 'previous': None,
                'owned': ['omarelay-acme', 'omarelay.terminal.acme']} | fields

    def captured(self):
        """The definition the card above saves as: labels from the classes, a launcher for the notes alone."""
        return {'faces': [{'apps': [self.app('omarelay-acme', 'omarelay-acme')], 'axis': 'horizontal', 'ratios': [1.], 'focus': 0},
                          {'apps': [self.app('omarelay.terminal.acme', 'omarelay.terminal.acme'),
                                    self.app('obsidian', 'obsidian') | {'desktop_id': 'obsidian.desktop'}],
                           'axis': 'vertical', 'ratios': [.6, .4], 'focus': 0}], 'active': 0}

    def close(self, address):
        """An app of the card closes: hyprflip shares its face out evenly and focuses the first app left."""
        card = self.ipc.snapshot['containers'][0]
        for face, layout in zip(card['faces'], card['layouts']):
            if address in face:
                face.remove(address)
                layout.update(ratios=[1 / len(face)] * len(face), focused=face[0])
        del self.ipc.clients[address]

    def test_save_captures_a_live_card_by_id_without_focus_or_mutation(self):
        self.carded(); self.ipc.log.clear()
        reply = self.send('save', **self.saving())
        def slot(name, address, launcher=False):
            return {'class': name, 'initial_class': name, 'label': name, 'launcher': launcher, 'address': address}
        self.assertEqual(reply, {'protocol': 1, 'ok': True, 'result': 'saved', 'name': 'acme', 'token': setup.digest(self.captured()),
                                 'dropped': [], 'slots': [[slot('omarelay-acme', '0xb')],
                                                          [slot('omarelay.terminal.acme', '0xc'), slot('obsidian', '0xd', True)]]})
        self.assertEqual(self.stored(), {'acme': self.captured()})
        self.assertNotIn('private@example.com', Path(self.store).read_text())
        self.assertEqual((self.ipc.mutations, self.focusing()), ([], []))
        self.assertEqual({entry[0] for entry in self.ipc.log}, {'windows', 'status'})

    def test_save_works_on_a_parked_card(self):
        self.carded()
        self.assertEqual(self.ipc.action('card 10 workspace special:park silent'), 'ok: ok')
        self.ipc.mutations.clear()
        reply = self.send('save', **self.saving())
        self.assertEqual((reply['result'], self.stored()), ('saved', {'acme': self.captured()}))
        self.assertEqual(self.ipc.snapshot['containers'][0]['workspace']['name'], 'special:park')
        self.assertEqual((self.ipc.mutations, self.focusing()), ([], []))

    def test_save_refuses_unknown_ids_pairs_changed_members_and_fullscreen_cards(self):
        self.carded()
        self.ipc.snapshot['pairs'] = [{'id': 12, 'front': '0xa', 'back': '0xe'}]
        self.ipc.clients['0xe'] = window('0xe')
        hy3 = dict(deepcopy(self.ipc.snapshot['containers'][0]), id=13, native_group=False, faces=[['0xa'], ['0xe']])
        self.ipc.snapshot['containers'].append(hy3)
        for fields, code in (({'card': 99}, 'no_card'), ({'card': 12, 'members': ['0xa', '0xe']}, 'not_native'),
                             ({'card': 13, 'members': ['0xa', '0xe']}, 'not_native'),
                             ({'members': ['0xb', '0xc']}, 'changed'), ({'members': ['0xb', '0xc', '0xd', '0xa']}, 'changed'),
                             ({'card': 0}, 'invalid_request'), ({'card': True}, 'invalid_request'), ({'card': '10'}, 'invalid_request'),
                             ({'members': []}, 'invalid_request'), ({'members': ['0xb', '0xb']}, 'invalid_request')):
            with self.subTest(fields=fields):
                self.assertEqual(self.send('save', **self.saving(**fields))['code'], code)
        card = self.ipc.snapshot['containers'][0]
        card['fullscreen'] = True
        self.assertEqual(self.send('save', **self.saving())['code'], 'fullscreen')
        card['fullscreen'] = False; self.ipc.clients['0xd']['fullscreen'] = 1
        self.assertEqual(self.send('save', **self.saving())['code'], 'fullscreen')
        self.ipc.clients['0xd']['fullscreen'] = 0; del self.ipc.clients['0xd']
        self.assertEqual(self.send('save', **self.saving())['code'], 'changed')
        self.assertFalse(Path(self.store).exists())
        self.assertEqual(self.ipc.mutations, [])

    def test_save_previous_null_needs_absent_name_and_base_for_keep(self):
        self.carded()
        base = self.acme()
        self.assertEqual(self.send('save', **self.saving(keep=[{'face': 1, 'index': 1}]))['code'], 'invalid_request')
        self.assertEqual(self.send('save', **self.saving(base=self.acme('Inbox')))['code'], 'invalid_request')
        self.assertEqual(self.send('save', **self.saving(previous='0' * 64, base=base))['code'], 'invalid_request')
        for keep in ([{'face': 2, 'index': 0}], [{'face': 1, 'index': 5}], [{'face': 1}], [{'face': 1, 'index': 1, 'x': 0}],
                     [{'face': 1, 'index': 1}] * 2, {'face': 1, 'index': 1}):
            with self.subTest(keep=keep):
                self.assertEqual(self.send('save', **self.saving(keep=keep, base=base))['code'], 'invalid_request')
        # The base is only the reference for the kept apps; past its apps is a mistake.
        self.assertEqual(self.send('save', **self.saving(keep=[{'face': 0, 'index': 1}], base=base))['code'], 'invalid_request')
        self.assertFalse(Path(self.store).exists())
        # The notes closed after the default card opened: the definition keeps them.
        self.close('0xd')
        reply = self.send('save', **self.saving(members=['0xb', '0xc'], keep=[{'face': 1, 'index': 1}], base=base))
        self.assertEqual(reply['result'], 'saved')
        self.assertEqual([[s['address'] for s in face] for face in reply['slots']], [['0xb'], ['0xc', None]])
        self.assertEqual(self.stored()['acme']['faces'][1], base['faces'][1])
        again = self.send('save', **self.saving(members=['0xb', '0xc'], base=base))
        self.assertEqual((again['code'], self.stored()['acme']['faces'][1]), ('conflict', base['faces'][1]))

    def test_save_writes_a_new_name_even_when_its_base_is_what_the_card_shows(self):
        # A default card saved for the first time, as it opened: nothing is stored under the name yet.
        self.carded()
        reply = self.send('save', **self.saving(base=self.captured()))
        self.assertEqual((reply['result'], self.stored()), ('saved', {'acme': self.captured()}))
        self.assertEqual(reply['token'], setup.digest(self.stored()['acme']))

    def stored_reference(self, back, ratios, axis='vertical'):
        """A stored acme definition whose back face has these apps, and its token."""
        recipe = self.captured()
        recipe['faces'][1] = {'apps': back, 'axis': axis, 'ratios': ratios, 'focus': 0}
        self.keep('acme', recipe)
        return recipe, setup.digest(recipe)

    def test_save_keeps_closed_slots_with_their_share(self):
        self.carded()
        terminal, notes, foot = (self.app('omarelay.terminal.acme', 'omarelay.terminal.acme'),
                                 self.app('obsidian', 'obsidian') | {'desktop_id': 'obsidian.desktop'}, self.app('foot', 'Terminal'))
        reference, token = self.stored_reference([terminal, notes, foot], [.5, .3, .2])
        # The notes closed and the user resized what was left.
        card = self.ipc.snapshot['containers'][0]
        self.ipc.clients['0xd'].update({'class': 'foot', 'initialClass': 'foot'})
        card['layouts'][1].update(ratios=[.7, .3])
        reply = self.send('save', **self.saving(previous=token, keep=[{'face': 1, 'index': 1}]))
        self.assertEqual((reply['result'], reply['dropped']), ('saved', []))
        self.assertEqual([s['address'] for s in reply['slots'][1]], ['0xc', None, '0xd'])
        back = self.stored()['acme']['faces'][1]
        self.assertEqual(back['apps'], [terminal, notes, foot])
        for share, wanted in zip(back['ratios'], [.49, .3, .21]): self.assertAlmostEqual(share, wanted)
        self.assertEqual((back['axis'], back['focus']), ('vertical', 0))
        self.assertEqual(reply['token'], setup.digest(self.stored()['acme']))

    def test_save_keeps_a_face_that_only_lost_closed_apps_unchanged(self):
        self.carded()
        first = self.send('save', **self.saving())
        written = Path(self.store).stat().st_mtime_ns
        self.close('0xd')
        reply = self.send('save', **self.saving(members=['0xb', '0xc'], previous=first['token'], keep=[{'face': 1, 'index': 1}]))
        self.assertEqual((reply['result'], reply['token']), ('unchanged', first['token']))
        self.assertEqual([[s['address'] for s in face] for face in reply['slots']], [['0xb'], ['0xc', None]])
        self.assertEqual((self.stored(), Path(self.store).stat().st_mtime_ns), ({'acme': self.captured()}, written))

    def test_save_keeps_closed_apps_on_a_third_face(self):
        clients = self.ipc.clients
        clients['0xe'] = window('0xe', at=[1830, 0], size=[600, 700])
        for address, name in (('0xb', 'omarelay-acme'), ('0xc', 'omarelay.terminal.acme'), ('0xd', 'obsidian'), ('0xe', 'foot')):
            clients[address].update({'class': name, 'initialClass': name, 'title': ''})
        self.ipc.add_card([['0xb'], ['0xc'], ['0xd', '0xe']])
        members = ['0xb', '0xc', '0xd', '0xe']
        first = self.send('save', **self.saving(members=members))
        self.assertEqual((first['result'], len(self.stored()['acme']['faces'])), ('saved', 3))
        self.close('0xe')
        reply = self.send('save', **self.saving(members=members[:3], previous=first['token'], keep=[{'face': 2, 'index': 1}]))
        self.assertEqual((reply['result'], reply['dropped']), ('unchanged', []))
        self.assertEqual([[s['address'] for s in face] for face in reply['slots']], [['0xb'], ['0xc'], ['0xd', None]])
        # Faces run from 0 to 3; a face the saved card lacks is a mistake.
        for keep in ([{'face': 4, 'index': 0}], [{'face': 3, 'index': 0}]):
            with self.subTest(keep=keep):
                self.assertEqual(self.send('save', **self.saving(members=members[:3], previous=first['token'], keep=keep))['code'],
                                 'invalid_request')

    def test_save_kept_shares_summing_to_one_leave_live_apps_a_floor(self):
        self.carded()
        notes, diary = (self.app('obsidian', 'obsidian') | {'desktop_id': 'obsidian.desktop'}, self.app('diary', 'Diary'))
        reference, token = self.stored_reference([notes, diary], [.5, .5])
        # Both closed after the user added a terminal, which now has the face alone, side by side.
        card = self.ipc.snapshot['containers'][0]
        card['faces'][1] = ['0xd']; card['layouts'][1] = dict(axis='horizontal', focused='0xd', ratios=[1.])
        self.ipc.clients['0xd'].update({'class': 'foot', 'initialClass': 'foot'}); del self.ipc.clients['0xc']
        reply = self.send('save', **self.saving(members=['0xb', '0xd'], previous=token,
                                               keep=[{'face': 1, 'index': 0}, {'face': 1, 'index': 1}]))
        back = self.stored()['acme']['faces'][1]
        self.assertEqual((reply['result'], back['apps'][:2], back['apps'][2]['class']), ('saved', [notes, diary], 'foot'))
        for share, wanted in zip(back['ratios'], [.45, .45, .1]): self.assertAlmostEqual(share, wanted)
        self.assertAlmostEqual(sum(back['ratios']), 1, places=12)
        # A lone live app takes the axis the definition had.
        self.assertEqual((back['axis'], back['focus']), ('vertical', 2))

    def test_save_drops_kept_slots_beyond_max_panes_and_excludes_them_from_the_sum(self):
        self.carded(); self.ipc.snapshot['container_max_panes'] = 3
        terminal = self.app('omarelay.terminal.acme', 'omarelay.terminal.acme')
        kept = [self.app(name, name.title()) for name in ('notes', 'diary', 'slack')]
        reference, token = self.stored_reference([terminal, *kept], [.4, .2, .2, .2])
        # The three closed and the user added a terminal: there is room for one of them.
        self.ipc.clients['0xd'].update({'class': 'foot', 'initialClass': 'foot'})
        self.ipc.snapshot['containers'][0]['layouts'][1].update(ratios=[.5, .5])
        reply = self.send('save', **self.saving(previous=token, keep=[{'face': 1, 'index': i} for i in (3, 1, 2)]))
        self.assertEqual(reply['dropped'], [{'face': 1, 'index': 2}, {'face': 1, 'index': 3}])
        back = self.stored()['acme']['faces'][1]
        self.assertEqual([app['class'] for app in back['apps']], ['omarelay.terminal.acme', 'notes', 'foot'])
        for share, wanted in zip(back['ratios'], [.4, .2, .4]): self.assertAlmostEqual(share, wanted)
        self.assertEqual([s['address'] for s in reply['slots'][1]], ['0xc', None, '0xd'])

    def test_save_never_gives_owned_or_label_matched_apps_a_launcher(self):
        gmail = 'chrome-mail.google.com__-Default'
        self.carded()
        for address, name in (('0xc', 'omarelay-whatsapp-team'), ('0xd', 'kitty')):
            self.ipc.clients[address].update({'class': name, 'initialClass': name})
        self.ipc.clients['0xe'] = window('0xe', **{'class': gmail, 'initialClass': gmail, 'at': [0, 0], 'size': [600, 700]})
        card = self.ipc.snapshot['containers'][0]
        card['faces'][1].append('0xe'); card['layouts'][1]['ratios'] = [.4, .3, .3]
        # An older definition remembered a launcher for the owned browser.
        recipe = self.captured()
        recipe['faces'][0]['apps'][0]['desktop_id'] = 'browser.desktop'
        self.keep('acme', recipe)
        reply = self.send('save', **self.saving(members=['0xb', '0xc', '0xd', '0xe'], previous=setup.digest(recipe),
                                               owned=['omarelay-acme', 'omarelay-whatsapp-team']))
        apps = [app for face in self.stored()['acme']['faces'] for app in face['apps']]
        # The labels name installed launchers (WhatsApp, Terminal); only Gmail's class does.
        self.assertEqual([(app['label'], app.get('desktop_id')) for app in apps],
                         [('omarelay-acme', None), ('WhatsApp', None), ('Terminal', None), ('Gmail', 'gmail.desktop')])
        self.assertEqual([s['launcher'] for face in reply['slots'] for s in face], [False, False, False, True])

    def test_save_then_save_is_unchanged_and_list_tokens_equal_save_tokens(self):
        self.carded()
        first = self.send('save', **self.saving())
        listed = self.send('list', store=self.store)['cards']['acme']['token']
        self.assertEqual((first['token'], listed), (setup.digest(self.stored()['acme']), first['token']))
        created, recording = self.created()
        with recording: second = self.send('save', **self.saving(previous=first['token']))
        self.assertEqual((second['result'], second['token'], created), ('unchanged', first['token'], []))
        # A real change is saved against the token, and the new token lists too.
        self.ipc.snapshot['containers'][0]['layouts'][1]['ratios'] = [.5, .5]
        third = self.send('save', **self.saving(previous=first['token']))
        self.assertEqual((third['result'], self.send('list', store=self.store)['cards']['acme']['token']), ('saved', third['token']))
        self.assertNotEqual(third['token'], first['token'])

    def test_save_floating_override(self):
        for floating_card, override, expected in ((False, True, True), (True, False, None), (True, None, True), (False, None, None)):
            with self.subTest(card=floating_card, override=override):
                Path(self.store).unlink(missing_ok=True)
                self.ipc = QuietIPC(); self.ipc.env = self.env; self.carded(floating=floating_card)
                fields = {} if override is None else {'floating': override}
                self.assertEqual(self.send('save', **self.saving(**fields))['result'], 'saved')
                self.assertEqual(self.stored()['acme'].get('floating'), expected)
        self.assertEqual(self.send('save', **self.saving(floating='yes'))['code'], 'invalid_request')

    def test_save_reports_limit_and_stale_token(self):
        self.carded()
        cards = {f'Card {i}': self.recipe() for i in range(100)}
        Path(self.store).write_text(json.dumps({'version': 1, 'cards': cards}))
        before = Path(self.store).read_bytes()
        self.assertEqual(self.send('save', **self.saving())['code'], 'limit')
        self.assertEqual(Path(self.store).read_bytes(), before)
        # Replacing one of them is no new card.
        replaced = self.send('save', **self.saving(name='Card 7', previous=setup.digest(self.recipe())))
        self.assertEqual((replaced['result'], len(self.stored())), ('saved', 100))
        stale = self.send('save', **self.saving(name='Card 7', previous=setup.digest(self.recipe())))
        self.assertEqual((stale['code'], stale['launched']), ('conflict', []))
        self.assertEqual(self.send('save', **self.saving(name='Card 101', previous='f' * 64))['code'], 'conflict')

    def test_save_never_touches_the_user_library(self):
        self.carded()
        library = setup.RecipeStore(self.env)
        library.update('acme', self.recipe('Inbox'), None)
        before, written = library.path.read_bytes(), library.path.stat().st_mtime_ns
        self.assertEqual(self.send('save', **self.saving())['result'], 'saved')
        for path in (library.path, library.root / 'omarelay.json'):
            with self.subTest(path=path):
                self.assertEqual(self.send('save', **self.saving(store=str(path)))['code'], 'invalid_store')
        self.assertEqual((library.path.read_bytes(), library.path.stat().st_mtime_ns), (before, written))
        self.assertEqual(sorted(p.name for p in library.root.iterdir()), ['cards.json', 'cards.lock'])

    # The command line, as another program starts it.

    def tools(self):
        """A hyprctl stand-in that records each call and answers as a session with an odd core would."""
        tools = self.root / 'tools'
        if not tools.exists():
            tools.mkdir()
            (tools / 'hyprctl').write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$(dirname "$0")/hyprctl.log"\n'
                'case "$*" in\n'
                '  "-j activeworkspace") echo \'{"id": 2}\' ;;\n'
                '  "-j activewindow") echo \'{}\' ;;\n'
                '  "hyprflip status") cat "$(dirname "$0")/status.json" ;;\n'
                '  *) echo "unknown request"; exit 1 ;;\n'
                'esac\n')
            (tools / 'hyprctl').chmod(0o755)
            (tools / 'status.json').write_text('{}')
        return tools

    def cli(self, *arguments, drop=(), wait=True, **options):
        """control.py unattended in a process of its own, with its stdin closed. It can reach no
        session: a made-up instance, this test's directories and the recording hyprctl first on PATH.
        Without wait, the process comes back while it runs."""
        env = {'PATH': f'{self.tools()}:{os.environ["PATH"]}', **self.env, 'HYPRLAND_INSTANCE_SIGNATURE': 'unattended-cli-bogus'}
        for name in drop: env.pop(name)
        if 'stdout' not in options: options.update(stdout=subprocess.PIPE)
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/control.py'), 'unattended', *arguments]
        options.update(env=env, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=lambda: os.close(0))
        return subprocess.run(command, timeout=60, **options) if wait else subprocess.Popen(command, **options)

    @staticmethod
    def opened(pid):
        """The files a running process has open, as far as they can still be read."""
        paths = set()
        try:
            for descriptor in Path(f'/proc/{pid}/fd').iterdir():
                try: paths.add(os.readlink(descriptor))
                except OSError: pass  # Closed meanwhile.
        except OSError:
            pass  # The process is gone.
        return paths

    def answer(self, result, code):
        """The one line a run printed, with its exit code and nothing on stderr."""
        self.assertEqual((result.returncode, result.stderr), (code, b''))
        self.assertTrue(result.stdout.endswith(b'\n') and result.stdout.count(b'\n') == 1, result.stdout)
        reply = json.loads(result.stdout)
        self.assertEqual((reply['protocol'], reply['ok']), (1, code == 0))
        return reply

    def test_cli_prints_one_json_line_with_exit_codes_and_never_reads_stdin(self):
        self.keep('acme', self.acme())
        listing = json.dumps({'protocol': 1, 'action': 'list', 'store': self.store})
        reply = self.answer(self.cli('--request', listing), 0)
        self.assertEqual((reply['result'], list(reply['cards'])), ('list', ['acme']))
        for request, code in ((json.dumps({'protocol': 1, 'action': 'list', 'store': 'cards.json'}), 'invalid_store'),
                              ('{"protocol": 1, "action": "list", ', 'invalid_request'),
                              (listing + ' ' * 65536, 'invalid_request'),
                              (json.dumps({'protocol': 2, 'action': 'list', 'store': self.store}), 'invalid_request'),
                              ('[' * 5000 + ']' * 5000, 'invalid_request'), ('', 'invalid_request')):
            with self.subTest(request=request[:40]):
                reply = self.answer(self.cli('--request', request), 1)
                self.assertEqual((reply['code'], reply['launched']), (code, []))
        # Without --request there is nothing to do; a helper without this command is a usage error.
        self.assertEqual(self.answer(self.cli(), 1)['code'], 'invalid_request')
        usage = self.cli('--retries', '3')
        self.assertEqual((usage.returncode, usage.stdout), (2, b''))
        self.assertFalse((self.root / 'tools/hyprctl.log').exists())

    def test_cli_internal_errors_print_no_exception_text(self):
        # A core that answers status with something no hyprflip ever printed.
        (self.tools() / 'status.json').write_text('["internal-detail"]')
        recipe = self.acme()
        result = self.cli('--request', json.dumps({'protocol': 1, 'action': 'open', 'recipe': recipe, 'workspace': 2}))
        reply = self.answer(result, 1)
        self.assertEqual(reply, {'protocol': 1, 'ok': False, 'code': 'internal', 'message': setup.Unfinished.MESSAGES['internal'],
                                 'labels': [], 'launched': []})
        for text in (b'internal-detail', b'Traceback', b'Error', b'list'):
            self.assertNotIn(text, result.stdout)
        self.assertIn('hyprflip status', (self.root / 'tools/hyprctl.log').read_text())

    def test_cli_without_session_environment_is_unavailable(self):
        listing = json.dumps({'protocol': 1, 'action': 'list', 'store': self.store})
        for drop in (('HYPRLAND_INSTANCE_SIGNATURE',), ('XDG_RUNTIME_DIR',), ('HYPRLAND_INSTANCE_SIGNATURE', 'XDG_RUNTIME_DIR')):
            with self.subTest(drop=drop):
                self.assertEqual(self.answer(self.cli('--request', listing, drop=drop), 1)['code'], 'unavailable')
        self.assertFalse((self.root / 'tools/hyprctl.log').exists())
        self.assertFalse(Path(self.store).exists())

    def test_cli_survives_a_closed_stdout(self):
        read, write = os.pipe()
        os.close(read)
        try:
            result = self.cli('--request', json.dumps({'protocol': 1, 'action': 'list', 'store': self.store}), stdout=write)
        finally:
            os.close(write)
        self.assertEqual((result.returncode, result.stderr), (1, b''))

    def test_cli_signals_end_a_waiting_request_with_one_cancelled_reply(self):
        # OmaRelay cancels a request with SIGTERM, a terminal with SIGINT. Either one only sets a flag,
        # which this request reads as it waits for the lock a picker holds.
        menus = setup.Request(Path(self.env['XDG_RUNTIME_DIR']), 'unattended-cli-bogus')
        holder = menus.lock.open('a'); self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        request = json.dumps({'protocol': 1, 'action': 'open', 'recipe': self.acme(), 'workspace': 2, 'lock_ms': 30000})
        for number in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=number.name):
                process = self.cli('--request', request, wait=False)
                self.addCleanup(process.wait); self.addCleanup(process.kill)
                # It opens the lock only after setting its handlers.
                deadline = time.monotonic() + 30
                while str(menus.lock.resolve()) not in self.opened(process.pid):
                    self.assertTrue(process.poll() is None and time.monotonic() < deadline, process.returncode)
                    time.sleep(.02)
                process.send_signal(number)
                stdout, stderr = process.communicate(timeout=10)
                reply = self.answer(subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr), 1)
                self.assertEqual((reply['code'], reply['message'], reply['launched']),
                                 ('cancelled', setup.Unfinished.MESSAGES['cancelled'], []))
        self.assertFalse((self.root / 'tools/hyprctl.log').exists())

    def test_capabilities_reports_actions_and_core(self):
        actions = ['capabilities', 'list', 'delete', 'open', 'save']
        self.assertEqual(self.send('capabilities'), {'protocol': 1, 'ok': True, 'result': 'capabilities', 'actions': actions,
                                                    'core': True, 'max_panes': 5})
        self.ipc.snapshot.pop('card_ungroup')
        self.assertEqual(self.send('capabilities')['core'], False)
        # No core loaded is an answer as well.
        with patch.object(self.ipc, 'status', side_effect=setup.CoreUnavailable('Hyprflip is unavailable. Load the container plugin.')):
            self.assertEqual(self.send('capabilities'), {'protocol': 1, 'ok': True, 'result': 'capabilities', 'actions': actions,
                                                        'core': False, 'max_panes': 0})
        # Not reaching Hyprland is no answer: the caller tries again soon instead of waiting for another core.
        for failure in (setup.SetupError('Hyprland is not responding.'), OSError('hyprctl'),
                        subprocess.TimeoutExpired('hyprctl', 10)):
            with self.subTest(failure=type(failure).__name__), patch.object(self.ipc, 'status', side_effect=failure):
                reply = self.send('capabilities')
                self.assertEqual((reply['ok'], reply['code']), (False, 'hyprland'))
        self.assertEqual(self.send('capabilities', store=self.store)['code'], 'invalid_request')
        self.assertEqual(self.ipc.mutations, [])


class SharedExtractionsTest(unittest.TestCase):
    """Steps the menus now share with unattended actions still behave as the menus' own did."""
    setUp, prepare, launch, apply = (repair_test.RepairTest.setUp, repair_test.RepairTest.prepare,
                                     repair_test.RepairTest.launch, repair_test.RepairTest.apply)

    def arranged(self):
        return [m[1] for m in self.ipc.mutations if m[0] == 'action' and m[1].startswith('arrange ')]

    def test_blend_with_floor_zero_matches_repair_reserved(self):
        # What Reopen missing apps sent before it shared blend().
        for missing, live, sent in (('0xb', [.7, .3], 'arrange horizontal 0x2b:0.2 0xc:0.56 0xd:0.24'),
                                    ('0xc', [.55, .45], 'arrange horizontal 0xb:0.385 0x2c:0.3 0xd:0.315'),
                                    ('0xd', [1 / 3, 2 / 3], 'arrange horizontal 0xb:0.166666666667 0xc:0.333333333333 0x2d:0.5'),
                                    ('0xc', [.123456789, .876543211],
                                     'arrange horizontal 0xb:0.0864197523 0x2c:0.3 0xd:0.6135802477')):
            with self.subTest(missing=missing, live=live):
                self.setUp()
                self.ipc.remove(missing)
                survivors = list(self.ipc.card['faces'][1])
                self.ipc.card['layouts'][1].update(axis='horizontal', ratios=live)
                flow, plan = self.prepare(); self.apply(flow, plan)
                self.assertEqual(self.arranged(), [sent])
                new = hex(int(missing, 16) + 32)
                order = [new if a == missing else a for a in ('0xb', '0xc', '0xd')]
                inserted = {new: self.recipe['faces'][1]['ratios'][order.index(new)]}
                shares = setup.Saved.blend(order, dict(zip(survivors, live)), inserted, floor=0.)
                self.assertEqual(shares, setup.Saved.blend(order, dict(zip(survivors, live)), inserted))
                self.assertEqual(sent, 'arrange horizontal' + ''.join(f' {a}:{r:.12g}' for a, r in zip(order, shares)))
        # Two apps back on one face, around the one that stayed.
        self.setUp()
        self.ipc.remove('0xb'); self.ipc.remove('0xd'); self.ipc.focus('0xa')
        flow, plan = self.prepare(); self.apply(flow, plan)
        sent = 'arrange vertical 0x2b:0.2 0xc:0.3 0x2d:0.5'
        self.assertEqual(self.arranged(), [sent])
        order = ['0x2b', '0xc', '0x2d']
        shares = setup.Saved.blend(order, {'0xc': 1.}, {'0x2b': .2, '0x2d': .5}, floor=0.)
        self.assertEqual(sent, 'arrange vertical' + ''.join(f' {a}:{r:.12g}' for a, r in zip(order, shares)))

    def test_blend_leaves_live_apps_a_floor_and_sums_to_one(self):
        for order, live, inserted, floor, expected in (
                # Room enough: the kept apps keep their shares.
                (['k', 'a', 'b'], {'a': .5, 'b': .5}, {'k': .4}, .1, [.4, .3, .3]),
                # Kept shares summing to one shrink together until the live app has its floor.
                (['k', 'a', 'j'], {'a': 1.}, {'k': .5, 'j': .5}, .1, [.45, .1, .45]),
                # The floor is for the live apps between them, here .2 for two.
                (['k', 'a', 'b'], {'a': .6, 'b': .4}, {'k': .9}, .1, [.8, .12, .08]),
                # Live shares that do not sum to one are renormalised with the rest.
                (['a', 'k', 'b'], {'a': .3, 'b': .3}, {'k': .4}, 0., [.18 / .76, .4 / .76, .18 / .76]),
                (['a', 'b'], {'a': 2., 'b': 2.}, {}, .1, [.5, .5])):
            with self.subTest(order=order, live=live, inserted=inserted, floor=floor):
                shares = setup.Saved.blend(order, live, inserted, floor)
                self.assertEqual(len(shares), len(expected))
                for share, wanted in zip(shares, expected): self.assertAlmostEqual(share, wanted)
                self.assertAlmostEqual(sum(shares), 1, places=12)


if __name__ == '__main__': unittest.main()
