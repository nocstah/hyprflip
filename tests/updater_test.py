"""Rollback must restore library files even after the compositor stops responding."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class UpdaterTest(unittest.TestCase):
    def test_lost_compositor_restores_files_and_keeps_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'scripts/update-containers.py'
            script.parent.mkdir()
            shutil.copy2(Path(__file__).resolve().parent.parent / 'scripts/update-containers.py', script)
            library = root / 'installed'
            for relative, value in (
                ('installed/hyprflip.so', b'old core'),
                ('installed/containers/libhy3.so', b'old provider'),
                ('build/containers/core/hyprflip.so', b'new core'),
                ('build/containers/provider/upstream/libhy3.so', b'new provider'),
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value)
            binary = root / 'bin/hyprctl'
            binary.parent.mkdir()
            binary.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['HYPRFLIP_TEST_ROOT'])
args = sys.argv[1:]
loaded_file = root / 'loaded.json'
loaded = json.loads(loaded_file.read_text()) if loaded_file.exists() else ['hyprflip', 'hy3']
if (root / 'dead').exists():
    print('error: mock compositor is gone'); sys.exit(1)
if args[:2] == ['plugin', 'load']:
    assert (root / 'installed/hyprflip.so').read_bytes() == b'new core'
    assert (root / 'installed/containers/libhy3.so').read_bytes() == b'new provider'
    (root / 'dead').touch()
    print('error: injected failure during plugin load'); sys.exit(1)
if args[:2] == ['plugin', 'unload']:
    loaded.remove('hyprflip' if Path(args[2]).name == 'hyprflip.so' else 'hy3')
    loaded_file.write_text(json.dumps(loaded)); print('ok')
elif args == ['configerrors']: print('')
elif args == ['-j', 'plugin', 'list']: print(json.dumps([{'name':name} for name in loaded]))
elif args == ['hyprflip', 'status']: print(json.dumps({'containers':[], 'pairs':[], 'container_provider':True}))
elif args == ['-j', 'activewindow']: print(json.dumps({'address':'0xa'}))
elif args[:1] == ['-j']: print('[]')
else: print('ok')
''')
            binary.chmod(0o755)
            result = subprocess.run(['python', str(script), '--library-root', str(library),
                                     '--state-dir', str(root / 'state')],
                                    env=os.environ | {'PATH': str(binary.parent) + ':' + os.environ['PATH'],
                                                      'HYPRFLIP_TEST_ROOT': str(root)},
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((root / 'dead').exists())
            self.assertEqual((library / 'hyprflip.so').read_bytes(), b'old core')
            self.assertEqual((library / 'containers/libhy3.so').read_bytes(), b'old provider')
            self.assertIn('Previous library files restored on disk.', result.stdout)
            self.assertIn('Recovery needs attention', result.stdout)
            self.assertIn('Could not restore desktop focus', result.stdout)
            self.assertIn('injected failure during plugin load', result.stderr)
            self.assertEqual(result.stderr.count('Traceback (most recent call last)'), 1)


if __name__ == '__main__':
    unittest.main()
