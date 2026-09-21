"""Check guided setup installation and rollback without touching user config."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class SetupInstallTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hyprflip-setup-install-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project, self.home = self.root / 'project', self.root / 'user'
        for relative in ('scripts/install-setup.py', 'scripts/setup.py', 'examples/containers-setup.lua'):
            target = self.project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.config = self.home / 'config/hypr'
        self.config.mkdir(parents=True)
        self.main = self.config / 'hyprland.lua'
        self.main.write_text('-- custom config\nrequire("hypr.hyprflip-containers")\n')
        self.helper = self.home / '.local/lib/hyprflip/setup.py'
        self.module = self.config / 'hyprflip-setup.lua'
        self.original = self.main.read_bytes()
        self.calls, self.reloads = [], 0
        self.fail_reload, self.conflict = False, None
        self.state = {'container_provider': True, 'peek_available': True,
                      'containers': [{'faces': [['0xa'], ['0xb', '0xc']]}], 'pairs': []}

    def run_command(self, command, **kwargs):
        self.calls.append(command)
        if command == ['omarchy-shell', 'shell', 'ping']:
            reply = 'ok'
        else:
            self.assertEqual(command[0], 'hyprctl')
            args = command[1:]
            if args == ['configerrors']:
                reply = 'Injected parse failure' if self.fail_reload and self.reloads == 1 else ''
            elif args == ['hyprflip', 'status']:
                reply = self.state
            elif args[0] == 'repl':
                reply = 'true'
            elif args == ['-j', 'binds']:
                description = 'Other action' if self.conflict == 'O' else (
                    'Hyprflip: unfold, fold or create a card' if self.module.exists() else 'Hyprflip: unfold or fold both faces')
                reply = [{'modmask': 76, 'key': 'O', 'description': description}]
                if self.module.exists() or self.conflict == 'C':
                    reply.append({'modmask': 76, 'key': 'C', 'description':
                                  'Other action' if self.conflict == 'C' else 'Hyprflip: edit card'})
                if self.module.exists() or self.conflict == 'SPACE':
                    reply.append({'modmask': 76, 'key': 'space', 'description':
                                  'Other action' if self.conflict == 'SPACE' else 'Hyprflip: hold to peek at the other side'})
            elif args == ['reload']:
                self.reloads += 1
                reply = 'ok'
            else:
                self.fail('Unexpected call: ' + repr(command))
        if not isinstance(reply, str): reply = json.dumps(reply)
        return subprocess.CompletedProcess(command, 0, reply, '')

    def install(self, *args):
        with patch.object(Path, 'home', return_value=self.home), \
                patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / 'config'),
                                        'XDG_STATE_HOME': str(self.home / 'state')}), \
                patch('shutil.which', side_effect=lambda name: '/usr/bin/' + name), \
                patch('subprocess.run', side_effect=self.run_command), \
                patch.object(sys, 'argv', ['install-setup.py', *args]), \
                contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(self.project / 'scripts/install-setup.py'), run_name='__main__')

    def test_dry_run_writes_nothing(self):
        with self.assertRaises(SystemExit) as result: self.install('--dry-run')
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(self.main.read_bytes(), self.original)
        self.assertFalse(self.helper.exists())
        self.assertFalse((self.home / 'state').exists())
        self.assertEqual(self.reloads, 0)

    def test_install_preserves_cards_and_is_repeatable_without_plugin_operations(self):
        for _ in range(2):
            with self.assertRaises(SystemExit) as result: self.install()
            self.assertEqual(result.exception.code, 0)
        self.assertEqual(self.main.read_text().count('require("hypr.hyprflip-setup")'), 1)
        self.assertTrue(self.main.read_text().startswith(self.original.decode()))
        self.assertEqual(self.helper.read_bytes(), (ROOT / 'scripts/setup.py').read_bytes())
        self.assertTrue(self.module.exists())
        self.assertFalse(any('plugin' in call or 'mark' in call or 'pair' in call for call in self.calls))

    def test_conflict_refuses_before_writing(self):
        for key in ('O', 'C', 'SPACE'):
            self.conflict = key
            with self.assertRaisesRegex(SystemExit, 'assigned to another action'): self.install()
            self.assertEqual(self.main.read_bytes(), self.original)
            self.assertFalse(self.helper.exists())
            self.assertEqual(self.reloads, 0)

    def test_parse_failure_restores_exact_files_and_removes_new_files(self):
        self.fail_reload = True
        with self.assertRaisesRegex(RuntimeError, 'Injected parse failure'): self.install()
        self.assertEqual(self.main.read_bytes(), self.original)
        self.assertFalse(self.helper.exists())
        self.assertFalse(self.module.exists())
        self.assertEqual(self.reloads, 2)


if __name__ == '__main__': unittest.main()
