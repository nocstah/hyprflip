"""OmaCards is optional: the working native menus remain available."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from setup_test import setup

sys.modules['workflow'] = setup
spec = importlib.util.spec_from_file_location('hyprflip_entry', Path(__file__).resolve().parents[1] / 'scripts/setup.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class PanelRouteTest(unittest.TestCase):
    def test_available_panel_receives_existing_shortcuts(self):
        for flag, page in (('--cards', 'edit'), ('--launch', 'library')):
            with patch.object(sys, 'argv', ['setup.py', flag]), \
                 patch.object(entry, 'omarchy_running', return_value=True), \
                 patch.object(entry, 'menu_main') as fallback, \
                 patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'ok\n')) as run:
                self.assertEqual(entry.main(), 0)
                self.assertEqual(run.call_args.args[0], ['omarchy-shell', 'omacards', 'open', page])
                fallback.assert_not_called()

    def test_missing_disabled_or_stopped_panel_uses_original_menu(self):
        for result in (subprocess.CompletedProcess([], 0, 'unavailable'),
                       subprocess.CompletedProcess([], 1, ''),
                       subprocess.TimeoutExpired([], 3), FileNotFoundError()):
            with patch.object(sys, 'argv', ['setup.py', '--launch']), \
                 patch.object(entry, 'omarchy_running', return_value=True), \
                 patch.object(entry, 'menu_main', return_value=7) as fallback, \
                 patch('subprocess.run', **({'side_effect': result} if isinstance(result, Exception) else {'return_value': result})):
                self.assertEqual(entry.main(), 7)
                fallback.assert_called_once()

    def test_absent_shell_skips_panel_and_passes_detection_to_menu(self):
        with patch.object(sys, 'argv', ['setup.py', '--cards']), \
             patch.object(entry, 'omarchy_running', return_value=False), \
             patch.object(entry, 'menu_main', return_value=0) as fallback, patch('subprocess.run') as run:
            self.assertEqual(entry.main(), 0)
            run.assert_not_called()
            fallback.assert_called_once_with(omarchy_available=False)

    def test_explicit_picker_preference_bypasses_the_panel(self):
        with patch.object(sys, 'argv', ['setup.py', '--launch']), \
             patch.dict(entry.os.environ, {'HYPRFLIP_MENU': 'rofi'}), \
             patch.object(entry, 'omarchy_running') as probe, \
             patch.object(entry, 'menu_main', return_value=0) as fallback, patch('subprocess.run') as run:
            self.assertEqual(entry.main(), 0)
            probe.assert_not_called()
            run.assert_not_called()
            fallback.assert_called_once_with()

    def test_explicit_legacy_and_guided_creation_do_not_route(self):
        for args in (['--legacy', '--cards'], ['--front', '0xa'], ['--edit', '0xa']):
            with patch.object(sys, 'argv', ['setup.py', *args]), \
                 patch.object(entry, 'menu_main', return_value=0) as fallback, patch('subprocess.run') as run:
                entry.main()
                fallback.assert_called_once()
                run.assert_not_called()


if __name__ == '__main__': unittest.main()
