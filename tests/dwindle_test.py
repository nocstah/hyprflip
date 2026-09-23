"""Dwindle workflows, optional provider detection and stale-layout guards."""
from copy import deepcopy
import unittest

from edit_test import CardIPC
from setup_test import Picker, setup


class DwindleIPC(CardIPC):
    def __init__(self):
        super().__init__(full=True)
        self.layout = 'dwindle'
        self.snapshot.update(native_cards=True, hy3_provider=False, layout_controls=True,
                             repair_cards=True, container_max_panes=5)
        card = self.snapshot['containers'][0]
        card['native_group'] = True
        for index, window in enumerate(self.clients.values()):
            window.update(size=[600, 700], at=[index * 610, 0])
        for face in card['faces']:
            for address in face:
                self.clients[address]['grouped'] = ['0xa', '0xb', '0xc']

    def data(self, *args):
        if args == ('-j', 'workspaces'):
            return [{'id': self.workspace, 'tiledLayout': self.layout}]
        return super().data(*args)

    def action(self, action):
        super().action(action)
        if action == 'card':
            front, back = self.snapshot['marked'], self.active
            self.snapshot['containers'].append(dict(id=2, faces=[[front], [back]], active=0,
                                                   current=front, unfolded=False, box=[0, 0, 1000, 700]))


class DwindleTest(unittest.TestCase):
    def fresh(self):
        ipc = DwindleIPC()
        ipc.snapshot['containers'] = []
        for window in ipc.clients.values(): window['grouped'] = []
        return ipc

    def test_guided_creation_uses_native_card_without_hy3(self):
        ipc = self.fresh()
        flow = setup.Setup(ipc, Picker('0xb', 'create'))
        selected = flow.prepare('0xa')
        self.assertEqual(ipc.mutations, [])
        flow.apply(selected)
        self.assertIn(('action', 'card'), ipc.mutations)
        self.assertNotIn(('action', 'pair'), ipc.mutations)
        self.assertEqual(ipc.snapshot['containers'][0]['faces'], [['0xa'], ['0xb']])

    def test_existing_native_group_can_be_edited_on_dwindle(self):
        ipc = DwindleIPC()
        flow = setup.Edit(ipc, Picker('layout', 'layout vertical'))
        plan = flow.prepare('0xb')
        flow.apply(plan)
        self.assertIn(('action', 'layout vertical'), ipc.mutations)

    def test_layout_change_between_selection_and_creation_prevents_mutation(self):
        ipc = self.fresh()
        flow = setup.Setup(ipc, Picker('0xb', 'create'))
        selected = flow.prepare('0xa')
        for layout in ('master', 'hy3'):
            ipc.layout = layout
            with self.subTest(layout=layout), self.assertRaisesRegex(setup.SetupError, 'layout changed'):
                flow.apply(selected)
            self.assertEqual(ipc.mutations, [])

    def test_missing_native_capability_requires_updated_core(self):
        ipc = self.fresh()
        ipc.snapshot.pop('native_cards')
        with self.assertRaises(setup.SetupError):
            setup.Setup(ipc, Picker()).prepare('0xa')
        self.assertEqual(ipc.mutations, [])

    def test_hy3_remains_optional_and_older_provider_status_is_supported(self):
        legacy = dict(container_provider=True)
        self.assertTrue(setup.card_layout_available(legacy, 'hy3'))
        self.assertFalse(setup.card_layout_available(legacy, 'dwindle'))
        native = legacy | dict(native_cards=True, hy3_provider=False)
        self.assertTrue(setup.card_layout_available(native, 'dwindle'))
        self.assertFalse(setup.card_layout_available(native, 'hy3'))
        self.assertTrue(setup.card_layout_available(native | dict(hy3_provider=True), 'hy3'))

    def test_saved_definition_accepts_dwindle_and_rejects_missing_hy3(self):
        ipc = DwindleIPC()
        for index, window in enumerate(ipc.clients.values()):
            window.update(size=[600, 700], at=[index * 610, 0])
        recipe = setup.Saved.capture(ipc.snapshot['containers'][0], ipc.windows())
        flow = setup.Saved(ipc, Picker())
        flow.check_workspace(recipe, 2)
        before = deepcopy(ipc.snapshot)
        ipc.layout = 'hy3'
        with self.assertRaises(setup.SetupError): flow.check_workspace(recipe, 2)
        self.assertEqual(ipc.snapshot, before)
        self.assertEqual(ipc.mutations, [])


if __name__ == '__main__': unittest.main()
