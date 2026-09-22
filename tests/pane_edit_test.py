"""Pane order and replacement choices, stale guards and reversible import failure."""
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

from repair_test import RepairIPC
from saved_test import Menu
from setup_test import setup, window


class PaneIPC(RepairIPC):
    def __init__(self):
        super().__init__()
        self.snapshot.update(pane_replacement=True, layout_controls=True)
        self.clients['0xe'] = window('0xe')
        self.lost_reply = False
        for i, (a, w) in enumerate(self.clients.items()):
            w.update({'class': 'App-' + a, 'title': 'Title ' + a, 'at': [i * 500,0], 'size': [500,700]})

    def action(self, action):
        super().action(action)
        if action.startswith('replace '):
            _, old, new = action.split(); side = self.card['active']
            index = self.card['faces'][side].index(old)
            self.card['faces'][side][index] = new
            if self.card['layouts'][side]['focused'] == old:
                self.card['layouts'][side]['focused'] = new
                self.card['current'] = new; self.active = new
            if self.snapshot['marked'] == new: self.snapshot['marked'] = None
            if self.lost_reply: raise setup.SetupError('IPC reply lost')


class PaneEditTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.ipc = PaneIPC(); self.ipc.env = {'XDG_STATE_HOME': directory.name}

    def prepare(self, *answers):
        flow = setup.Edit(self.ipc, Menu(*answers)); return flow, flow.prepare(self.ipc.active)

    def test_two_panes_swap_in_one_layout_choice_with_sizes_attached_to_slots(self):
        self.ipc.remove('0xd', close=False)
        self.ipc.card['layouts'][1]['ratios'] = [.3,.7]
        flow, plan = self.prepare('layout', 'reorder')
        self.assertEqual(len(flow.menu.prompts), 2)
        self.assertEqual(flow.menu.prompts[1][1][-1].label, 'Swap app positions')
        self.assertEqual(self.ipc.mutations, [])
        flow.apply(plan)
        self.assertEqual(self.ipc.card['faces'][1], ['0xc','0xb'])
        self.assertEqual(self.ipc.card['layouts'][1]['ratios'], [.3,.7])
        self.assertEqual(self.ipc.active, '0xb')

    def test_three_pane_direction_labels_and_all_neighbor_moves(self):
        for axis in ('horizontal','vertical'):
            for move in ('0:1','1:0','1:2','2:1'):
                with self.subTest(axis=axis, move=move):
                    self.ipc.card['faces'][1] = ['0xb','0xc','0xd']
                    self.ipc.card['layouts'][1].update(axis=axis, ratios=[.2,.3,.5])
                    flow, plan = self.prepare('layout','reorder',move)
                    options = flow.menu.prompts[2][1]
                    self.assertEqual([c.value for c in options], ['0:1','1:0','1:2','2:1'])
                    self.assertIn('right' if axis == 'horizontal' else 'down', options[0].label)
                    flow.apply(plan)
                    expected = ['0xb','0xc','0xd']; a,b = map(int, move.split(':')); expected[a],expected[b] = expected[b],expected[a]
                    self.assertEqual(self.ipc.card['faces'][1], expected)
                    self.assertEqual(self.ipc.card['layouts'][1]['ratios'], [.2,.3,.5])
                    self.assertEqual(self.ipc.active, '0xb')

    def test_reorder_refuses_a_resize_while_the_menu_is_open(self):
        flow, plan = self.prepare('layout','reorder','0:1')
        self.ipc.card['layouts'][1]['ratios'] = [.4,.4,.2]
        with self.assertRaisesRegex(setup.SetupError, 'split changed'): flow.apply(plan)
        self.assertTrue(all(m[0] == 'action' and m[1].split()[0] in ('reserve','unreserve') for m in self.ipc.mutations))
        self.assertEqual(self.ipc.card['faces'][1], ['0xb','0xc','0xd'])

    def test_replace_on_full_face_keeps_slot_weights_and_unfocused_target_does_not_steal_focus(self):
        before = deepcopy(self.ipc.card); self.ipc.snapshot['marked'] = '0xe'
        flow, plan = self.prepare('replace','0xc','0xe')
        self.assertNotIn('add', [c.value for c in flow.menu.prompts[0][1]])
        flow.apply(plan)
        self.assertEqual(self.ipc.card['faces'], [['0xa'],['0xb','0xe','0xd']])
        self.assertEqual(self.ipc.card['id'], before['id'])
        self.assertEqual(self.ipc.card['layouts'], before['layouts'])
        self.assertEqual(self.ipc.active, '0xb'); self.assertIn('0xc', self.ipc.clients)
        self.assertIsNone(self.ipc.snapshot['marked'])

    def test_replacing_the_only_app_on_a_face_keeps_card_and_focuses_replacement(self):
        self.ipc.focus('0xa'); self.ipc.mutations.clear()
        flow, plan = self.prepare('replace','0xe')
        self.assertEqual(len(flow.menu.prompts), 2)
        self.assertEqual(plan.removal, '0xa')
        flow.apply(plan)
        self.assertEqual(self.ipc.card['faces'], [['0xe'],['0xb','0xc','0xd']])
        self.assertEqual(self.ipc.active, '0xe')
        self.assertIn('0xa', self.ipc.clients)
        self.assertFalse(any(m == ('action','unpair') for m in self.ipc.mutations))

    def test_unfolded_replacement_retains_state_and_other_face_selection(self):
        self.ipc.card['unfolded'] = True
        flow, plan = self.prepare('replace','0xb','0xe'); flow.apply(plan)
        self.assertTrue(self.ipc.card['unfolded'])
        self.assertEqual(self.ipc.card['layouts'][0]['focused'], '0xa')
        self.assertEqual(self.ipc.active, '0xe')

    def test_remote_float_selection_and_cancellation_do_not_mutate_before_apply(self):
        self.ipc.clients['0xe'].update(workspace={'id':8,'name':'8'}, floating=True)
        for answers in (('replace',None), ('replace','0xc',None), ('replace','0xc','workspace:8',None)):
            with self.subTest(answers=answers):
                with self.assertRaises(setup.Cancelled): self.prepare(*answers)
                self.assertEqual(self.ipc.mutations, [])
        flow, plan = self.prepare('replace','0xc','workspace:8','0xe')
        self.assertEqual(self.ipc.mutations, [])
        flow.apply(plan)
        self.assertEqual(self.ipc.clients['0xe']['workspace']['id'], 2)
        self.assertFalse(self.ipc.clients['0xe']['floating'])
        self.assertEqual(self.ipc.clients['0xc']['workspace']['id'], 2)

    def test_failed_replacement_returns_import_and_float_and_keeps_mark(self):
        self.ipc.clients['0xe'].update(workspace={'id':8,'name':'8'}, floating=True)
        self.ipc.snapshot['marked'] = '0xe'
        before = deepcopy(self.ipc.card)
        flow, plan = self.prepare('replace','0xc','workspace:8','0xe')
        self.ipc.fail = lambda action: action.startswith('replace ')
        with self.assertRaisesRegex(setup.SetupError, 'Injected layout failure'): flow.apply(plan)
        self.assertEqual(self.ipc.card, before)
        self.assertEqual(self.ipc.clients['0xe']['workspace']['id'], 8)
        self.assertTrue(self.ipc.clients['0xe']['floating'])
        self.assertEqual(self.ipc.active, '0xb'); self.assertEqual(self.ipc.snapshot['marked'], '0xe')

    def test_lost_success_reply_does_not_pull_the_new_member_out_of_the_card(self):
        self.ipc.clients['0xe'].update(workspace={'id':8,'name':'8'}, floating=True)
        flow, plan = self.prepare('replace','0xb','workspace:8','0xe')
        self.ipc.lost_reply = True; flow.apply(plan)
        self.assertEqual(self.ipc.card['faces'][1], ['0xe','0xc','0xd'])
        self.assertEqual(self.ipc.active, '0xe')
        self.assertEqual(self.ipc.clients['0xe']['workspace']['id'], 2)
        self.assertFalse(self.ipc.clients['0xe']['floating'])

    def test_import_time_stale_card_and_candidate_identity_are_rechecked(self):
        for kind in ('ratio','pid','closed'):
            with self.subTest(kind=kind):
                ipc = PaneIPC(); ipc.env = self.ipc.env
                ipc.clients['0xe']['workspace'] = {'id':8,'name':'8'}
                flow = setup.Edit(ipc, Menu('replace','0xc','workspace:8','0xe')); plan = flow.prepare('0xb')
                move = ipc.move
                def changed(a, ws):
                    move(a, ws)
                    if kind == 'ratio': ipc.card['layouts'][1]['ratios'] = [.3,.3,.4]
                    if kind == 'pid': ipc.clients['0xe']['pid'] += 10
                    if kind == 'closed': ipc.clients.pop('0xc', None)
                with patch.object(ipc, 'move', side_effect=changed):
                    with self.assertRaises(setup.SetupError): flow.apply(plan)
                self.assertFalse(any(m[0] == 'action' and m[1].startswith('replace ') for m in ipc.mutations))
                self.assertEqual(ipc.card['faces'][1], ['0xb','0xc','0xd'])

    def test_replacement_picker_excludes_cards_and_groups(self):
        self.ipc.clients['0xe']['grouped'] = ['0xe','0xf']
        with self.assertRaisesRegex(setup.SetupError, 'Open an ungrouped app'): self.prepare('replace','0xb')
        self.assertEqual(self.ipc.mutations, [])

    def test_reordering_and_replacing_do_not_silently_update_saved_definition(self):
        store = setup.RecipeStore(self.ipc.env)
        recipe = setup.Saved.capture(self.ipc.card, self.ipc.windows()); store.update('Comms',recipe,None)
        flow, plan = self.prepare('layout','reorder','0:1'); flow.apply(plan)
        flow, plan = self.prepare('replace','0xd','0xe'); flow.apply(plan)
        self.assertEqual(store.read()['Comms'], recipe)


if __name__ == '__main__': unittest.main()
