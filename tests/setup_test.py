"""Check selection, cancellation and stale-window protection without a desktop."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('hyprflip_setup', Path(__file__).resolve().parent.parent / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup
spec.loader.exec_module(setup)


def window(address, **overrides):
    return dict(address=address, pid=int(address, 16), **({'class': 'foot', 'title': 'Terminal',
                'workspace': {'id': 2, 'name': '2'}, 'floating': False, 'grouped': [],
                'fullscreen': 0, 'mapped': True, 'hidden': False, 'focusHistoryID': 1} | overrides))


class IPC:
    def __init__(self):
        self.clients = {a: window(a) for a in ('0xa', '0xb', '0xc')}
        self.snapshot = dict(containers=[], pairs=[], marked='0xc', container_provider=True, container_max_panes=3)
        self.mutations = []

    def windows(self): return self.clients
    def status(self): return self.snapshot
    def data(self, *args):
        if args == ('-j', 'workspaces'): return [{'id': 2, 'tiledLayout': 'hy3'}]
        if args == ('-j', 'activeworkspace'): return {'id': 2}
        raise AssertionError(args)
    def focus(self, address): self.mutations.append(('focus', address))
    def action(self, action): self.mutations.append(('action', action))


class Picker:
    def __init__(self, *answers): self.answers, self.prompts = iter(answers), []
    def choose(self, prompt, choices):
        self.prompts.append((prompt, choices))
        answer = next(self.answers)
        if answer is None: raise setup.Cancelled()
        return answer


class SetupTest(unittest.TestCase):
    def test_cancel_at_either_picker_does_not_touch_marks_focus_or_layout(self):
        for answers in ((None,), ('0xb', None)):
            ipc = IPC()
            with self.assertRaises(setup.Cancelled):
                setup.Setup(ipc, Picker(*answers)).prepare('0xa')
            self.assertEqual(ipc.mutations, [])
            self.assertEqual(ipc.snapshot['marked'], '0xc')

    def test_choose_one_or_two_reverse_windows_without_mutation(self):
        for last, expected in (('create', ['0xa', '0xb']), ('0xc', ['0xa', '0xb', '0xc'])):
            ipc, picker = IPC(), Picker('0xb', last)
            self.assertEqual(list(setup.Setup(ipc, picker).prepare('0xa')), expected)
            self.assertEqual(ipc.mutations, [])
            self.assertEqual(picker.prompts[1][1][0].value, 'create')

    def test_only_one_candidate_needs_one_choice(self):
        ipc = IPC()
        del ipc.clients['0xc']
        picker = Picker('0xb')
        self.assertEqual(list(setup.Setup(ipc, picker).prepare('0xa')), ['0xa', '0xb'])
        self.assertEqual(len(picker.prompts), 1)

    def test_third_app_is_optional_and_cancellable_before_any_mutation(self):
        for last, expected in (('create', ['0xa', '0xb', '0xc']), ('0xd', ['0xa', '0xb', '0xc', '0xd']),
                               (None, None)):
            ipc, picker = IPC(), Picker('0xb', '0xc', last)
            ipc.clients['0xd'] = window('0xd')
            flow = setup.Setup(ipc, picker)
            if expected is None:
                with self.assertRaises(setup.Cancelled): flow.prepare('0xa')
            else:
                self.assertEqual(list(flow.prepare('0xa')), expected)
            self.assertIn('third app', picker.prompts[2][0])
            self.assertEqual([c.value for c in picker.prompts[2][1]], ['create', '0xd'])
            self.assertEqual(picker.prompts[2][1][0].label, 'Only two apps')
            self.assertEqual(ipc.mutations, [])

    def test_owned_floating_and_special_workspace_windows_are_excluded(self):
        ipc = IPC()
        ipc.clients.update({'0xd': window('0xd', floating=True),
                            '0xe': window('0xe', workspace={'id': -98, 'name': 'special:scratch'}),
                            '0xf': window('0xf', grouped=['0xf', '0x10']),
                            '0x11': window('0x11', fullscreen=2)})
        ipc.snapshot['containers'] = [{'faces': [['0xb'], ['0xc']]}]
        with self.assertRaisesRegex(setup.SetupError, 'Open another ungrouped, tiled app'):
            setup.Setup(ipc, Picker()).prepare('0xa')
        self.assertEqual(ipc.mutations, [])

    def test_remote_workspaces_follow_local_apps_in_numeric_order(self):
        ipc = IPC()
        ipc.clients.update({'0xd': window('0xd', workspace={'id': 10, 'name': '10'}),
                            '0xe': window('0xe', workspace={'id': 3, 'name': '3'})})
        picker = Picker('workspace:3', '0xe', 'create')
        selected = setup.Setup(ipc, picker).prepare('0xa')
        self.assertEqual(list(selected), ['0xa', '0xe'])
        self.assertEqual([c.value for c in picker.prompts[0][1]], ['0xb', '0xc', 'workspace:3', 'workspace:10'])
        self.assertEqual(picker.prompts[0][1][-2].label, 'Add from workspace 3')
        self.assertIn('move an app here', picker.prompts[1][0])
        self.assertEqual(ipc.mutations, [])

    def test_back_from_workspace_menu_and_escape_never_move_apps(self):
        for answers in (('workspace:3', None), ('workspace:3', 'back', None),
                        ('0xb', 'workspace:3', None)):
            ipc = IPC()
            ipc.clients['0xd'] = window('0xd', workspace={'id': 3, 'name': '3'})
            with self.assertRaises(setup.Cancelled):
                setup.Setup(ipc, Picker(*answers)).prepare('0xa')
            self.assertEqual(ipc.mutations, [])
            self.assertEqual(ipc.clients['0xd']['workspace']['id'], 3)

    def test_stale_selection_is_rejected_before_mutation(self):
        for change in ('close', 'move', 'reuse', 'group'):
            ipc = IPC()
            flow = setup.Setup(ipc, Picker('0xb', 'create'))
            chosen = flow.prepare('0xa')
            ipc.clients = {k: dict(v) for k, v in ipc.clients.items()}
            if change == 'close': del ipc.clients['0xb']
            if change == 'move': ipc.clients['0xb']['workspace'] = {'id': 7, 'name': '7'}
            if change == 'reuse': ipc.clients['0xb']['pid'] = 100
            if change == 'group': ipc.clients['0xb']['grouped'] = ['0xb', '0xc']
            with self.assertRaisesRegex(setup.SetupError, 'closed, moved or joined'):
                flow.apply(chosen)
            self.assertEqual(ipc.mutations, [])

    def test_duplicate_titles_stay_distinguishable_and_control_text_is_plain(self):
        choices = setup.window_choices([window('0xa'), window('0xb')])
        self.assertNotEqual(choices[0].label, choices[1].label)
        self.assertEqual(setup.clean('one\ttwo\nthree\u202efour'), 'one two three four')

    def test_new_request_supersedes_waiting_request(self):
        with tempfile.TemporaryDirectory() as directory:
            first = setup.Request(Path(directory), 'instance')
            second = setup.Request(Path(directory), 'instance')
            first.start(); second.start()
            with self.assertRaises(setup.Cancelled): first.check()
            first.finish(); second.check(); second.finish()
            self.assertFalse(second.current.exists())

    def test_menu_round_trip_keeps_titles_out_of_shell_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = setup.Request(root, 'instance'); request.start()
            title = 'Backticks `touch nope` and $(touch nope)'
            choice = setup.Choice('0xb', 'Brave', title)
            def run(command, **kwargs):
                self.assertEqual(command[:4], ['omarchy-shell', 'shell', 'summon', 'omarchy.menu'])
                payload = json.loads(command[4])
                self.assertEqual(payload['options'], ['\tBrave\t' + title])
                Path(payload['selectionFile']).write_text('Brave\t' + title + '\n')
                Path(payload['doneFile']).touch()
                return subprocess.CompletedProcess(command, 0, 'ok\n', '')
            with patch('subprocess.run', side_effect=run):
                self.assertEqual(setup.OmarchyMenu(root, request).choose('Choose', [choice]), '0xb')
            request.finish()


if __name__ == '__main__': unittest.main()
