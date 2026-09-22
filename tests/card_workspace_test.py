from copy import deepcopy
import unittest
from unittest.mock import patch
import saved_test
from setup_test import setup


class WorkspaceTest(unittest.TestCase):
    setUp = saved_test.SavedTest.setUp
    saved = saved_test.SavedTest.saved
    def test_workspace_preference_set_clear_and_stale_update(self):
        self.store.update('Comms', self.recipe, None)
        flow=self.saved('0','workspace','number','3')
        plan=flow.prepare_manage()
        self.assertEqual(self.ipc.mutations, [])
        self.assertEqual(plan.recipe['workspace'],3)
        flow.apply(plan)
        self.assertEqual(self.store.read()['Comms']['workspace'],3)
        with self.assertRaisesRegex(setup.SetupError,'changed'): flow.apply(plan)
        flow=self.saved('0','workspace','current');flow.apply(flow.prepare_manage())
        self.assertNotIn('workspace',self.store.read()['Comms'])

    def test_invalid_workspace_data_and_input_are_rejected(self):
        for value in (0,-2,True,2147483648,'3',None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                setup.RecipeStore.validate(self.recipe | {'workspace':value})
        self.store.update('Comms',self.recipe,None)
        for value in ('-1','0','3;bad','2147483648'):
            with self.subTest(value=value),self.assertRaises(setup.SetupError):
                self.saved('0','workspace','number',value).prepare_manage()
        self.assertEqual(self.store.read()['Comms'],self.recipe)
        self.assertEqual(self.ipc.mutations,[])

    def test_update_preserves_workspace_assignment(self):
        self.store.update('Comms',self.recipe | {'workspace':3},None)
        flow=setup.Edit(self.ipc, __import__('saved_test').Menu('manage','update'))
        flow.apply(flow.prepare('0xb'))
        self.assertEqual(self.store.read()['Comms']['workspace'],3)

    def test_open_card_moves_to_pinned_workspace_after_context_check(self):
        recipe=self.recipe | {'workspace':3}
        self.store.update('Comms',recipe,None)
        flow=self.saved();plan=flow.prepare_named('Comms',recipe,2,'0xb')
        with patch.object(self.ipc,'focused') as focused:
            flow.apply(plan)
            focused.assert_called_once_with(('0xb','workspace 3'))


if __name__=='__main__':unittest.main()
