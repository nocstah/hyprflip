"""Installed launcher resolution and saved-card opening without a live desktop."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from edit_test import CardIPC
from saved_test import Menu
from setup_test import setup, window


class OpeningTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ipc = CardIPC(full=True)
        self.ipc.env = {'XDG_STATE_HOME': str(self.root / 'state'), 'XDG_DATA_HOME': str(self.root / 'data'),
                        'XDG_DATA_DIRS': str(self.root / 'system')}
        for index, (address, w) in enumerate(self.ipc.clients.items()):
            w.update({'class': 'app-' + address, 'initialClass': 'app-' + address,
                      'title': 'Title ' + address, 'size': [600,700], 'at': [index*610,0]})
        self.original = deepcopy(self.ipc.clients)
        self.recipe = setup.Saved.capture(self.ipc.snapshot['containers'][0], self.ipc.windows())
        self.store = setup.RecipeStore(self.ipc.env); self.store.update('Comms', self.recipe, None)
        self.ipc.snapshot['containers'] = []
        self.ipc.active = '0xd'
        for a in ('a','b','c'): self.desktop(a + '.desktop', 'App ' + a, 'app-0x' + a)

    def desktop(self, identifier, name, wm_class='', extra='', system=False):
        path = self.root / ('system' if system else 'data') / 'applications' / identifier
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Desktop Entry]\nType=Application\nName=' + name + '\nStartupWMClass=' + wm_class +
                        '\nExec=example-app %U\n' + extra)
        return path

    def flow(self, *extra):
        flow = setup.Saved(self.ipc, Menu('0', 'open', *extra, 'open'))
        return flow, flow.prepare_restore()

    def test_existing_windows_are_reused_and_remote_windows_are_planned_for_import(self):
        self.ipc.clients['0xa']['workspace'] = {'id': 8, 'name': '8'}
        flow, plan = self.flow()
        with patch.object(setup.DesktopApps, 'launch') as launch, patch.object(flow, 'apply_reserved') as apply:
            flow.apply(plan)
        launch.assert_not_called()
        selected, arrangement, workspace = apply.call_args.args
        self.assertEqual(workspace, 2)
        self.assertEqual(selected['0xa']['workspace']['id'], 8)
        self.assertEqual(arrangement['faces'][1]['windows'], ['0xb', '0xc'])

    def test_missing_app_launches_once_and_records_only_installed_desktop_id(self):
        del self.ipc.clients['0xc']
        flow, plan = self.flow()
        def launched(entry):
            self.assertEqual(entry.id, 'c.desktop')
            self.ipc.clients['0xe'] = self.original['0xc'] | {'address': '0xe', 'pid': 22}
            self.ipc.active = '0xe'
            return Mock(poll=lambda: 0)
        with patch.object(setup.DesktopApps, 'launch', side_effect=launched) as launch, \
                patch.object(setup, 'Opening'), patch.object(flow, 'apply_reserved') as apply:
            flow.apply(plan)
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(apply.call_args.args[1]['faces'][1]['windows'], ['0xb','0xe'])
        saved = self.store.read()['Comms']['faces'][1]['apps'][1]
        self.assertEqual(saved['desktop_id'], 'c.desktop')
        self.assertNotIn('Exec', self.store.path.read_text())

    def test_open_card_is_focused_without_launching_or_rebuilding_it(self):
        self.ipc.snapshot['containers'] = [dict(id=1, faces=[['0xa'],['0xb','0xc']], current='0xc', active=1, unfolded=True)]
        flow = setup.Saved(self.ipc, Menu('0', 'open'))
        plan = flow.prepare_restore()
        self.assertEqual(plan.action, 'goto')
        with patch.object(setup.DesktopApps, 'launch') as launch: flow.apply(plan)
        launch.assert_not_called()
        self.assertEqual(self.ipc.mutations, [('focus','0xc')])
        self.assertIn('Go to open card', [c.label for c in flow.menu.prompts[1][1]])

    def test_ambiguous_existing_windows_require_selection(self):
        self.ipc.clients['0xe'] = self.ipc.clients['0xa'] | {'address':'0xe', 'pid':22}
        flow, plan = self.flow('0xe')
        self.assertEqual(plan.chosen[0], '0xe')
        self.assertEqual(plan.launchers, {})
        self.assertEqual(self.ipc.mutations, [])

    def test_an_app_in_another_card_is_not_launched_again(self):
        self.ipc.snapshot['containers'] = [dict(id=1, faces=[['0xa'],['0xd']], current='0xd', active=1)]
        with self.assertRaisesRegex(setup.SetupError, 'already open but unavailable'): self.flow()
        self.assertEqual(self.ipc.mutations, [])

    def test_missing_launcher_is_chosen_then_shown_in_review_before_launch(self):
        del self.ipc.clients['0xa']
        (self.root / 'data/applications/a.desktop').unlink()
        flow, plan = self.flow('b.desktop')
        self.assertEqual(plan.launchers[0].id, 'b.desktop')
        self.assertEqual(flow.menu.prompts[-1][1][1].detail, 'Launch App b')
        self.assertEqual(self.ipc.mutations, [])

    def test_cancel_failure_timeout_and_navigation_never_group_or_close_windows(self):
        del self.ipc.clients['0xc']
        for mode in ('cancel', 'failure', 'timeout', 'navigation'):
            with self.subTest(mode=mode):
                self.ipc.active = '0xd'
                flow, plan = self.flow()
                def launched(entry):
                    if mode == 'navigation': self.ipc.active = '0xffff'
                    return Mock(poll=lambda: 1 if mode == 'failure' else 0)
                with patch.object(setup.DesktopApps, 'launch', side_effect=launched), \
                        patch.object(setup, 'Opening') as progress, patch.object(flow, 'apply_reserved') as apply:
                    if mode == 'cancel': progress.return_value.check.side_effect = setup.Cancelled()
                    with self.assertRaises((setup.SetupError, setup.Cancelled)): flow.apply_open(plan, timeout=0)
                    apply.assert_not_called()
                self.assertEqual(self.ipc.mutations, [])
                self.assertEqual(self.ipc.snapshot['containers'], [])

    def test_new_request_can_cancel_while_waiting_without_holding_its_lock(self):
        del self.ipc.clients['0xc']
        flow, plan = self.flow()
        runtime = self.root / 'runtime'; runtime.mkdir()
        request = setup.Request(runtime, 'test-instance'); request.start(); flow.menu.request = request
        replacement = setup.Request(runtime, 'test-instance')
        def cancel_wait(): replacement.start()  # Would block forever if launch wait held the flock.
        with patch.object(setup.DesktopApps, 'launch', return_value=Mock(poll=lambda: 0)), \
                patch.object(setup, 'Opening') as progress, patch.object(flow, 'apply_reserved') as apply:
            progress.return_value.check.side_effect = cancel_wait
            with self.assertRaises(setup.Cancelled): flow.apply_open(plan, timeout=1)
            apply.assert_not_called()
        request.finish(); replacement.check(); replacement.finish()

    def test_window_changed_during_launch_is_refused_by_restore_validation(self):
        del self.ipc.clients['0xc']
        flow, plan = self.flow()
        def launched(entry):
            self.ipc.clients['0xe'] = self.original['0xc'] | {'address':'0xe', 'pid':22}
            self.ipc.clients['0xa']['pid'] += 100
            return Mock(poll=lambda: 0)
        with patch.object(setup.DesktopApps, 'launch', side_effect=launched), patch.object(setup, 'Opening'):
            with self.assertRaisesRegex(setup.SetupError, 'selected window closed'): flow.apply(plan)
        self.assertEqual(self.ipc.mutations, [])
        self.assertIn('0xe', self.ipc.clients)

    def test_wrong_launcher_or_multiple_new_windows_do_not_get_guessed(self):
        del self.ipc.clients['0xc']
        flow, plan = self.flow()
        def launched(entry):
            for address in ('0xe','0xf'):
                self.ipc.clients[address] = self.original['0xc'] | {'address':address, 'pid':22, 'title':'New title'}
            return Mock(poll=lambda: 0)
        with patch.object(setup.DesktopApps, 'launch', side_effect=launched), patch.object(setup, 'Opening'), \
                patch.object(flow, 'apply_reserved') as apply:
            with self.assertRaisesRegex(setup.SetupError, 'Restore from open apps'): flow.apply_open(plan, timeout=0)
            apply.assert_not_called()

    def test_user_launcher_precedence_hidden_mask_and_ambiguous_inference(self):
        self.desktop('a.desktop', 'System A', 'app-0xa', system=True)
        self.desktop('hide.desktop', 'Hidden', 'hidden', 'Hidden=true\n')
        self.desktop('hide.desktop', 'System Hidden', 'hidden', system=True)
        self.desktop('invisible.desktop', 'Helper', 'helper', 'NoDisplay=true\n')
        catalog = setup.DesktopApps(self.ipc.env)
        self.assertEqual(catalog.apps['a.desktop'].name, 'App a')
        self.assertNotIn('hide.desktop', catalog.apps)
        self.assertFalse(catalog.apps['invisible.desktop'].visible)
        self.assertEqual(catalog.infer(self.recipe['faces'][0]['apps'][0]).id, 'a.desktop')
        self.desktop('duplicate.desktop', 'Duplicate', 'app-0xa')
        self.assertIsNone(setup.DesktopApps(self.ipc.env).infer(self.recipe['faces'][0]['apps'][0]))

    def test_gio_receives_only_a_validated_path_and_changed_launcher_is_refused(self):
        catalog = setup.DesktopApps(self.ipc.env); entry = catalog.apps['a.desktop']
        with patch.object(setup.subprocess, 'Popen') as popen:
            catalog.launch(entry)
            self.assertEqual(popen.call_args.args[0], ['gio','launch',str(entry.path)])
            self.assertNotIn('shell', popen.call_args.kwargs)
        entry.path.write_text(entry.path.read_text() + '\nComment=Changed\n')
        with patch.object(setup.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(setup.SetupError, 'launcher changed'): catalog.launch(entry)
            popen.assert_not_called()
        for identifier in ('../a.desktop', '/tmp/a.desktop', 'a\\b.desktop', 'a\n.desktop'):
            recipe = deepcopy(self.recipe); recipe['faces'][0]['apps'][0]['desktop_id'] = identifier
            with self.assertRaises(ValueError): setup.RecipeStore.validate(recipe)


if __name__ == '__main__': unittest.main()
