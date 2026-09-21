"""Check edit decisions and stale-card guards without changing a desktop."""
from copy import deepcopy
import unittest

from setup_test import IPC, Picker, setup, window


class CardIPC(IPC):
    def __init__(self, full=False):
        super().__init__()
        self.clients['0xd'] = window('0xd')
        self.clients['0xb']['size'] = [1000, 700]
        self.snapshot.update(containers=[dict(id=1, faces=[['0xa'], ['0xb', '0xc'] if full else ['0xb']],
                                             current='0xb', active=1, unfolded=False, box=[0, 0, 1000, 700])])
        self.active, self.workspace = '0xb', 2
        self.refuse_attach = False

    def data(self, *args):
        if args == ('-j', 'activewindow'): return {'address': self.active}
        if args == ('-j', 'activeworkspace'): return {'id': self.workspace}
        return super().data(*args)

    def focus(self, address):
        super().focus(address)
        self.active = address

    def action(self, action):
        super().action(action)
        if action == 'mark': self.snapshot['marked'] = self.active
        if action == 'cancel': self.snapshot['marked'] = None
        if action.startswith('other_side '): self.active = action.split()[1]
        if action.startswith('attach ') and self.refuse_attach:
            raise setup.SetupError('This split is too small for the applications.')

    def move(self, address, workspace):
        self.mutations.append(('move', address, workspace))
        self.clients[address]['workspace'] = {'id': workspace, 'name': str(workspace)}


