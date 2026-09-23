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
