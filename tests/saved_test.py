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


if __name__ == '__main__': unittest.main()
