"""Card presentation preferences are bounded data, reversible and independent."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from copy import deepcopy
from setup_test import setup
import saved_test


class PreferencesTest(unittest.TestCase):
    def test_persistent_preference_and_failed_apply_rollback(self):
        for method, field, filename, initial, value in (
            ('save_appearance', 'card_frame', 'appearance', True, 'classic'),
            ('save_spacing', 'card_gap', 'card_gap', -1, 12),
        ):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                ipc = setup.Hyprctl({'XDG_STATE_HOME': directory})
                state = {field: initial}
                ipc.status = lambda: state.copy()
                ipc.call = lambda *args: None
                path = Path(directory) / 'hyprflip' / filename
                with self.assertRaises(setup.SetupError): getattr(ipc, method)(value)
                self.assertFalse(path.exists())
                def apply(*args): state[field] = False if field == 'card_frame' else 12
                ipc.call = apply
                getattr(ipc, method)(value)
                self.assertEqual(path.read_text(), str(value) + '\n')
                ipc.call = lambda *args: None
                with self.assertRaises(setup.SetupError):
                    getattr(ipc, method)('frame' if field == 'card_frame' else -1)
                self.assertEqual(path.read_text(), str(value) + '\n')
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_or_unsupported_options_do_not_write_or_dispatch(self):
        ipc = setup.Hyprctl()
        for method, values in (('save_appearance', ('classic";oops', None, 1)),
                               ('save_spacing', (-2, 129, True, '12', 1.5))):
            with patch.object(ipc, 'call') as call, patch.object(ipc, 'status', return_value={}):
                for value in values:
                    with self.assertRaises(setup.SetupError): getattr(ipc, method)(value)
                call.assert_not_called()
        with patch.object(ipc, 'status', return_value={}):
            with self.assertRaises(setup.SetupError): ipc.save_appearance('classic')
            with self.assertRaises(setup.SetupError): ipc.save_spacing(12)

    def test_accent_ring_and_color_persist_and_roll_back(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = setup.Hyprctl({'XDG_STATE_HOME': directory})
            state = {'accent_ring': False, 'accent_color': ''}
            calls = []
            ipc.status = lambda: state.copy()
            def apply(*args):
                calls.append(args[1])
                key, value = args[1].split('hyprflip={')[1].rstrip('}})').split('=')
                state[key] = value == 'true' if key == 'accent_ring' else value.strip('"')
            ipc.call = apply
            root = Path(directory) / 'hyprflip'
            ipc.save_accent_color('#f78dbb')
            ipc.save_accent_ring(True)
            self.assertEqual(state, {'accent_ring': True, 'accent_color': '#F78DBB'})
            self.assertEqual((root / 'accent_ring').read_text(), 'on\n')
            self.assertEqual((root / 'accent_color').read_text(), '#F78DBB\n')
            ipc.save_accent_color('#F78DBB')
            self.assertEqual(len(calls), 2, 'an unchanged theme accent is not dispatched again')
            ipc.call = lambda *args: None
            with self.assertRaises(setup.SetupError): ipc.save_accent_color('#123456')
            self.assertEqual((root / 'accent_color').read_text(), '#F78DBB\n')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['accent_color', 'accent_ring'])

    def test_invalid_accent_or_older_core_does_not_write_or_dispatch(self):
        ipc = setup.Hyprctl()
        with patch.object(ipc, 'call') as call, patch.object(ipc, 'status', return_value={'accent_ring': False, 'accent_color': ''}):
            for value in ('F78DBB', '#F78DB', '#F78DBBAA', '"#F78DBB"', '#F78DBG', None, 0xF78DBB):
                with self.assertRaises(setup.SetupError): ipc.save_accent_color(value)
            for value in (None, 1, 'on'):
                with self.assertRaises(setup.SetupError): ipc.save_accent_ring(value)
            call.assert_not_called()
        with patch.object(ipc, 'call') as call, patch.object(ipc, 'status', return_value={}):
            with self.assertRaises(setup.SetupError): ipc.save_accent_ring(True)
            with self.assertRaises(setup.SetupError): ipc.save_accent_color('#F78DBB')
            call.assert_not_called()


class FivePaneRecipesTest(unittest.TestCase):
    setUp = saved_test.SavedTest.setUp

    def test_five_apps_round_trip_and_six_are_rejected(self):
        recipe = deepcopy(self.recipe)
        for face in recipe['faces']:
            face['apps'] = [deepcopy(face['apps'][0]) for _ in range(5)]
            face['ratios'] = [.1, .15, .2, .25, .3]
            face['focus'] = 4
        self.store.update('Five', recipe, None)
        self.assertEqual(self.store.read()['Five'], recipe)
        recipe['faces'][0]['apps'].append(deepcopy(recipe['faces'][0]['apps'][0]))
        recipe['faces'][0]['ratios'] = [1/6]*6
        with self.assertRaises(ValueError): self.store.validate(recipe)

    def test_five_app_recipe_explains_need_for_newer_core(self):
        recipe = deepcopy(self.recipe)
        recipe['faces'][1]['apps'] = [deepcopy(recipe['faces'][1]['apps'][0]) for _ in range(5)]
        recipe['faces'][1]['ratios'] = [.2]*5
        with self.assertRaises(setup.SetupError):
            setup.Saved(self.ipc, None).prepare_open('Five', recipe, 2, '0xb')
