"""User choices and saved preferences must remain reversible and plain data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from edit_test import CardIPC
from setup_test import IPC, Picker, setup


class TransitionsTest(unittest.TestCase):
    def test_cancel_while_selecting_floating_apps_never_mutates_them(self):
        for answers in ((None,), ('0xb', None)):
            ipc = IPC(); ipc.snapshot['workspace_protection'] = True
            ipc.clients['0xa']['floating'] = True
            picker = Picker(*answers)
            with self.assertRaises(setup.Cancelled): setup.Setup(ipc, picker).prepare('0xa')
            self.assertEqual(ipc.mutations, [])
            self.assertTrue(ipc.clients['0xa']['floating'])

    def test_floating_creation_needs_no_extra_confirmation(self):
        for extra in (False, True):
            ipc = IPC(); ipc.snapshot['workspace_protection'] = True
            for window in ipc.clients.values(): window['floating'] = True
            if not extra: del ipc.clients['0xc']
            picker = Picker('0xb', *(['create'] if extra else []))
            selected = setup.Setup(ipc, picker).prepare('0xa')
            self.assertEqual(list(selected), ['0xa', '0xb'])
            self.assertEqual(len(picker.prompts), 2 if extra else 1)
            self.assertEqual(ipc.mutations, [])
            self.assertTrue(all(w['floating'] for w in ipc.clients.values()))

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
