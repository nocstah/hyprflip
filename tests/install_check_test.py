"""install_check: whether the core and helpers that run are those bootstrap.py installed."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow as w  # noqa: E402


class InstallCheckTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lib, self.state = Path(directory.name) / 'lib', Path(directory.name) / 'state'
        self.lib.mkdir()
        self.state.mkdir()
        for name, content in (('hyprflip.so', b'core'), ('control.py', b'helper'), ('navigation.lua', b'keys')):
            (self.lib / name).write_bytes(content)
        (self.lib / '__pycache__').mkdir()
        w.record_installed_files(self.lib, self.state, 'c' * 40)

    def loaded(self, path=None, **changes):
        """status's loaded_file for the core loaded from path, as that file is now."""
        path = path or self.lib / 'hyprflip.so'
        info = path.stat()
        return {'loaded_file': {'path': str(path), 'inode': info.st_ino, 'size': info.st_size,
                                'mtime_ns': info.st_mtime_ns, **changes}}

    def test_without_a_record_of_the_install_there_is_nothing_to_say(self):
        (self.state / w.INSTALLED_FILES).unlink()
        self.assertIsNone(w.install_check(self.lib, self.state, self.loaded()))
        (self.state / w.INSTALLED_FILES).write_text('not json')
        self.assertIsNone(w.install_check(self.lib, self.state, self.loaded()))

    def test_the_install_as_recorded_and_its_core_loaded(self):
        self.assertEqual(w.install_check(self.lib, self.state, self.loaded()), {'loaded': 'same', 'changed': []})
        # A core that does not say what it was loaded from.
        self.assertEqual(w.install_check(self.lib, self.state, {}), {'loaded': 'unknown', 'changed': []})

    def test_a_helper_copied_over_is_named_and_a_touch_is_not(self):
        (self.lib / 'control.py').write_bytes(b'hand-copied helper')
        os.utime(self.lib / 'navigation.lua', ns=(1, 1))
        self.assertEqual(w.install_check(self.lib, self.state, self.loaded()), {'loaded': 'same', 'changed': ['control.py']})

    def test_a_file_gone_or_added_is_named_and_a_backup_is_not(self):
        (self.lib / 'navigation.lua').unlink()
        (self.lib / 'extra.py').write_bytes(b'new')
        (self.lib / 'control.py.bak-20261118').write_bytes(b'old')
        self.assertEqual(w.install_check(self.lib, self.state, self.loaded()),
                         {'loaded': 'same', 'changed': ['extra.py', 'navigation.lua']})

    def test_a_core_loaded_from_elsewhere_or_from_an_older_copy_differs(self):
        other = self.lib.parent / 'build-hyprflip.so'
        other.write_bytes(b'core')
        self.assertEqual(w.install_check(self.lib, self.state, self.loaded(other))['loaded'], 'differs')
        # The installed file replaced after the load: the running core is the copy that was there.
        running = self.loaded()
        (self.lib / 'hyprflip.so').write_bytes(b'newer core')
        self.assertEqual(w.install_check(self.lib, self.state, running), {'loaded': 'differs', 'changed': ['hyprflip.so']})


if __name__ == '__main__':
    unittest.main()
