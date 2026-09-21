"""Direct card launching and atomic saved-card management."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import unittest

import opening_test
import saved_test
from setup_test import setup

Menu = saved_test.Menu


class LibraryTest(unittest.TestCase):
    setUp = saved_test.SavedTest.setUp

    def manage(self, *answers):
        flow = setup.Saved(self.ipc, Menu('0', *answers))
        return flow, flow.prepare_manage()

    def test_empty_launcher_can_save_the_focused_card(self):
        flow = setup.Saved(self.ipc, Menu('save', 'First card'))
        plan = flow.prepare_restore()
        self.assertEqual(flow.menu.prompts[0][0], 'No saved cards yet')
        flow.apply(plan)
        self.assertIn('First card', self.store.read())
        self.assertEqual(self.ipc.mutations, [])

    def test_update_uses_existing_name_current_layout_and_remembered_launcher(self):
        self.recipe['faces'][1]['apps'][0]['desktop_id'] = 'chosen-manually.desktop'
        self.store.update('Comms', self.recipe, None)
        self.ipc.clients['0xb']['size'][0] = 900
        flow = setup.Edit(self.ipc, Menu('manage', 'update'))
        plan = flow.prepare('0xb')
        # Read the latest resize when applying, as with ordinary Save.
        self.ipc.clients['0xb']['size'][0] = 1200
        flow.apply(plan)
        recipe = self.store.read()['Comms']
        self.assertEqual(recipe['faces'][1]['ratios'], [2 / 3, 1 / 3])
        self.assertEqual(recipe['faces'][1]['apps'][0]['desktop_id'], 'chosen-manually.desktop')
        self.assertEqual(len(flow.menu.prompts), 2)
        self.assertEqual(self.ipc.mutations, [])

    def test_update_recognizes_apps_after_a_transfer_between_faces(self):
        self.store.update('Comms', self.recipe, None)
        self.ipc.snapshot['containers'][0]['faces'] = [['0xa', '0xc'], ['0xb']]
        flow = setup.Edit(self.ipc, Menu('manage', 'update')); flow.apply(flow.prepare('0xb'))
        self.assertEqual([len(f['apps']) for f in self.store.read()['Comms']['faces']], [2, 1])

    def test_two_saved_variants_require_choosing_which_to_update(self):
        for name in ('First', 'Second'): self.store.update(name, self.recipe, None)
        self.ipc.clients['0xb']['size'][0] = 1200
        flow = setup.Edit(self.ipc, Menu('manage', '1', 'update')); flow.apply(flow.prepare('0xb'))
        self.assertEqual(self.store.read()['First'], self.recipe)
        self.assertEqual(self.store.read()['Second']['faces'][1]['ratios'], [2 / 3, 1 / 3])
        self.assertEqual(flow.menu.prompts[1][0], 'Manage saved cards')

    def test_changed_card_or_saved_definition_refuses_update(self):
        for change in ('card', 'file'):
            with self.subTest(change=change):
                self.setUp(); self.store.update('Comms', self.recipe, None)
                flow = setup.Edit(self.ipc, Menu('manage', 'update')); plan = flow.prepare('0xb')
                if change == 'card': self.ipc.snapshot['containers'][0]['active'] = 0
                else: self.store.update('Comms', self.recipe | {'active': 0}, self.recipe)
                before = self.store.path.read_bytes()
                with self.assertRaises(setup.SetupError): flow.apply(plan)
                self.assertEqual(self.store.path.read_bytes(), before)

    def test_rename_and_duplicate_only_change_saved_data(self):
        self.store.update('Comms', self.recipe, None)
        flow, plan = self.manage('duplicate', 'Work')
        flow.apply(plan)
        self.assertEqual(self.store.read(), {'Comms': self.recipe, 'Work': self.recipe})
        flow, plan = self.manage('rename', '../Messages $(echo test)')
        flow.apply(plan)
        self.assertEqual(set(self.store.read()), {'../Messages $(echo test)', 'Work'})
        self.assertEqual(self.ipc.mutations, [])
        self.assertEqual(len(self.ipc.snapshot['containers']), 1)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_name_cancel_and_existing_name_preserve_saved_data(self):
        self.store.update('Comms', self.recipe, None)
        before = self.store.path.read_bytes()
        for action in ('rename', 'duplicate'):
            for answer in (None, '', 'Comms', 'too\nlong'):
                with self.subTest(action=action, answer=answer):
                    with self.assertRaises((setup.Cancelled, setup.SetupError)): self.manage(action, answer)
                    self.assertEqual(self.store.path.read_bytes(), before)

    def test_atomic_rename_failure_and_concurrent_source_or_destination_edit(self):
        for change in ('write', 'source', 'destination'):
            with self.subTest(change=change):
                self.setUp(); self.store.update('Comms', self.recipe, None)
                flow, plan = self.manage('rename', 'New name')
                if change == 'source': self.store.update('Comms', self.recipe | {'active': 0}, self.recipe)
                if change == 'destination': self.store.update('New name', self.recipe, None)
                before = self.store.path.read_bytes()
                with patch.object(Path, 'replace', side_effect=OSError('Full disk')) if change == 'write' else setup.nullcontext():
                    with self.assertRaises((OSError, setup.SetupError)): flow.apply(plan)
                self.assertEqual(self.store.path.read_bytes(), before)

    def test_rename_at_capacity_succeeds_and_duplicate_refuses(self):
        cards = {f'Card {i:03}': deepcopy(self.recipe) for i in range(100)}
        self.store.change(dict.fromkeys(cards), cards)
        flow, plan = self.manage('duplicate', 'Extra')
        with self.assertRaisesRegex(setup.SetupError, '100 saved cards'): flow.apply(plan)
        flow, plan = self.manage('rename', 'New name'); flow.apply(plan)
        self.assertEqual(len(self.store.read()), 100)
        self.assertNotIn('Card 000', self.store.read())


class LauncherTest(unittest.TestCase):
    setUp = opening_test.OpeningTest.setUp
    desktop = opening_test.OpeningTest.desktop
    flow = opening_test.OpeningTest.flow

    def test_empty_launcher_explains_how_to_create_a_card(self):
        self.store.update('Comms', None, self.recipe)
        flow = setup.Saved(self.ipc, Menu('close'))
        with self.assertRaises(setup.Cancelled): flow.prepare_restore()
        self.assertEqual(flow.menu.prompts[0][0], 'No saved cards yet')
        self.assertIn('Super+Ctrl+Alt+O', flow.menu.prompts[0][1][0].detail)
    def test_local_and_floating_apps_open_with_one_selection(self):
        self.ipc.snapshot['workspace_protection'] = True
        self.ipc.clients['0xa']['floating'] = True
        flow, plan = self.flow()
        self.assertEqual(len(flow.menu.prompts), 1)
        self.assertIn('Tile apps', flow.menu.prompts[0][1][0].detail)
        with patch.object(flow, 'apply_reserved') as apply: flow.apply(plan)
        apply.assert_called_once()

    def test_launcher_describes_remote_apps_before_selection(self):
        self.ipc.clients['0xa']['workspace'] = {'id': 8, 'name': '8'}
        flow, _ = self.flow()
        self.assertIn('Bring apps from 8', flow.menu.prompts[0][1][0].detail)
        self.assertEqual(len(flow.menu.prompts), 1)

    def test_known_missing_launchers_need_no_review(self):
        for address in ('0xa', '0xb', '0xc'): del self.ipc.clients[address]
        flow, plan = self.flow()
        self.assertEqual(len(plan.launchers), 3)
        self.assertEqual(len(flow.menu.prompts), 1)
        self.assertEqual(self.ipc.mutations, [])

    def test_manage_back_returns_to_launcher_without_opening_any_apps(self):
        flow = setup.Saved(self.ipc, Menu('manage', '0', 'back', None))
        with patch.object(setup.DesktopApps, 'launch') as launch:
            with self.assertRaises(setup.Cancelled): flow.prepare_restore()
            launch.assert_not_called()
        self.assertEqual(flow.menu.prompts[-1][0], 'Open saved card')
        self.assertEqual(self.ipc.mutations, [])


if __name__ == '__main__': unittest.main()
