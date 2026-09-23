"""The updater must refuse a locked desktop before dismantling live cards."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class UpdateLockTest(unittest.TestCase):
    def test_lock_stops_before_plugin_operations_or_file_changes(self):
        with tempfile.TemporaryDirectory(prefix='hyprflip-locked-update-') as directory:
            root = Path(directory)
            script = root / 'scripts/update-containers.py'
            script.parent.mkdir()
            shutil.copyfile(ROOT / 'scripts/update-containers.py', script)
            for relative in ('installed/hyprflip.so', 'installed/containers/libhy3.so',
                             'build/containers/core/hyprflip.so',
                             'build/containers/provider/upstream/libhy3.so'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'original')
            calls = []

            def command(args, **kwargs):
                calls.append(args)
                if args == ['hyprctl', 'configerrors']:
                    output = ''
                elif args == ['hyprctl', '-j', 'monitors']:
                    output = json.dumps([{'solitaryBlockedBy': None},
                                         {'solitaryBlockedBy': ['WORKSPACE']},
                                         {'solitaryBlockedBy': ['LOCK', 'WINDOWED']}])
                else:
                    self.fail('Updater continued while locked: ' + repr(args))
                return subprocess.CompletedProcess(args, 0, output, '')

            with patch.object(sys, 'argv', [str(script), '--library-root', str(root / 'installed'),
                                           '--state-dir', str(root / 'state')]), \
                    patch('subprocess.run', side_effect=command), \
                    self.assertRaisesRegex(SystemExit, 'Unlock your desktop'):
                runpy.run_path(str(script), run_name='__main__')
            self.assertEqual(len(calls), 2)
            self.assertFalse((root / 'state').exists())
            self.assertEqual((root / 'installed/hyprflip.so').read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
