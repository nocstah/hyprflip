import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import shortcuts


class IPC:
    def __init__(self, root):
        self.env = {'XDG_STATE_HOME': root}
        self.binds = [{'description': 'Hyprflip: turn window over', 'key': 'F', 'modmask': 76}]
        self.fail = False
        self.mutations = []
    def data(self, *args): return self.binds
    def call(self, *args):
        if 'configure(' not in args[-1]: return 'true'
        self.mutations.append(args[-1])
        if self.fail:
            self.fail = False
            raise shortcuts.SetupError('Injected failure')
        ident, mask, key = json.loads('[' + args[-1].split('.configure(')[1][:-1] + ']')
        self.binds[0].update(modmask=mask, key=key)
        return 'true'


class ShortcutsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.ipc = IPC(temp.name)

    def test_save_and_restore_default_are_persistent(self):
        shortcuts.save(self.ipc, 'flip', 65, 'F9')
        self.assertEqual(shortcuts.read(self.ipc), {'flip': (65, 'F9')})
        self.assertEqual(shortcuts.snapshot(self.ipc)['rows'][0]['shortcut'], 'Super+Shift+F9')
        shortcuts.save(self.ipc, 'flip', 76, 'F')
        self.assertEqual(shortcuts.read(self.ipc), {'flip': (76, 'F')})

    def test_conflict_keeps_bindings_and_disk_unchanged(self):
        for conflict in ({'key': 'F9', 'modmask': 65}, {'key': 'F', 'modmask': 76},
                         {'key': '', 'keycode': 12, 'modmask': 65}, {'key': '', 'keycode': 0, 'modmask': 65}):
            with self.subTest(conflict=conflict):
                self.ipc.binds = self.ipc.binds[:1] + [dict(description='Other action', **conflict)]
                with self.assertRaises(shortcuts.SetupError): shortcuts.save(self.ipc, 'flip', 65, 'F9')
                self.assertEqual(self.ipc.mutations, [])
                self.assertFalse(shortcuts.path(self.ipc).exists())

    def test_unreported_keys_allow_distinct_modifiers_and_inactive_submaps(self):
        self.ipc.binds += [
            {'description': 'Workspace key', 'key': '', 'keycode': 0, 'modmask': 64},
            {'description': 'Mode key', 'key': '', 'keycode': 0, 'modmask': 65, 'submap': 'resize'}]
        shortcuts.save(self.ipc, 'flip', 65, 'F9')
        self.assertEqual(shortcuts.read(self.ipc), {'flip': (65, 'F9')})

    def test_failure_rolls_back_runtime_and_persistent_preference(self):
        shortcuts.save(self.ipc, 'flip', 65, 'F9')
        self.ipc.fail = True
        with self.assertRaisesRegex(shortcuts.SetupError, 'Injected'): shortcuts.save(self.ipc, 'flip', 76, 'F')
        self.assertEqual(shortcuts.read(self.ipc), {'flip': (65, 'F9')})
        self.assertEqual(self.ipc.binds[0]['key'], 'F9')

    def test_rejects_injection_modifiers_and_unknown_keysyms(self):
        for mask, key in ((True, 'F'), (0, 'F'), (1, 'F'), (256, 'F'), (64, 'F);os.exit()'),
                          (64, 'made_up_key'), (64, 'Super_L')):
            with self.subTest(mask=mask, key=key), self.assertRaises(shortcuts.SetupError): shortcuts.normalize(mask, key)


if __name__ == '__main__': unittest.main()
