"""Switch the movement shortcuts on and off against a fake Hyprland, in a disposable home."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import navigation  # noqa: E402

SHIPPED = (ROOT / 'examples/containers-navigation.lua').read_bytes()
LINES = '\n\n' + navigation.COMMENT + '\n' + navigation.STATEMENT + '\n'


class Hyprland:
    """Registers the movement shortcuts while the module loads, as Hyprland would after a reload."""
    def __init__(self, paths):
        self.paths, self.calls, self.errors, self.broken = paths, [], [], False
        self.keys, self.cards = list(navigation.KEYS), [{'faces': [['0xa'], ['0xb']]}]
        self.loaded = self.load()

    def load(self):
        return self.paths.module.is_file() and navigation.loaded(self.paths.main.read_text())

    def __call__(self, *args):
        self.calls.append(args)
        if args == ('configerrors',):
            return '\n'.join(self.errors + (['hyprflip-navigation.lua:1: broken'] if self.broken and self.loaded else []))
        if args == ('reload',):
            self.loaded = self.load()
            return 'ok'
        if args == ('-j', 'binds'):
            return json.dumps([{'modmask': 64, 'key': 'Q', 'description': 'Close window'}]
                              + [{'modmask': 65, 'key': 'X', 'description': d} for d in self.keys if self.loaded])
        if args == ('hyprflip', 'status'):
            return json.dumps({'containers': self.cards, 'pairs': []})
        raise AssertionError(f'unexpected call {args}')

    @property
    def reloads(self): return self.calls.count(('reload',))


class NavigationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='hyprflip-navigation-')
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.paths = navigation.Paths({'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / 'config'),
                                       'XDG_STATE_HOME': str(self.home / 'state')})
        self.paths.main.parent.mkdir(parents=True)
        self.original = '-- my config\nrequire("hypr.hyprflip-setup")\n'
        self.paths.main.write_text(self.original)
        self.hyprland = Hyprland(self.paths)
        self.clock = (datetime(2026, 11, 14, 15, 0, second) for second in range(60))

    def switch(self, enabled):
        return navigation.switch(enabled, self.hyprland, self.paths, SHIPPED, now=lambda: next(self.clock))

    def backups(self):
        return sorted(path for path in self.paths.state.glob('navigation-*') if path.is_dir())

    def test_paths_follow_xdg_and_fall_back_to_the_home(self):
        self.assertEqual(self.paths.module, self.home / 'config/hypr/hyprflip-navigation.lua')
        self.assertEqual(self.paths.choice, self.home / 'state/hyprflip/navigation-choice')
        bare = navigation.Paths({'HOME': str(self.home), 'XDG_CONFIG_HOME': '', 'XDG_STATE_HOME': ''})
        self.assertEqual(bare.main, self.home / '.config/hypr/hyprland.lua')
        self.assertEqual(bare.record, self.home / '.local/state/hyprflip/navigation.sha256')

    def test_the_require_line_comes_and_goes_with_its_comment(self):
        added = navigation.with_statement(self.original)
        self.assertEqual(added, self.original + LINES[1:])
        self.assertEqual(navigation.with_statement(added), added)
        self.assertEqual(navigation.without_statement(added), self.original)
        # a line of the user's own goes alone, whatever its indentation, and nothing else changes
        own = 'local a = 1\nif a then\n  require("hypr.hyprflip-navigation")\nend\n'
        self.assertEqual(navigation.without_statement(own), 'local a = 1\nif a then\nend\n')
        self.assertFalse(navigation.loaded(navigation.without_statement(own)))
        self.assertEqual(navigation.without_statement(self.original), self.original)

    def test_state_needs_both_the_file_and_its_line(self):
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'off')
        self.paths.module.write_bytes(SHIPPED)
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'off')
        self.paths.main.write_text(self.original + LINES[1:])
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'on')
        self.paths.module.unlink()
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'off')

    def test_only_changes_of_the_users_own_make_it_edited(self):
        self.paths.main.write_text(self.original + LINES[1:])
        earlier = b'-- the module as an earlier install put it in place\n'
        self.paths.module.write_bytes(earlier)
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'edited')
        navigation.record(self.paths, earlier)
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'on')
        self.paths.module.write_bytes(SHIPPED + b'-- mine\n')
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'edited')
        # without a shipped copy to compare, a recorded one still counts as unchanged
        self.paths.module.write_bytes(earlier)
        self.assertEqual(navigation.state(self.paths, None), 'on')

    def test_choice_is_on_off_or_none(self):
        self.assertIsNone(navigation.choice(self.paths))
        for text, expected in (('on\n', 'on'), ('off', 'off'), ('maybe\n', None), ('', None)):
            with self.subTest(text=text):
                self.paths.choice.parent.mkdir(parents=True, exist_ok=True)
                self.paths.choice.write_text(text)
                self.assertEqual(navigation.choice(self.paths), expected)

    def test_on_installs_loads_records_and_checks_every_key(self):
        self.assertIsNone(self.switch(True))
        self.assertEqual(self.paths.module.read_bytes(), SHIPPED)
        self.assertEqual(self.paths.main.read_text(), self.original + LINES[1:])
        self.assertEqual(self.paths.record.read_text().strip(), hashlib.sha256(SHIPPED).hexdigest())
        self.assertEqual(navigation.choice(self.paths), 'on')
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'on')
        self.assertEqual(self.hyprland.reloads, 1)
        self.assertIn(('-j', 'binds'), self.hyprland.calls)
        # the backup holds the configuration as it was
        [backup] = self.backups()
        self.assertEqual((backup / 'hyprland.lua').read_text(), self.original)
        self.assertFalse((backup / 'hyprflip-navigation.lua').exists())

    def test_off_removes_the_module_its_line_and_its_record(self):
        self.switch(True)
        self.assertIsNone(self.switch(False))
        self.assertFalse(self.paths.module.exists())
        self.assertEqual(self.paths.main.read_text(), self.original)
        self.assertFalse(self.paths.record.exists())
        self.assertEqual(navigation.choice(self.paths), 'off')
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'off')
        self.assertFalse(self.hyprland.loaded)
        self.assertEqual(self.hyprland.reloads, 2)

    def test_a_changed_copy_is_kept_in_the_backup_either_way(self):
        own = SHIPPED + b'-- a workspace numbering of my own\n'
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.paths.module.write_bytes(own)
                self.paths.main.write_text(self.original + LINES[1:])
                for backup in self.backups():
                    for path in backup.iterdir(): path.unlink()
                    backup.rmdir()
                kept = self.switch(enabled)
                self.assertEqual(kept, self.backups()[0])
                self.assertEqual((kept / 'hyprflip-navigation.lua').read_bytes(), own)
                self.assertEqual(self.paths.module.exists() and self.paths.module.read_bytes(), enabled and SHIPPED)

    def test_already_so_records_the_choice_without_a_reload(self):
        self.switch(False)
        self.assertEqual(navigation.choice(self.paths), 'off')
        self.assertEqual((self.hyprland.reloads, self.backups()), (0, []))
        self.switch(True)
        self.hyprland.calls.clear()
        self.paths.record.unlink()
        self.switch(True)
        self.assertEqual(self.hyprland.calls, [])
        self.assertTrue(self.paths.record.exists())

    def test_a_line_without_its_file_and_a_file_without_its_line_count_as_off_and_switch(self):
        self.paths.main.write_text(self.original + LINES[1:])
        self.switch(False)
        self.assertEqual(self.paths.main.read_text(), self.original)
        self.paths.module.write_bytes(SHIPPED)
        self.switch(False)
        self.assertFalse(self.paths.module.exists())
        self.paths.main.write_text(self.original + LINES[1:])
        self.switch(True)
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'on')

    def assertUnchanged(self, main, module, choice=None, backups=()):
        self.assertEqual(self.paths.main.read_text(), main)
        self.assertEqual(self.paths.module.read_bytes() if self.paths.module.exists() else None, module)
        self.assertEqual(navigation.choice(self.paths), choice)
        # a failed switch leaves no backup of its own
        self.assertEqual(self.backups(), list(backups))

    def test_keys_that_do_not_register_put_everything_back(self):
        self.hyprland.keys = self.hyprland.keys[:-1]
        self.paths.main.chmod(0o600)
        with self.assertRaisesRegex(navigation.Refused, r'"Move card or window down" did not register exactly once. '
                                                        'The shortcuts are as they were.'):
            self.switch(True)
        self.assertUnchanged(self.original, None)
        self.assertEqual(self.paths.main.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.paths.record.exists())
        self.assertEqual(self.hyprland.reloads, 2)

    def test_keys_that_stay_after_off_put_everything_back(self):
        self.switch(True)
        self.paths.choice.unlink()
        loaded, backups = self.paths.main.read_text(), self.backups()
        self.hyprland.load = lambda: True
        with self.assertRaisesRegex(navigation.Refused, 'is still there'):
            self.switch(False)
        self.assertUnchanged(loaded, SHIPPED, backups=backups)
        self.assertTrue(self.paths.record.exists())

    def test_only_a_new_configuration_error_refuses(self):
        self.hyprland.broken = True
        with self.assertRaisesRegex(navigation.Refused, 'Hyprland reported: hyprflip-navigation.lua:1: broken'):
            self.switch(True)
        self.assertUnchanged(self.original, None)
        # an error from before stays someone else's, and the broken module can still go off
        self.hyprland.errors = ['bindings.lua:3: an error of its own']
        self.paths.main.write_text(self.original + LINES[1:])
        self.paths.module.write_bytes(SHIPPED)
        self.hyprland.loaded = True
        self.switch(False)
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'off')

    def test_a_card_that_changed_during_the_reload_refuses(self):
        def reload_breaks_a_card(*args):
            if args == ('reload',): self.hyprland.cards = []
            return Hyprland.__call__(self.hyprland, *args)
        with self.assertRaisesRegex(navigation.Refused, 'A card changed while Hyprland reloaded'):
            navigation.switch(True, reload_breaks_a_card, self.paths, SHIPPED)
        self.assertUnchanged(self.original, None)

    def test_hyprland_that_fails_mid_switch_puts_everything_back(self):
        def failing(*args):
            if args == ('-j', 'binds'): raise RuntimeError('Hyprland is not responding.')
            return self.hyprland(*args)
        with self.assertRaisesRegex(navigation.Refused, '^Hyprland is not responding. The shortcuts are as they were.$'):
            navigation.switch(True, failing, self.paths, SHIPPED)
        self.assertUnchanged(self.original, None)

    def test_no_core_to_ask_still_switches(self):
        def coreless(*args):
            if args == ('hyprflip', 'status'): return 'unknown request'
            return self.hyprland(*args)
        navigation.switch(True, coreless, self.paths, SHIPPED)
        self.assertEqual(navigation.state(self.paths, SHIPPED), 'on')

    def test_a_missing_configuration_refuses_before_anything(self):
        self.paths.main.unlink()
        with self.assertRaisesRegex(navigation.Refused, 'existing Hyprland Lua configuration'):
            self.switch(True)
        self.assertEqual(self.hyprland.calls, [])
        self.assertFalse(self.paths.module.exists())

    def test_plan_matches_what_installs_did(self):
        self.assertIsNone(navigation.plan(self.paths, SHIPPED, False))
        self.assertEqual(navigation.plan(self.paths, SHIPPED, True), 'install')
        self.paths.module.write_bytes(SHIPPED)
        self.assertEqual(navigation.plan(self.paths, SHIPPED, False), 'current')
        self.paths.module.write_bytes(b'-- older\n')
        navigation.record(self.paths, b'-- older\n')
        self.assertEqual(navigation.plan(self.paths, SHIPPED, False), 'update')
        self.paths.module.write_bytes(b'-- mine\n')
        self.assertEqual((navigation.plan(self.paths, SHIPPED, False), navigation.plan(self.paths, SHIPPED, True)),
                         ('kept', 'replace'))


if __name__ == '__main__': unittest.main()
