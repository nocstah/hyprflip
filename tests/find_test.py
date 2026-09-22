"""Finding hidden panes must reveal the chosen app, never reconstruct a card."""
from copy import deepcopy
import unittest

from setup_test import IPC as BaseIPC, Picker, setup as w, window


class IPC(BaseIPC):
    def __init__(self, pair=False):
        super().__init__()
        self.active = '0xa'
        self.workspace = 2
        if pair:
            self.snapshot['pairs'] = [dict(id=1, front='0xa', back='0xb', current='0xa')]
        else:
            self.snapshot['containers'] = [dict(id=1, faces=[['0xa'], ['0xb', '0xc']],
                active=0, current='0xa', unfolded=False, floating=False, box=[10, 10, 1000, 700])]
        self.clients['0xb']['hidden'] = True
    def data(self, *args):
        if args == ('-j', 'activeworkspace'): return {'id': self.workspace}
        return super().data(*args)
    def focus(self, address):
        super().focus(address)
        self.active = address
        self.workspace = self.clients[address]['workspace']['id']
    def action(self, action):
        assert action == 'flip', action
        super().action(action)
        if self.snapshot['containers']:
            card = self.snapshot['containers'][0]
            card['active'] = 1 - card['active']
            card['current'] = card['faces'][card['active']][0]
        else:
            card = self.snapshot['pairs'][0]
            card['current'] = card['back'] if card['current'] == card['front'] else card['front']


class FindTest(unittest.TestCase):
    def test_hidden_second_pane_is_selected_after_one_flip(self):
        ipc, picker = IPC(), Picker('0xc')
        shape = deepcopy(ipc.snapshot['containers'][0])
        flow = w.Find(ipc, picker)
        plan = flow.prepare()
        self.assertEqual(ipc.mutations, [])
        flow.apply(plan)
        self.assertEqual(ipc.mutations, [('focus', '0xa'), ('action', 'flip'), ('focus', '0xc')])
        after = ipc.snapshot['containers'][0]
        self.assertEqual(after['faces'], shape['faces'])
        self.assertEqual(after['box'], shape['box'])
        self.assertEqual(ipc.active, '0xc')

    def test_native_pairs_reveal_the_hidden_side_too(self):
        ipc = IPC(pair=True)
        flow = w.Find(ipc, Picker('0xb'))
        flow.apply(flow.prepare())
        self.assertEqual(ipc.snapshot['pairs'][0]['current'], '0xb')
        self.assertEqual(ipc.active, '0xb')

    def test_visible_unfolded_and_already_turned_cards_are_only_focused(self):
        for mode in ('visible', 'unfolded', 'turned'):
            with self.subTest(mode=mode):
                ipc = IPC()
                target = '0xa' if mode == 'visible' else '0xc'
                flow = w.Find(ipc, Picker(target))
                plan = flow.prepare()
                if mode == 'unfolded': ipc.snapshot['containers'][0]['unfolded'] = True
                if mode == 'turned': ipc.snapshot['containers'][0].update(active=1, current='0xb')
                flow.apply(plan)
                self.assertEqual(ipc.mutations, [('focus', target)])

    def test_cancel_and_stale_identity_membership_or_workspace_do_not_change_anything(self):
        ipc = IPC()
        with self.assertRaises(w.Cancelled): w.Find(ipc, Picker(None)).prepare()
        self.assertEqual(ipc.mutations, [])
        for change in ('close', 'reuse', 'group', 'move'):
            with self.subTest(change=change):
                ipc = IPC()
                flow = w.Find(ipc, Picker('0xb'))
                plan = flow.prepare()
                if change == 'close': del ipc.clients['0xc']
                if change == 'reuse': ipc.clients['0xb']['pid'] += 1
                if change == 'group': ipc.snapshot['containers'][0]['faces'][1].reverse()
                if change == 'move': ipc.clients['0xb']['workspace']['id'] = 3
                with self.assertRaises(w.SetupError): flow.apply(plan)
                self.assertEqual(ipc.mutations, [])

    def test_remote_and_floating_cards_keep_their_workspace_and_mode(self):
        ipc = IPC()
        ipc.workspace = 9
        ipc.snapshot['containers'][0]['floating'] = True
        original = deepcopy(ipc.clients)
        flow = w.Find(ipc, Picker('0xb'))
        flow.apply(flow.prepare())
        self.assertEqual(ipc.workspace, 2)
        self.assertEqual(ipc.clients, original)
        self.assertTrue(ipc.snapshot['containers'][0]['floating'])

    def test_result_labels_show_side_visibility_and_workspace(self):
        ipc, picker = IPC(), Picker('0xa')
        w.Find(ipc, picker).prepare()
        choices = {c.value: c for c in picker.prompts[0][1]}
        self.assertIn('Workspace 2 · Front · Visible', choices['0xa'].detail)
        self.assertIn('Workspace 2 · Back · Hidden', choices['0xb'].detail)
        self.assertEqual(set(choices), {'0xa', '0xb', '0xc'})

    def test_fullscreen_blocker_and_empty_cards_give_clear_feedback(self):
        ipc = IPC()
        flow = w.Find(ipc, Picker('0xb'))
        plan = flow.prepare()
        ipc.clients['0xd'] = window('0xd', fullscreen=2)
        with self.assertRaisesRegex(w.SetupError, 'Leave fullscreen'): flow.apply(plan)
        self.assertEqual(ipc.mutations, [])
        ipc.snapshot['containers'] = []
        with self.assertRaisesRegex(w.SetupError, 'No cards are open'): w.Find(ipc, Picker()).prepare()


if __name__ == '__main__': unittest.main()
