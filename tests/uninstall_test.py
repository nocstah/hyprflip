"""scripts/uninstall.py against a stand-in Hyprland, in a disposable home: what the installers wrote comes out, and a
configuration error puts everything back."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
BLOCK = (ROOT / 'examples/module-path.lua').read_text()
ORIGINAL = '-- existing desktop configuration\nrequire("hypr.mine")\n'


def installed(text, mouse=False):
    """hyprland.lua as scripts/install.py, then scripts/install-setup.py, leave it."""
    text = BLOCK + '\n' + text
    text = text.rstrip() + '\n\n-- Two-sided application windows.\nrequire("hypr.hyprflip")\n'
    text = text.rstrip() + '\n\n-- Hyprflip helpers and saved motion preferences.\nrequire("hypr.hyprflip-setup")\n'
    return text + ('require("hypr.hyprflip-mouse")\n' if mouse else '')


class UninstallTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hyprflip-uninstall-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / 'config/hypr'
        self.state = self.home / 'state/hyprflip'
        self.library = self.home / '.local/lib/hyprflip'
        self.main = self.config / 'hyprland.lua'
        self.config.mkdir(parents=True)
        self.main.write_text(installed(ORIGINAL, mouse=True))
        for name in ('hyprflip.lua', 'hyprflip-setup.lua', 'hyprflip-preferences.lua', 'hyprflip-shortcuts.lua',
                     'hyprflip-mouse.lua', 'hyprflip.lua.bak-20261111-171238', 'hyprland.lua.bak-20261111-171238'):
            (self.config / name).write_text(f'-- {name}\n')
        (self.config / 'mine.lua').write_text('-- the user\'s own module\n')
        (self.config / 'bindings.lua.bak.1794370386').write_text('-- another tool\'s backup\n')
        self.library.mkdir(parents=True)
        for name in ('hyprflip.so', 'setup.py', 'control.py', 'hyprflip.so.bak-20261111-171238'):
            (self.library / name).write_text(name)
        self.state.mkdir(parents=True)
        for name, text in (('installed-release', '0.3.0-rc.20\n'), ('installed-commit', 'a' * 40 + '\n'), ('cards.json', '{}\n')):
            (self.state / name).write_text(text)
        self.session, self.loaded, self.containers, self.calls = True, True, [], []
        self.sticky = False  # Hyprland keeps the plugin through a reload that no longer declares it
        # The configuration errors Hyprland reports for what hyprland.lua says, at each reload.
        self.problems = lambda text: []
        self.errors = []

    def hyprctl(self, command, **kwargs):
        self.assertEqual(command[0], 'hyprctl')
        args = command[1:]
        self.calls.append(args)
        if not self.session:
            return subprocess.CompletedProcess(command, 4, "Couldn't connect (4)\n", '')
        if args == ['version']:
            reply = 'Hyprland 0.56.2'
        elif args == ['-j', 'plugin', 'list']:
            reply = json.dumps([{'name': 'hyprflip'}] if self.loaded else [])
        elif args == ['hyprflip', 'status']:
            self.assertTrue(self.loaded)
            reply = json.dumps({'version': '0.3.0', 'pairs': [], 'containers': self.containers})
        elif args == ['hyprflip', 'finish']:
            reply = 'ok: settled'
        elif args == ['reload']:
            # The declaration is Hyprland's desired plugin list: without it a reload unloads the plugin.
            text = self.main.read_text()
            self.loaded = self.loaded and (self.sticky or 'require("hypr.hyprflip")' in text)
            self.errors = self.problems(text)
            reply = 'ok'
        elif args == ['configerrors']:
            reply = '\n'.join(self.errors)
        elif args == ['plugin', 'unload', str(self.library / 'hyprflip.so')]:
            self.loaded = False
            reply = 'ok'
        elif args == ['plugin', 'load', str(self.library / 'hyprflip.so')]:
            self.assertTrue((self.library / 'hyprflip.so').is_file())
            self.loaded = True
            reply = 'ok'
        else:
            self.fail(f'Unexpected IPC: {args}')
        return subprocess.CompletedProcess(command, 0, reply + '\n', '')

    def uninstall(self, *arguments):
        self.output = io.StringIO()
        which = lambda name, *a, **k: '/usr/bin/hyprctl' if name == 'hyprctl' else None
        with patch.object(Path, 'home', return_value=self.home), \
                patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / 'config'), 'XDG_STATE_HOME': str(self.home / 'state'),
                                        'HYPRLAND_INSTANCE_SIGNATURE': 'test-instance'}), \
                patch.object(sys, 'argv', ['uninstall.py', *arguments]), \
                patch('subprocess.run', side_effect=self.hyprctl), patch('shutil.which', side_effect=which), \
                contextlib.redirect_stdout(self.output):
            try:
                runpy.run_path(str(ROOT / 'scripts/uninstall.py'), run_name='__main__')
            except SystemExit as stop:
                return stop.code
        return None

    def kept(self):
        """The folder the modules and backups moved to."""
        found = list(self.state.glob('uninstalled-*'))
        self.assertEqual(len(found), 1, found)
        return found[0]

    def test_everything_the_installers_wrote_comes_out(self):
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertFalse(self.loaded)
        self.assertFalse(self.library.exists())
        self.assertEqual(sorted(p.name for p in self.config.iterdir()),
                         ['bindings.lua.bak.1794370386', 'hyprland.lua', 'mine.lua'])
        self.assertEqual(sorted(p.name for p in self.kept().iterdir()),
                         ['hyprflip-mouse.lua', 'hyprflip-preferences.lua', 'hyprflip-setup.lua', 'hyprflip-shortcuts.lua',
                          'hyprflip.lua', 'hyprflip.lua.bak-20261111-171238', 'hyprland.lua.bak-20261111-171238'])
        self.assertEqual((self.kept() / 'hyprflip.lua').read_text(), '-- hyprflip.lua\n')
        # the saved cards stay; what said Hyprflip is installed goes
        self.assertEqual(sorted(p.name for p in self.state.iterdir() if p.is_file()), ['cards.json'])
        self.assertIn(['hyprflip', 'finish'], self.calls)
        self.assertIn('Hyprflip is removed.', self.output.getvalue())

    def test_a_plugin_the_reload_left_loaded_is_unloaded(self):
        self.sticky = True
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertIn(['plugin', 'unload', str(self.library / 'hyprflip.so')], self.calls)
        self.assertFalse(self.loaded)

    def test_a_dry_run_changes_nothing(self):
        before = self.main.read_text()
        self.assertEqual(self.uninstall('--dry-run'), 0)
        self.assertEqual(self.main.read_text(), before)
        self.assertTrue((self.library / 'hyprflip.so').exists())
        self.assertTrue((self.config / 'hyprflip.lua').exists())
        self.assertNotIn(['reload'], self.calls)
        self.assertIn('Saved cards and preferences stay', self.output.getvalue())

    def test_a_new_configuration_error_puts_everything_back(self):
        before = self.main.read_text()
        self.problems = lambda text: [] if 'require("hypr.hyprflip")' in text else ['hyprland.lua:3: module "hypr.hyprflip-shortcuts" not found']
        self.assertIn('Hyprflip was not removed, and everything is as it was. Hyprland reported: hyprland.lua:3',
                      self.uninstall('--yes'))
        self.assertEqual(self.main.read_text(), before)
        self.assertTrue(self.loaded)
        self.assertEqual((self.config / 'hyprflip.lua').read_text(), '-- hyprflip.lua\n')
        self.assertTrue((self.library / 'hyprflip.so').exists())
        self.assertTrue((self.state / 'installed-commit').exists())
        self.assertEqual(list(self.state.glob('uninstalled-*')), [])

    def test_the_search_path_stays_when_another_module_needs_it(self):
        self.problems = lambda text: [] if 'package.path' in text else ['hyprland.lua:2: module "hypr.mine" not found']
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertEqual(self.main.read_text(), BLOCK + '\n' + ORIGINAL)
        self.assertFalse(self.library.exists())

    def test_errors_from_before_are_not_counted(self):
        self.problems = lambda text: ['hyprland.lua:9: the user\'s own mistake']
        self.errors = self.problems('')
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertEqual(self.main.read_text(), ORIGINAL)

    def test_parked_cards_stop_it_before_anything_changes(self):
        before = self.main.read_text()
        self.containers = [{'faces': [['0xa'], ['0xb']], 'workspace': {'id': -98, 'name': 'special:park', 'special': True}}]
        self.assertIn('1 card(s) are parked out of sight', self.uninstall('--yes'))
        self.assertEqual(self.main.read_text(), before)
        self.assertTrue(self.loaded)
        self.assertNotIn(['reload'], self.calls)

    def test_lines_the_user_changed_or_added_stay(self):
        text = installed(ORIGINAL).replace('-- Two-sided application windows.', '-- my cards') + 'require("hypr.hyprflip-fkeys")\n'
        self.main.write_text(text)
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertEqual(self.main.read_text(), ORIGINAL + '\n-- my cards\nrequire("hypr.hyprflip-fkeys")\n')

    def test_purge_removes_the_saved_cards_too(self):
        self.assertEqual(self.uninstall('--yes', '--purge'), 0)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertFalse((self.config / 'hyprflip.lua').exists())

    def test_without_hyprland_only_the_files_change(self):
        self.session = False
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertFalse(self.library.exists())
        self.assertEqual(self.calls, [['version']])
        self.assertIn('Hyprland reads the change when it next starts.', self.output.getvalue())

    def test_it_asks_and_takes_no_for_an_answer(self):
        before = self.main.read_text()
        with patch('sys.stdin') as stdin, patch('builtins.input', return_value='') as answer:
            stdin.isatty.return_value = True
            self.assertEqual(self.uninstall(), 0)
        answer.assert_called_once_with('Remove Hyprflip? [y/N] ')
        self.assertEqual(self.main.read_text(), before)
        self.assertIn('Nothing was changed.', self.output.getvalue())

    def test_without_a_terminal_it_needs_yes(self):
        with patch('sys.stdin') as stdin:
            stdin.isatty.return_value = False
            self.assertIn('Add --yes', self.uninstall())
        self.assertTrue(self.library.exists())

    def test_nothing_installed_says_so(self):
        self.main.write_text(ORIGINAL)
        for path in (*self.config.glob('hyprflip*'), *self.config.glob('hyprland.lua.bak-*')):
            path.unlink()
        for path in self.library.iterdir():
            path.unlink()
        self.library.rmdir()
        for name in ('installed-release', 'installed-commit'):
            (self.state / name).unlink()
        self.loaded = False
        self.assertEqual(self.uninstall('--yes'), 0)
        self.assertEqual(self.output.getvalue(), 'Hyprflip is not installed here.\n')


if __name__ == '__main__':
    unittest.main()
