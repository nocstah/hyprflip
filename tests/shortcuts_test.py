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

    def test_card_fullscreen_row_defaults_to_return_and_is_editable(self):
        self.ipc.binds = [{'description': 'Hyprflip: fullscreen the whole card', 'key': 'Return', 'modmask': 76}]
        row = next(r for r in shortcuts.snapshot(self.ipc)['rows'] if r['id'] == 'fullscreen')
        self.assertEqual((row['default_mask'], row['default_key'], row['shortcut']), (76, 'Return', 'Super+Ctrl+Alt+Return'))
        self.assertTrue(row['editable'])
        self.assertEqual(shortcuts.save(self.ipc, 'fullscreen', 76, 'F11'), 'Fullscreen whole card: Super+Ctrl+Alt+F11')
        self.assertEqual(shortcuts.read(self.ipc), {'fullscreen': (76, 'F11')})
        lua = (Path(__file__).resolve().parents[1] / 'examples/shortcuts.lua').read_text()
        self.assertIn('["fullscreen the whole card"]="fullscreen"', lua)

    def test_change_face_defaults_to_tab_and_keeps_its_earlier_name(self):
        for description in ('Hyprflip: change face', 'Hyprflip: turn window over'):
            with self.subTest(description=description):
                self.ipc.binds = [{'description': description, 'key': 'Tab', 'modmask': 76}]
                row = next(r for r in shortcuts.snapshot(self.ipc)['rows'] if r['id'] == 'flip')
                self.assertEqual((row['label'], row['default_mask'], row['default_key'], row['shortcut']),
                                 ('Change face', 76, 'Tab', 'Super+Ctrl+Alt+Tab'))
                self.assertTrue(row['editable'])
        self.assertEqual(shortcuts.save(self.ipc, 'flip', 76, 'S'), 'Change face: Super+Ctrl+Alt+S')
        project = Path(__file__).resolve().parents[1]
        self.assertIn('["change face"]="flip", ["turn window over"]="flip"', (project / 'examples/shortcuts.lua').read_text())
        self.assertIn('shortcuts.bind("SUPER + CTRL + ALT + Tab", run("flip"), { description = "Hyprflip: change face" })',
                      (project / 'examples/hyprflip.lua').read_text())

    def test_parse_chord_reads_what_hl_bind_takes(self):
        for text, expected in (('SUPER + CTRL + ALT + O', (76, 'O')), ('super+ctrl+alt+o', (76, 'O')),
                               ('CTRL + SUPER + ALT + Return', (76, 'Return')), ('SUPER + SHIFT + F9', (65, 'F9')),
                               ('MOD4 + CONTROL + MOD1 + space', (76, 'space')), ('SUPER + CTRL + ALT + mouse:274', (76, 'mouse:274'))):
            with self.subTest(text=text): self.assertEqual(shortcuts.parse_chord(text), expected)
        for text in ('O', 'SUPER +', 'HYPER + O', 'SUPER + SUPER + O', 'SUPER + O); os.exit(', ''):
            with self.subTest(text=text): self.assertIsNone(shortcuts.parse_chord(text))

    def test_claims_need_the_header_and_skip_what_they_cannot_read(self):
        reply = ('claims\nSUPER + CTRL + ALT + O\tOmaRelay\nnot a chord\tSomebody\nSUPER + K\t\n'
                 'SUPER + CTRL + ALT + L\t  A   very ' + 'long owner name ' * 5)
        claimed = shortcuts.claims(lambda source: reply)
        self.assertEqual(set(claimed), {(76, 'o'), (76, 'l')})
        self.assertEqual(claimed[(76, 'o')], 'OmaRelay')
        self.assertEqual(len(claimed[(76, 'l')]), 40)
        self.assertTrue(claimed[(76, 'l')].startswith('A very long owner name'))
        for answer in ('true', 'nil', '', 'unknown request'):
            with self.subTest(answer=answer): self.assertEqual(shortcuts.claims(lambda source: answer), {})
        def broken(source): raise shortcuts.SetupError('Lua error')
        self.assertEqual(shortcuts.claims(broken), {})
        self.assertIn('hyprflip_claimed_keys', shortcuts.CLAIMS_QUERY)

    def test_a_claimed_key_shows_its_owner_and_is_not_edited_here(self):
        self.ipc.binds = [{'description': 'Card: unfold, fold, create, or show the browser', 'key': 'O', 'modmask': 76},
                          {'description': 'Hyprflip: edit card', 'key': 'C', 'modmask': 76}]
        call = self.ipc.call
        self.ipc.call = lambda *args: ('claims\nSUPER + CTRL + ALT + O\tOmaRelay' if 'hyprflip_claimed_keys' in args[-1]
                                       else call(*args))
        rows = {r['id']: r for r in shortcuts.snapshot(self.ipc)['rows']}
        self.assertEqual((rows['create']['shortcut'], rows['create']['owner'], rows['create']['editable']),
                         ('Super+Ctrl+Alt+O', 'OmaRelay', False))
        self.assertNotIn('owner', rows['edit'])
        self.assertTrue(rows['edit']['editable'])
        with self.assertRaisesRegex(shortcuts.SetupError, 'OmaRelay sets this shortcut'): shortcuts.save(self.ipc, 'create', 76, 'F9')
        with self.assertRaisesRegex(shortcuts.SetupError, 'is used by Card: unfold'): shortcuts.save(self.ipc, 'edit', 76, 'O')
        self.assertEqual(self.ipc.mutations, [])

    def test_rejects_injection_modifiers_and_unknown_keysyms(self):
        for mask, key in ((True, 'F'), (0, 'F'), (1, 'F'), (256, 'F'), (64, 'F);os.exit()'),
                          (64, 'made_up_key'), (64, 'Super_L')):
            with self.subTest(mask=mask, key=key), self.assertRaises(shortcuts.SetupError): shortcuts.normalize(mask, key)


if __name__ == '__main__': unittest.main()
