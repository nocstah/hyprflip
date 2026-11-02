"""Hidden cards, parked on a special workspace, stay out of the saved-card menus."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import repair_test
from saved_test import Menu
from setup_test import setup, window

HELD = ' is held by a hidden card. Close it or bring that card back, then try again.'


class ParkedCardsTest(unittest.TestCase):
    setUp = repair_test.RepairTest.setUp

    def park(self, card):
        # As status reports a card after card <id> workspace special:park silent.
        card['workspace'] = {'id': -98, 'name': 'special:park', 'special': True}
        for address in (a for face in card['faces'] for a in face):
            self.ipc.clients[address]['workspace'] = {'id': -98, 'name': 'special:park'}

    def away(self):
        # Meanwhile the user works in another app on workspace 2.
        self.ipc.clients['0xe'] = window('0xe', **{'class': 'other', 'initialClass': 'other'})
        self.ipc.active = '0xe'

    def test_saved_cards_never_offer_or_reveal_a_parked_card(self):
        self.park(self.ipc.card); self.away()
        flow = setup.Saved(self.ipc, Menu('0'))
        with patch.object(setup.DesktopApps, 'launch') as launch:
            with self.assertRaisesRegex(setup.SetupError, '^app-0xa' + HELD + '$'): flow.prepare_restore()
            launch.assert_not_called()
        self.assertEqual(len(flow.menu.prompts), 1)
        self.assertTrue(flow.menu.prompts[0][1][0].detail.startswith('Open here'))
        flow = setup.Saved(self.ipc, Menu('0', None))
        with self.assertRaises(setup.Cancelled): flow.prepare_manage()
        self.assertEqual(flow.menu.prompts[1][1][0].label, 'Open here')
        self.assertEqual(self.ipc.mutations, [])
        self.assertEqual({self.ipc.clients[a]['workspace']['id'] for a in ('0xa', '0xb', '0xc', '0xd')}, {-98})

    def test_go_to_takes_the_card_on_screen_and_never_a_parked_one(self):
        twins = {}
        for address in ('0xa', '0xb', '0xc', '0xd'):
            twins[address] = hex(int(address, 16) + 16)
            self.ipc.clients[twins[address]] = deepcopy(self.original[address]) | {
                'address': twins[address], 'pid': int(address, 16) + 16, 'workspace': {'id': 3, 'name': '3'}}
        shown = dict(id=2, faces=[[twins['0xa']], [twins[a] for a in ('0xb', '0xc', '0xd')]],
                     current=twins['0xb'], active=1, unfolded=False)
        self.ipc.snapshot['containers'].append(shown)
        self.park(self.ipc.card); self.away()
        flow = setup.Saved(self.ipc, Menu())
        plan = flow.prepare_named('Comms', self.recipe, 2, '0xe')
        self.assertEqual((plan.action, plan.card['id'], flow.menu.prompts), ('goto', 2, []))
        flow.apply(plan)
        self.assertEqual(self.ipc.mutations, [('focus', '0x1b')])
        # Parked after the menu chose it, it is not revealed either.
        self.ipc.active = '0xe'
        plan = flow.prepare_named('Comms', self.recipe, 2, '0xe')
        self.park(self.ipc.snapshot['containers'][1])
        with self.assertRaisesRegex(setup.SetupError, 'That open card changed'): flow.apply(plan)
        self.assertEqual(self.ipc.mutations, [('focus', '0x1b')])

    def test_partial_completion_leaves_a_parked_card_alone(self):
        self.ipc.remove('0xc'); self.park(self.ipc.card); self.away()
        flow = setup.Saved(self.ipc, Menu())
        with self.assertRaisesRegex(setup.SetupError, '^app-0xa' + HELD + '$'):
            flow.prepare_named('Comms', self.recipe, 2, '0xe')
        self.assertEqual((self.ipc.mutations, self.ipc.active), ([], '0xe'))
        # Back on screen, the same card is completed in place.
        self.ipc.card['workspace'] = {'id': 2, 'name': '2', 'special': False}
        for address in ('0xa', '0xb', '0xd'): self.ipc.clients[address]['workspace'] = {'id': 2, 'name': '2'}
        self.assertEqual(flow.prepare_named('Comms', self.recipe, 2, '0xe').action, 'repair')

    def test_reopen_missing_apps_names_an_app_held_by_a_hidden_card(self):
        self.ipc.remove('0xc', close=False)
        self.ipc.clients['0xf'] = window('0xf', **{'class': 'other', 'initialClass': 'other'})
        hidden = dict(id=2, faces=[['0xc'], ['0xf']], current='0xc', active=0, unfolded=False)
        self.ipc.snapshot['containers'].append(hidden); self.park(hidden)
        with patch.object(setup.DesktopApps, 'launch') as launch:
            with self.assertRaisesRegex(setup.SetupError, '^app-0xc' + HELD + '$'):
                setup.Edit(self.ipc, Menu('repair')).prepare(self.ipc.active)
            launch.assert_not_called()
        self.assertEqual(self.ipc.mutations, [])
        # A card on screen keeps the message it always had.
        hidden['workspace'] = {'id': 2, 'name': '2', 'special': False}
        for address in ('0xc', '0xf'): self.ipc.clients[address]['workspace'] = {'id': 2, 'name': '2'}
        with self.assertRaisesRegex(setup.SetupError, '^app-0xc is already open but unavailable'):
            setup.Edit(self.ipc, Menu('repair')).prepare(self.ipc.active)
        self.assertEqual(self.ipc.mutations, [])


if __name__ == '__main__': unittest.main()
