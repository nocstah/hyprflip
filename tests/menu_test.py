"""Desktop selection, cancellation and data boundaries without a compositor."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from setup_test import setup as w


class MenuDetectionTest(unittest.TestCase):
    def which(self, *names):
        return patch.object(w.shutil, 'which', side_effect=lambda name, **kw: '/bin/' + name if name in names else None)

    def test_responding_omarchy_is_preferred_and_fallbacks_have_stable_order(self):
        with self.which('fuzzel', 'rofi', 'wofi'):
            self.assertEqual(w.select_menu_backend({}, True), 'omarchy')
            self.assertEqual(w.select_menu_backend({}, False), 'fuzzel')
        with self.which('rofi', 'wofi'):
            self.assertEqual(w.select_menu_backend({}, False), 'rofi')
        with self.which('wofi'):
            self.assertEqual(w.select_menu_backend({}, False), 'wofi')

    def test_binary_presence_does_not_mean_the_shell_is_running(self):
        for reply in (subprocess.CompletedProcess([], 0, 'unavailable'),
                      subprocess.CompletedProcess([], 1, ''), FileNotFoundError(),
                      subprocess.TimeoutExpired([], 2)):
            with self.which('omarchy-shell', 'fuzzel'), patch.object(w.subprocess, 'run',
                    **({'side_effect': reply} if isinstance(reply, Exception) else {'return_value': reply})):
                self.assertEqual(w.select_menu_backend({}), 'fuzzel')

    def test_absent_shell_is_not_invoked(self):
        with self.which('wofi'), patch.object(w.subprocess, 'run') as run:
            self.assertEqual(w.select_menu_backend({}), 'wofi')
            run.assert_not_called()

    def test_explicit_preference_does_not_probe_or_override_it(self):
        with self.which('rofi'), patch.object(w, 'omarchy_running') as probe:
            self.assertEqual(w.select_menu_backend({'HYPRFLIP_MENU': 'rofi'}), 'rofi')
            probe.assert_not_called()
            with self.assertRaisesRegex(w.SetupError, 'Fuzzel is not installed'):
                w.select_menu_backend({'HYPRFLIP_MENU': 'fuzzel'})
        with self.assertRaisesRegex(w.SetupError, 'HYPRFLIP_MENU must be'):
            w.select_menu_backend({'HYPRFLIP_MENU': 'echo unsafe'})

    def test_missing_frontend_has_actionable_error(self):
        with self.which():
            with self.assertRaisesRegex(w.SetupError, 'Install Fuzzel'):
                w.select_menu_backend({}, False)


class DesktopMenuTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='hyprflip-menu-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.record = self.root / 'record.json'
        for name in ('fuzzel', 'rofi', 'wofi'):
            program = self.root / name
            program.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, sys, time
text = sys.stdin.read()
pathlib.Path(os.environ['HF_MENU_RECORD']).write_text(json.dumps({'argv': sys.argv, 'input': text, 'pid': os.getpid()}))
if os.environ.get('HF_MENU_WAIT'): time.sleep(60)
sys.stdout.write(os.environ.get('HF_MENU_RESULT', '0') + '\\n')
sys.exit(int(os.environ.get('HF_MENU_EXIT', '0')))
''')
            program.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root), HF_MENU_RECORD=str(self.record), HYPRFLIP_MENU='auto')
        self.request = Mock()

    def test_duplicate_labels_map_to_distinct_values_and_titles_stay_data(self):
        label = 'same <b>name</b> `touch nope` $(touch nope)'
        choices = [w.Choice('first', label, 'detail\ntext\x00icon'), w.Choice('second', label, 'detail\ntext\x00icon')]
        for backend in ('fuzzel', 'rofi', 'wofi'):
            menu = w.DesktopMenu(backend, self.request, self.env | {'HF_MENU_RESULT': '1'})
            self.assertEqual(menu.choose('Choose', choices), 'second')
            data = json.loads(self.record.read_text())
            self.assertEqual(len(data['input'].splitlines()), 2)
            self.assertIn(label, data['input'])
            self.assertNotIn('\x00', data['input'])

    def test_arbitrary_or_out_of_range_selection_is_rejected(self):
        for result in ('-1', '1', '0\n0', '0;touch nope', ''):
            with self.assertRaises(w.SetupError):
                w.DesktopMenu('fuzzel', self.request, self.env | {'HF_MENU_RESULT': result}).choose(
                    'Choose', [w.Choice('only', 'One')])

    def test_text_input_can_name_cards_and_does_not_execute_it(self):
        for backend in ('fuzzel', 'rofi', 'wofi'):
            name = 'Project $(touch nope)'
            menu = w.DesktopMenu(backend, self.request, self.env | {'HF_MENU_RESULT': name})
            self.assertEqual(menu.input('Name this card'), name)
            self.assertEqual(json.loads(self.record.read_text())['input'], '')

    def test_user_cancellation_does_not_try_a_second_frontend(self):
        with patch.object(w, 'select_menu_backend', return_value='fuzzel') as detect:
            menu = w.AutoMenu(self.root, self.request, self.env | {'HF_MENU_EXIT': '1'})
            with self.assertRaises(w.Cancelled):
                menu.choose('Choose', [w.Choice('one', 'One')])
            self.assertEqual(detect.call_count, 1)

    def test_unavailable_omarchy_menu_falls_back_but_escape_does_not(self):
        with patch.object(w, 'select_menu_backend', side_effect=['omarchy', 'fuzzel']) as detect, \
                patch.object(w.OmarchyMenu, 'choose', side_effect=w.MenuUnavailable()):
            menu = w.AutoMenu(self.root, self.request, self.env)
            self.assertEqual(menu.choose('Choose', [w.Choice('one', 'One')]), 'one')
            self.assertEqual(detect.call_count, 2)
        with patch.object(w, 'select_menu_backend', return_value='omarchy') as detect, \
                patch.object(w.OmarchyMenu, 'choose', side_effect=w.Cancelled()):
            menu = w.AutoMenu(self.root, self.request, self.env)
            with self.assertRaises(w.Cancelled): menu.choose('Choose', [w.Choice('one', 'One')])
            self.assertEqual(detect.call_count, 1)

    def test_superseded_request_closes_the_old_picker(self):
        def supersede_when_running():
            if self.record.exists():
                raise w.Cancelled()
        self.request.check.side_effect = supersede_when_running
        menu = w.DesktopMenu('fuzzel', self.request, self.env | {'HF_MENU_WAIT': '1'})
        with self.assertRaises(w.Cancelled): menu.choose('Choose', [w.Choice('one', 'One')])
        pid = json.loads(self.record.read_text())['pid']
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)


class NotificationTest(unittest.TestCase):
    def test_launch_notification_uses_portable_flags_and_cancels_by_action(self):
        process = Mock()
        process.poll.return_value = 0
        with patch.object(w.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(w.subprocess, 'run') as close:
            with w.Opening('Work', ['Editor'], {}) as progress:
                command = launch.call_args.args[0]
                self.assertIn('--print-id', command)
                self.assertNotIn('--id-fd', command)
                self.assertNotIn('--selected-action-fd', command)
                self.assertIn('--app-name=Hyprflip', command)
                progress.answer.write_text('17\ndefault\n')
                with self.assertRaises(w.Cancelled): progress.check()
            self.assertEqual(close.call_args.args[0][-1], '17')

    def test_missing_notification_service_does_not_fail_the_card_action(self):
        with patch.object(w.subprocess, 'run', side_effect=[FileNotFoundError(), subprocess.CompletedProcess([], 0)]) as run:
            w.notify('Card saved')
            self.assertEqual(run.call_args.args[0][:2], ['hyprctl', 'notify'])


if __name__ == '__main__': unittest.main()