class EditTest(unittest.TestCase):
    def test_layout_and_transfer_choices_are_capability_gated_and_target_the_chosen_pane(self):
        ipc = CardIPC(full=True)
        for index, w in enumerate(ipc.clients.values()): w['at'] = [index * 600, 0]
        ipc.snapshot['layout_controls'] = True
        for answers, target, action in ((('layout', 'layout vertical'), '0xb', 'layout vertical'),
                                         (('other_side', '0xc'), '0xc', 'other_side 0xc')):
            ipc.active = '0xb'; ipc.mutations.clear()
            flow = setup.Edit(ipc, Picker(*answers)); plan = flow.prepare('0xb'); flow.apply(plan)
            self.assertEqual(ipc.mutations, [('focus','0xb'), ('action',action)])
            self.assertEqual(ipc.active, target)
        ipc.snapshot['containers'][0]['faces'][0] = ['0xa','0xd','0xe']
        ipc.clients['0xe'] = window('0xe')
        ipc.active = '0xb'
        picker = Picker(None)
        with self.assertRaises(setup.Cancelled): setup.Edit(ipc, picker).prepare('0xb')
        self.assertNotIn('other_side', [c.value for c in picker.prompts[0][1]])

    def test_native_pair_explains_the_supported_layout(self):
        ipc = CardIPC()
        ipc.snapshot.update(containers=[], pairs=[{'front': '0xa', 'back': '0xb'}])
        with self.assertRaisesRegex(setup.SetupError, 'native window group'):
            setup.Edit(ipc, Picker()).prepare('0xb')
        self.assertEqual(ipc.mutations, [])

    def test_cancel_at_either_menu_preserves_card_and_mark(self):
        for answers in ((None,), ('add', None)):
            ipc = CardIPC()
            before = deepcopy(ipc.snapshot)
            with self.assertRaises(setup.Cancelled):
                setup.Edit(ipc, Picker(*answers)).prepare('0xb')
            self.assertEqual(ipc.snapshot, before)
            self.assertEqual(ipc.mutations, [])

    def test_picker_excludes_both_faces_and_unavailable_apps(self):
        ipc = CardIPC()
        ipc.clients['0xd']['floating'] = True
        picker = Picker('add', '0xc')
        plan = setup.Edit(ipc, picker).prepare('0xb')
        self.assertEqual(plan.candidate, '0xc')
        self.assertEqual([c.value for c in picker.prompts[1][1]], ['0xc'])
        self.assertEqual(ipc.mutations, [])

    def test_two_app_side_offers_a_third_app_and_either_removal(self):
        ipc, picker = CardIPC(full=True), Picker('release:0xb')
        setup.Edit(ipc, picker).prepare('0xb')
        prompt, choices = picker.prompts[0]
        self.assertIn('2 apps on this side', prompt)
        self.assertEqual([c.value for c in choices], ['add', 'release:0xb', 'release:0xc', 'save', 'manage', 'saved'])
        self.assertIn('Keep open', choices[1].detail)

    def test_full_side_offers_all_three_removals_and_no_add(self):
        ipc, picker = CardIPC(full=True), Picker('release:0xd')
        ipc.snapshot['containers'][0]['faces'][1].append('0xd')
        flow = setup.Edit(ipc, picker)
        plan = flow.prepare('0xb')
        prompt, choices = picker.prompts[0]
        self.assertIn('full (3 apps)', prompt)
        self.assertEqual([c.value for c in choices], ['release:0xb', 'release:0xc', 'release:0xd', 'save', 'manage', 'saved'])
        flow.apply(plan)
        self.assertEqual(ipc.active, '0xb')

    def test_older_provider_keeps_its_two_app_limit(self):
        ipc, picker = CardIPC(full=True), Picker('release:0xb')
        del ipc.snapshot['container_max_panes']
        setup.Edit(ipc, picker).prepare('0xb')
        self.assertIn('full (2 apps)', picker.prompts[0][0])
        self.assertNotIn('add', [c.value for c in picker.prompts[0][1]])

    def test_last_app_uses_explicit_ungroup_wording(self):
        ipc, picker = CardIPC(), Picker('unpair')
        flow = setup.Edit(ipc, picker)
        plan = flow.prepare('0xb')
        ungroup = next(c for c in picker.prompts[0][1] if c.value == 'unpair')
        self.assertEqual(ungroup.label, 'Ungroup card')
        self.assertIn('All apps stay open', ungroup.detail)
        flow.apply(plan)
        self.assertIn(('action', 'unpair'), ipc.mutations)

    def test_no_candidates_explains_how_to_add_one_without_mutation(self):
        ipc = CardIPC()
        del ipc.clients['0xc'], ipc.clients['0xd']
        with self.assertRaisesRegex(setup.SetupError, 'Open another ungrouped, tiled app'):
            setup.Edit(ipc, Picker('add')).prepare('0xb')
        self.assertEqual(ipc.mutations, [])

    def test_changed_card_or_app_aborts_before_focus_mark_or_layout_mutation(self):
        for change in ('card', 'flip', 'unfold', 'close', 'reuse', 'move', 'candidate_group', 'focus', 'workspace', 'fullscreen'):
            with self.subTest(change=change):
                ipc = CardIPC()
                flow = setup.Edit(ipc, Picker('add', '0xc'))
                plan = flow.prepare('0xb')
                if change == 'card': ipc.snapshot['containers'][0]['faces'][1].append('0xd')
                if change == 'flip': ipc.snapshot['containers'][0]['active'] = 0
                if change == 'unfold': ipc.snapshot['containers'][0]['unfolded'] = True
                if change == 'close': del ipc.clients['0xa']
                if change == 'reuse': ipc.clients['0xc']['pid'] = 100
                if change == 'move': ipc.clients['0xc']['workspace'] = {'id': 7, 'name': '7'}
                if change == 'candidate_group': ipc.clients['0xc']['grouped'] = ['0xc', '0xd']
                if change == 'focus': ipc.active = '0xd'
                if change == 'workspace': ipc.workspace = 7
                if change == 'fullscreen': ipc.clients['0xd']['fullscreen'] = 2
                with self.assertRaises(setup.SetupError): flow.apply(plan)
                self.assertEqual(ipc.mutations, [])

    def test_failed_attach_preserves_existing_card_restores_mark_and_focus(self):
        ipc = CardIPC()
        ipc.snapshot['marked'] = '0xd'
        before = deepcopy(ipc.snapshot)
        flow = setup.Edit(ipc, Picker('add', '0xc'))
        plan = flow.prepare('0xb')
        ipc.refuse_attach = True
        with self.assertRaisesRegex(setup.SetupError, 'too small'): flow.apply(plan)
        self.assertEqual(ipc.snapshot, before)
        self.assertEqual(ipc.active, '0xb')
        self.assertNotIn(('action', 'unpair'), ipc.mutations)

    def test_unfolded_card_targets_the_focused_face_and_its_dimensions(self):
        ipc = CardIPC()
        ipc.snapshot['containers'][0]['unfolded'] = True
        ipc.clients['0xb']['size'] = [500, 900]
        flow = setup.Edit(ipc, Picker('add', '0xc'))
        flow.apply(flow.prepare('0xb'))
        self.assertIn(('action', 'attach vertical'), ipc.mutations)
        self.assertEqual(ipc.active, '0xc')

    def test_remove_other_pane_keeps_focus_on_the_original_app(self):
        ipc = CardIPC(full=True)
        flow = setup.Edit(ipc, Picker('release:0xc'))
        plan = flow.prepare('0xb')
        self.assertEqual(plan.removal, '0xc')
        flow.apply(plan)
        self.assertIn(('focus', '0xc'), ipc.mutations)
        self.assertEqual(ipc.mutations[-1], ('focus', '0xb'))
        self.assertEqual(ipc.active, '0xb')

    def test_cross_workspace_selection_moves_only_after_the_final_choice(self):
        ipc = CardIPC()
        ipc.clients['0xc']['workspace'] = {'id': 7, 'name': '7'}
        flow = setup.Edit(ipc, Picker('add', 'workspace:7', '0xc'))
        selected = flow.prepare('0xb')
        self.assertEqual(ipc.mutations, [])
        flow.apply(selected)
        self.assertIn(('move', '0xc', 2), ipc.mutations)
        self.assertEqual(ipc.clients['0xc']['workspace']['id'], 2)
        self.assertEqual(ipc.active, '0xc')

    def test_failed_import_returns_app_to_its_original_workspace(self):
        ipc = CardIPC()
        ipc.snapshot['marked'] = '0xd'
        ipc.clients['0xc']['workspace'] = {'id': 7, 'name': '7'}
        flow = setup.Edit(ipc, Picker('add', 'workspace:7', '0xc'))
        selected = flow.prepare('0xb')
        before = deepcopy(ipc.snapshot)
        ipc.refuse_attach = True
        with self.assertRaisesRegex(setup.SetupError, 'too small'): flow.apply(selected)
        self.assertEqual(ipc.clients['0xc']['workspace']['id'], 7)
        self.assertEqual(ipc.snapshot, before)
        self.assertEqual(ipc.active, '0xb')

    def test_remote_app_moving_after_selection_invalidates_the_import(self):
        ipc = CardIPC()
        ipc.clients['0xc']['workspace'] = {'id': 7, 'name': '7'}
        flow = setup.Edit(ipc, Picker('add', 'workspace:7', '0xc'))
        selected = flow.prepare('0xb')
        ipc.clients['0xc']['workspace'] = {'id': 8, 'name': '8'}
        with self.assertRaises(setup.SetupError): flow.apply(selected)
        self.assertEqual(ipc.mutations, [])


if __name__ == '__main__': unittest.main()
