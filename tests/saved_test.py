"""Saved-card matching, cancellation, file integrity and stale-plan protection."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from edit_test import CardIPC
from setup_test import Picker, setup


class Menu(Picker):
    def input(self, prompt):
        answer = next(self.answers)
        if answer is None: raise setup.Cancelled()
        return answer


class SavedTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ipc = CardIPC(full=True)
        self.ipc.env = {'XDG_STATE_HOME': directory.name}
        for index, (address, window) in enumerate(self.ipc.clients.items()):
            window.update({'class': 'app-' + address, 'initialClass': 'app-' + address,
                           'title': 'Title ' + address, 'size': [600, 700], 'at': [index * 610, 0]})
        self.recipe = setup.Saved.capture(self.ipc.snapshot['containers'][0], self.ipc.windows())
        self.store = setup.RecipeStore(self.ipc.env)

    def saved(self, *answers): return setup.Saved(self.ipc, Menu(*answers))

    def ungrouped(self):
        self.store.update('Comms', self.recipe, None)
        self.ipc.snapshot['containers'] = []

    def test_save_cancel_and_name_does_not_change_windows(self):
        for name in (None, '', 'x' * 65, 'one\ntwo'):
            flow = setup.Edit(self.ipc, Menu('save', name))
            with self.assertRaises((setup.Cancelled, setup.SetupError)): flow.prepare('0xb')
            self.assertEqual(self.ipc.mutations, [])
            self.assertFalse(self.store.path.exists())
        name = '../Comms `echo test` $(echo test)'
        flow = setup.Edit(self.ipc, Menu('save', name))
        plan = flow.prepare('0xb')
        self.assertFalse(self.store.path.exists())
        flow.apply(plan)
        self.assertIn(name, self.store.read())
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.ipc.mutations, [])

    def test_replace_requires_choice_and_merge_preserves_other_cards(self):
        self.store.update('Comms', self.recipe, None)
        before = self.store.path.read_bytes()
        with self.assertRaises(setup.Cancelled): setup.Edit(self.ipc, Menu('save', 'Comms', 'cancel')).prepare('0xb')
        self.assertEqual(self.store.path.read_bytes(), before)
        flow = setup.Edit(self.ipc, Menu('save', 'Comms', 'replace'))
        plan = flow.prepare('0xb')
        self.store.update('Another', self.recipe, None)
        flow.apply(plan)
        self.assertEqual(set(self.store.read()), {'Comms', 'Another'})

    def test_concurrent_edit_and_corrupt_file_are_never_overwritten(self):
        self.store.update('Comms', self.recipe, None)
        changed = deepcopy(self.recipe); changed['active'] = 0
        self.store.update('Comms', changed, self.recipe)
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(setup.SetupError, 'changed in another'): self.store.update('Comms', None, self.recipe)
        self.assertEqual(self.store.path.read_bytes(), before)
        for content in ('broken json', '{"version":99,"cards":{}}', '{"version":1,"cards":{"Comms":{}}}'):
            self.store.path.write_text(content)
            with self.assertRaisesRegex(setup.SetupError, 'not been overwritten'): self.store.update('Other', self.recipe, None)
            self.assertEqual(self.store.path.read_text(), content)

    def test_invalid_ratios_and_unknown_schema_are_rejected(self):
        for value in (float('nan'), float('inf'), 0, -1, 2):
            invalid = deepcopy(self.recipe); invalid['faces'][0]['ratios'] = [value]
            self.store.root.mkdir(parents=True, exist_ok=True)
            self.store.path.write_text(json.dumps({'version': 1, 'cards': {'Invalid': invalid}}))
            with self.assertRaises(setup.SetupError): self.store.read()

    def test_failed_atomic_replace_preserves_previous_file(self):
        self.store.update('Comms', self.recipe, None)
        before = self.store.path.read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('Full disk')):
            with self.assertRaises(OSError): self.store.update('Other', self.recipe, None)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertFalse(list(self.store.root.glob('cards-*')))

    def test_changed_card_during_naming_is_not_saved(self):
        flow = setup.Edit(self.ipc, Menu('save', 'Comms'))
        plan = flow.prepare('0xb')
        self.ipc.snapshot['containers'][0]['active'] = 0
        with self.assertRaises(setup.SetupError): flow.apply(plan)
        self.assertFalse(self.store.path.exists())

    def test_unique_apps_match_after_pid_address_and_title_changes(self):
        self.ungrouped()
        self.ipc.clients = {'0x' + str(i): dict(w, address='0x' + str(i), pid=100 + i, title='Changed title')
                            for i, w in enumerate(self.ipc.clients.values(), 10)}
        flow = self.saved('0', 'restore', 'restore')
        plan = flow.prepare_manage()
        self.assertEqual(list(plan.windows), ['0x10', '0x11', '0x12'])
        self.assertEqual(plan.arrangement['faces'][1]['windows'], ['0x11', '0x12'])
        self.assertEqual(self.ipc.mutations, [])

    def test_web_app_matches_after_default_browser_changes(self):
        front = self.recipe['faces'][0]['apps'][0]
        front.update({'class': 'brave-gmail.com__-Default', 'initial_class': 'brave-gmail.com__-Default'})
        self.ungrouped()
        self.ipc.clients['0xa'].update({'class': 'chrome-gmail.com__-Default',
                                        'initialClass': 'chrome-gmail.com__-Default', 'title': 'Inbox'})
        plan = self.saved('0', 'restore', 'restore').prepare_manage()
        self.assertEqual(plan.arrangement['faces'][0]['windows'], ['0xa'])
        self.assertEqual(self.ipc.mutations, [])

    def test_web_app_match_needs_the_same_site_and_profile(self):
        app = {'class': 'brave-gmail.com__-Default', 'initial_class': 'brave-gmail.com__-Default'}
        same = lambda cls: setup.Saved.same_app(app, {'class': cls, 'initialClass': cls})
        self.assertTrue(same('msedge-gmail.com__-Default'))
        self.assertFalse(same('chrome-web.whatsapp.com__-Default'))
        self.assertFalse(same('chrome-gmail.com__-Profile_1'))
        self.assertFalse(same('firefox-gmail.com__-Default'))
        self.assertFalse(same('chrome'))

    def test_ambiguous_browser_match_is_a_choice_and_review_can_cancel(self):
        self.ungrouped()
        self.ipc.clients['0xd'].update(self.ipc.clients['0xa'] | {'address': '0xd', 'pid': 4})
        flow = self.saved('0', 'restore', '0xa', 'cancel')
        with self.assertRaises(setup.Cancelled): flow.prepare_manage()
        self.assertIn('Front: choose', flow.menu.prompts[2][0])
        self.assertEqual(self.ipc.mutations, [])

    def test_missing_app_allows_explicit_replacement_from_other_workspace(self):
        self.ungrouped()
        del self.ipc.clients['0xa']
        self.ipc.clients['0xd']['workspace'] = {'id': 8, 'name': '8'}
        flow = self.saved('0', 'restore', 'workspace:8', '0xd', 'restore')
        plan = flow.prepare_manage()
        self.assertEqual(plan.arrangement['faces'][0]['windows'], ['0xd'])
        self.assertEqual(plan.windows['0xd']['workspace']['id'], 8)
        self.assertEqual(plan.workspace, 2)
        self.assertEqual(self.ipc.mutations, [])

    def test_review_can_change_an_automatic_match(self):
        self.ungrouped()
        flow = self.saved('0', 'restore', '0', '0xd', 'restore')
        plan = flow.prepare_manage()
        self.assertEqual(plan.arrangement['faces'][0]['windows'], ['0xd'])
        self.assertEqual(self.ipc.mutations, [])

    def test_stale_restore_refuses_before_mutation(self):
        for change in ('file', 'workspace', 'focus', 'app'):
            with self.subTest(change=change):
                self.setUp(); self.ungrouped()
                flow = self.saved('0', 'restore', 'restore'); plan = flow.prepare_manage()
                if change == 'file': self.store.update('Comms', None, self.recipe)
                if change == 'workspace': self.ipc.workspace = 3
                if change == 'focus': self.ipc.active = '0xd'
                if change == 'app': self.ipc.clients['0xa']['pid'] += 100
                with self.assertRaises(setup.SetupError): flow.apply(plan)
                self.assertEqual(self.ipc.mutations, [])

    def test_delete_is_explicit_and_never_ungroups_running_apps(self):
        self.store.update('Comms', self.recipe, None)
        with self.assertRaises(setup.Cancelled): self.saved('0', 'delete', 'cancel').prepare_manage()
        self.assertIn('Comms', self.store.read())
        flow = self.saved('0', 'delete', 'delete'); flow.apply(flow.prepare_manage())
        self.assertEqual(self.store.read(), {})
        self.assertEqual(self.ipc.mutations, [])
        self.assertEqual(len(self.ipc.snapshot['containers']), 1)

    def whole_core(self, reply='ok: ok', builds=True):
        """A core with native cards and card ungroup, whose restore builds the card in one step."""
        self.ipc.snapshot.update(native_cards=True, card_ungroup=True)
        sent = []

        def batch(commands):
            sent.append(commands)
            if builds:
                self.ipc.snapshot['containers'] = [dict(id=7, faces=[['0xa'], ['0xb', '0xc']], current='0xb', active=1,
                                                        unfolded=False, box=[0, 0, 1200, 700])]
            return [reply]
        self.ipc.batch = batch
        return sent

    def test_saved_card_is_rebuilt_in_one_step_not_pane_by_pane(self):
        # Pairing in the front app's tile and attaching the rest fails whenever that
        # tile is narrower than an app's minimum size, however big the card would be.
        self.ungrouped(); sent = self.whole_core()
        flow = self.saved('0', 'restore', 'restore')
        self.assertEqual(flow.apply(flow.prepare_manage()), 'Restored “Comms”.')
        self.assertEqual(sent, [['hyprflip restore quiet tiled 1 0 0 0 600 700 front horizontal 0xa 0xa:1 '
                                 'back horizontal 0xb 0xb:0.5 0xc:0.5']])
        self.assertFalse([m for m in self.ipc.mutations if m[0] == 'action'])
        self.assertEqual(self.ipc.mutations[-1], ('focus', '0xb'))

    def test_floating_card_keeps_the_front_apps_size_from_before_setup(self):
        self.recipe['floating'] = True
        self.ungrouped(); sent = self.whole_core()
        self.ipc.data = lambda *args, _data=self.ipc.data: (
            [{'id': 2, 'monitorID': 0, 'tiledLayout': 'dwindle'}] if args == ('-j', 'workspaces') else
            [{'id': 0, 'x': 0, 'y': 0, 'width': 3000, 'height': 2000, 'scale': 2, 'reserved': [0, 30, 0, 0]}]
            if args == ('-j', 'monitors') else _data(*args))
        flow = self.saved('0', 'restore', 'restore'); plan = flow.prepare_manage()
        self.ipc.clients['0xa']['size'] = [300, 700]  # Squeezed once setup tiles the other apps beside it.
        flow.apply(plan)
        self.assertTrue(sent[0][0].startswith('hyprflip restore quiet floating 1 0 450 165 600 700 front'), sent)

    def open_elsewhere(self, workspace=3, floating=False):
        """Comms saved, and open as a card on another workspace; the core answers every batch ok."""
        self.store.update('Comms', self.recipe, None)
        card = self.ipc.snapshot['containers'][0]
        card.update(floating=floating, id=card.get('id', 1))
        for face in card['faces']:
            for address in face: self.ipc.clients[address]['workspace'] = {'id': workspace, 'name': str(workspace)}
        self.ipc.snapshot.update(native_cards=True, card_ungroup=True)
        sent = []

        def batch(commands):
            sent.append(commands)
            for command in commands:
                if ' workspace ' in command:
                    for face in card['faces']:
                        for address in face: self.ipc.clients[address]['workspace'] = {'id': 2, 'name': '2'}
                if command.endswith(' ungroup'): self.ipc.snapshot['containers'] = []
                if ' restore quiet ' in command:
                    self.ipc.snapshot['containers'] = [dict(card, floating=True)]
            return ['ok']
        self.ipc.batch = batch
        return card, sent

    def test_an_open_card_elsewhere_is_brought_here_not_gone_to(self):
        card, sent = self.open_elsewhere()
        flow = self.saved('0')
        plan = flow.prepare_restore()
        self.assertIn('Bring here from workspace 3', flow.menu.prompts[0][1][0].detail)
        self.assertEqual(flow.apply(plan), 'Brought “Comms” here.')
        self.assertEqual(sent, [[f'hyprflip card {card["id"]} workspace 2 silent']])
        self.assertEqual(self.ipc.mutations[-1], ('focus', card['current']))

    def test_a_card_saved_floating_and_open_as_a_tile_is_floated_again(self):
        # A tile is often too narrow for the apps that a floating card fits.
        self.recipe['floating'] = True
        card, sent = self.open_elsewhere(workspace=2)
        self.ipc.data = lambda *args, _data=self.ipc.data: (
            [{'id': 2, 'monitorID': 0, 'tiledLayout': 'dwindle'}] if args == ('-j', 'workspaces') else
            [{'id': 0, 'x': 0, 'y': 0, 'width': 3000, 'height': 2000, 'scale': 2, 'reserved': [0, 30, 0, 0]}]
            if args == ('-j', 'monitors') else _data(*args))
        flow = self.saved('0'); plan = flow.prepare_restore()
        self.assertIn('Open on this workspace', flow.menu.prompts[0][1][0].detail)
        self.assertEqual(flow.apply(plan), 'Floated “Comms” again.')
        self.assertEqual(sent[0], [f'hyprflip card {card["id"]} ungroup'])
        self.assertTrue(sent[1][0].startswith('hyprflip restore quiet floating '), sent)
        self.assertIn('front horizontal 0xa 0xa:1 back horizontal', sent[1][0])

    def test_a_card_saved_for_its_own_workspace_is_still_gone_to(self):
        self.recipe['workspace'] = 3
        card, sent = self.open_elsewhere()
        flow = self.saved('0'); flow.apply(flow.prepare_restore())
        self.assertEqual(sent, [])
        self.assertIn(('focus', card['current']), self.ipc.mutations)

    def test_a_refused_restore_says_which_app_does_not_fit(self):
        self.ungrouped()
        self.whole_core('error: Claude needs at least 600 px, so this card would have to be 1818 px wide, '
                        'and the screen has 1512.', builds=False)
        flow = self.saved('0', 'restore', 'restore')
        with self.assertRaisesRegex(setup.SetupError, r'^Claude needs at least 600 px'):
            flow.apply(flow.prepare_manage())
        self.assertEqual(self.ipc.snapshot['containers'], [])

    def test_a_core_without_card_ungroup_still_builds_pane_by_pane(self):
        self.ungrouped(); sent = self.whole_core()
        self.ipc.snapshot['card_ungroup'] = False
        flow = self.saved('0', 'restore', 'restore')
        with self.assertRaises(setup.SetupError): flow.apply(flow.prepare_manage())
        self.assertEqual(sent, [])
        self.assertIn(('action', 'mark'), self.ipc.mutations)


class MultiFaceSavedTest(unittest.TestCase):
    """Cards with three or four faces, saved and opened again; two-face cards as they always were."""
    setUp, saved = SavedTest.setUp, SavedTest.saved

    def three_faces(self):
        """The card gains Face 3, 0xd alone, and shows it."""
        card = self.ipc.snapshot['containers'][0]
        card['faces'].append(['0xd'])
        card.update(active=2, current='0xd')
        self.ipc.snapshot['container_max_faces'] = 4
        self.ipc.active = '0xd'
        return card

    def test_restore_line_writes_faces_after_the_back(self):
        arrangement = {'active': 2, 'faces': [
            {'windows': ['0xa'], 'axis': 'horizontal', 'ratios': [1], 'focus': 0},
            {'windows': ['0xb', '0xc'], 'axis': 'vertical', 'ratios': [.6, .4], 'focus': 1},
            {'windows': ['0xd'], 'axis': 'horizontal', 'ratios': [1], 'focus': 0}]}
        self.assertEqual(setup.Setup.restore_line(arrangement, [0, 0, 1200, 700], False),
                         'restore quiet tiled 2 0 0 0 1200 700 front horizontal 0xa 0xa:1 '
                         'back vertical 0xc 0xb:0.6 0xc:0.4 face horizontal 0xd 0xd:1')
        arrangement['faces'].append({'windows': ['0xe'], 'axis': 'horizontal', 'ratios': [1], 'focus': 0})
        self.assertTrue(setup.Setup.restore_line(arrangement, [0, 0, 1, 1], True).endswith(
            'face horizontal 0xd 0xd:1 face horizontal 0xe 0xe:1'))
        for broken in ({'active': 4}, {'faces': arrangement['faces'][:1], 'active': 0},
                       {'faces': arrangement['faces'] * 2, 'active': 0}):
            with self.subTest(broken=broken), self.assertRaises(setup.SetupError):
                setup.Setup.restore_line(arrangement | broken, [0, 0, 1, 1], False)

    def test_a_three_face_card_saves_and_reads_back_as_it_was(self):
        card = self.three_faces()
        card['layouts'] = [dict(axis='horizontal', focused='0xa', ratios=[1.]),
                           dict(axis='vertical', focused='0xc', ratios=[.6, .4]),
                           dict(axis='horizontal', focused='0xd', ratios=[1.])]
        recipe = setup.Saved.capture(card, self.ipc.windows())
        self.assertEqual((len(recipe['faces']), recipe['active']), (3, 2))
        self.assertEqual(recipe['faces'][1] | {'apps': []}, {'apps': [], 'axis': 'vertical', 'ratios': [.6, .4], 'focus': 1})
        self.assertEqual([a['label'] for a in recipe['faces'][2]['apps']], [setup.app_name(self.ipc.clients['0xd'])])
        self.store.update('Three', recipe, None)
        self.assertEqual(self.store.read(), {'Three': recipe})
        # The card it was saved from is that card, and no two-face card is.
        windows, state = self.ipc.windows(), self.ipc.status()
        self.assertEqual([c['id'] for c in setup.Saved.open_cards(recipe, windows, state)], [1])
        self.assertEqual(setup.Saved.open_cards(self.recipe, windows, state), [])
        self.assertIsNone(setup.Saved.surviving_slots(self.recipe, card, windows))
        self.assertIn('↔', setup.Saved.describe(recipe))

    def test_a_three_face_card_opens_again_in_one_restore(self):
        card = deepcopy(self.three_faces())
        recipe = setup.Saved.capture(card, self.ipc.windows())
        self.store.update('Three', recipe, None)
        self.ipc.snapshot['containers'] = []
        self.ipc.snapshot.update(native_cards=True, card_ungroup=True)
        sent = []

        def batch(commands):
            sent.append(commands)
            self.ipc.snapshot['containers'] = [card]
            return ['ok: ok']
        self.ipc.batch = batch
        flow = self.saved('0', 'restore', 'restore')
        plan = flow.prepare_manage()
        self.assertEqual([c.label.split(' · ')[0] for c in flow.menu.prompts[-1][1][1:-1]], ['Front', 'Back', 'Back', 'Face 3'])
        self.assertEqual(flow.apply(plan), 'Restored “Three”.')
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][0].startswith('hyprflip restore quiet tiled 2 0 '), sent)
        self.assertTrue(sent[0][0].endswith(' face horizontal 0xd 0xd:1'), sent)
        self.assertEqual(self.ipc.mutations[-1], ('focus', '0xd'))

    def test_a_core_without_numbered_faces_refuses_a_three_face_card_before_any_change(self):
        recipe = setup.Saved.capture(self.three_faces(), self.ipc.windows())
        self.store.update('Three', recipe, None)
        self.ipc.snapshot['containers'] = []
        del self.ipc.snapshot['container_max_faces']
        with self.assertRaisesRegex(setup.SetupError, 'it has 3 faces'):
            self.saved('0', 'restore').prepare_manage()
        self.assertEqual(self.ipc.mutations, [])

    def test_two_face_cards_saved_by_older_versions_still_read(self):
        older = {'version': 1, 'cards': {'Comms': {
            'faces': [{'apps': [{'class': 'foot', 'initial_class': 'foot', 'title': 'Terminal', 'label': 'Foot'}],
                       'axis': 'horizontal', 'ratios': [1.0], 'focus': 0},
                      {'apps': [{'class': 'a', 'initial_class': 'a', 'title': '', 'label': 'A'},
                                {'class': 'b', 'initial_class': 'b', 'title': '', 'label': 'B'}],
                       'axis': 'vertical', 'ratios': [0.5, 0.5], 'focus': 1}],
            'active': 1, 'floating': True}}}
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(json.dumps(older))
        self.assertEqual(self.store.read(), older['cards'])

    def test_face_counts_and_active_faces_out_of_range_are_rejected(self):
        face = self.recipe['faces'][0]
        for faces, active in (([face], 0), ([face] * 5, 0), ([face] * 3, 3), ([face] * 2, 2), ([face] * 4, -1)):
            with self.subTest(faces=len(faces), active=active):
                with self.assertRaises(ValueError): setup.RecipeStore.validate({'faces': faces, 'active': active})
        for count in (2, 3, 4):
            setup.RecipeStore.validate({'faces': [face] * count, 'active': count - 1})

if __name__ == '__main__': unittest.main()
