"""User choices and saved preferences must remain reversible and plain data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from edit_test import CardIPC
from setup_test import IPC, Picker, setup


class TransitionsTest(unittest.TestCase):
    def test_floating_choices_have_a_final_cancel_before_any_mutation(self):
        for answer in ('cancel', None):
            ipc = IPC(); ipc.snapshot['workspace_protection'] = True
            ipc.clients['0xa']['floating'] = True
            picker = Picker('0xb', 'create', answer)
            with self.assertRaises(setup.Cancelled): setup.Setup(ipc, picker).prepare('0xa')
            self.assertEqual(ipc.mutations, [])
            self.assertEqual(picker.prompts[-1][1][0].label, 'Tile and create card')

    def test_preview_and_back_do_not_save_the_previewed_mode(self):
        ipc = CardIPC()
        ipc.snapshot.update(transition='flip', transition_modes=list(setup.TRANSITIONS))
        picker = Picker('transition', 'portal', 'preview', 'back', 'fade', 'use')
        flow = setup.Edit(ipc, picker)
        before = deepcopy(ipc.snapshot['containers'])
        plan = flow.prepare('0xb')
        self.assertIn(('action', 'preview portal'), ipc.mutations)
        self.assertEqual(ipc.snapshot['transition'], 'flip')
        self.assertEqual(ipc.snapshot['containers'], before)
        saved = []
        ipc.save_transition = saved.append
        flow.apply(plan)
        self.assertEqual(saved, ['fade'])

    def test_escaping_a_transition_picker_keeps_the_existing_preference(self):
        for answers in (('transition', None), ('transition', 'portal', None)):
            ipc = CardIPC(); ipc.snapshot.update(transition='slide', transition_modes=list(setup.TRANSITIONS))
            with self.assertRaises(setup.Cancelled): setup.Edit(ipc, Picker(*answers)).prepare('0xb')
            self.assertEqual(ipc.snapshot['transition'], 'slide')
            self.assertEqual(ipc.mutations, [])

    def test_unfolded_cards_can_change_mode_without_a_mutating_preview(self):
        ipc = CardIPC(); ipc.snapshot.update(transition='flip', transition_modes=list(setup.TRANSITIONS))
        ipc.snapshot['containers'][0]['unfolded'] = True
        picker = Picker('transition', 'fade', 'use')
        setup.Edit(ipc, picker).prepare('0xb')
        self.assertNotIn('preview', [c.value for c in picker.prompts[-1][1]])
        self.assertTrue(ipc.snapshot['containers'][0]['unfolded'])

    def test_preference_is_plain_data_and_failed_apply_restores_the_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = setup.Hyprctl({'XDG_STATE_HOME': directory})
            ipc.status = lambda: {'transition': 'flip'}
            path = Path(directory) / 'hyprflip/transition'
            path.parent.mkdir(); path.write_text('flip\n')
            ipc.call = lambda *args: None
            with self.assertRaises(setup.SetupError): ipc.save_transition('portal')
            self.assertEqual(path.read_text(), 'flip\n')
            with self.assertRaises(setup.SetupError): ipc.save_transition('fade"; os.execute("oops")')
            self.assertEqual(path.read_text(), 'flip\n')
            count = 0
            def state():
                nonlocal count
                count += 1
                return {'transition': 'flip' if count == 1 else 'portal'}
            ipc.status = state
            ipc.save_transition('portal')
            self.assertEqual(path.read_text(), 'portal\n')
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == '__main__': unittest.main()
