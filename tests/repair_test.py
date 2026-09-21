"""Partial saved-card restoration: identity, proportions, cancellation and rollback."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from edit_test import CardIPC
from saved_test import Menu
from setup_test import setup, window


class RepairIPC(CardIPC):
    def __init__(self):
        super().__init__(full=True)
        self.snapshot.update(repair_cards=True, workspace_protection=True, marked=None)
        self.card = self.snapshot['containers'][0]
        self.card['faces'][1].append('0xd')
        self.card['layouts'] = [dict(axis='horizontal', ratios=[1.], focused='0xa'),
                                dict(axis='vertical', ratios=[.2, .3, .5], focused='0xb')]
        self.fail = None

    def windows(self): return deepcopy(self.clients)
    def status(self): return deepcopy(self.snapshot)

    def focus(self, address):
        super().focus(address)
        for side, members in enumerate(self.card['faces']):
            if address in members:
                self.card.update(active=side, current=address)
                self.card['layouts'][side]['focused'] = address

    def remove(self, address, close=True):
        for side, members in enumerate(self.card['faces']):
            if address in members:
                layout = self.card['layouts'][side]
                index = members.index(address); members.pop(index); layout['ratios'].pop(index)
                total = sum(layout['ratios']); layout['ratios'] = [r / total for r in layout['ratios']]
                if layout['focused'] == address: layout['focused'] = members[0]
                if self.card['active'] == side: self.card['current'] = layout['focused']
        if close: self.clients.pop(address)
        self.active = self.card['current']

    def action(self, action):
        super().action(action)
        if self.fail and self.fail(action): raise setup.SetupError('Injected layout failure')
        if action.startswith('attach '):
            side = self.card['active']; members = self.card['faces'][side]; layout = self.card['layouts'][side]
            if len(members) == 1: layout['axis'] = action.split()[1]
            layout['ratios'] = [r * len(members) / (len(members) + 1) for r in layout['ratios']] + [1 / (len(members) + 1)]
            members.append(self.snapshot['marked']); self.snapshot['marked'] = None
        if action == 'release': self.remove(self.active, close=False)
        if action.startswith('arrange '):
            _, axis, *pairs = action.split(); addresses, ratios = zip(*(p.split(':') for p in pairs))
            side = self.card['active']
            assert set(addresses) == set(self.card['faces'][side])
            self.card['faces'][side] = list(addresses)
            self.card['layouts'][side].update(axis=axis, ratios=list(map(float, ratios)))

    def tile(self, w):
        self.mutations.append(('tile', w['address'])); self.clients[w['address']]['floating'] = False

    def restore_float(self, w):
        self.mutations.append(('float', w['address'])); self.clients[w['address']]['floating'] = True


class RepairTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root, self.ipc = Path(directory.name), RepairIPC()
        self.ipc.env = dict(XDG_STATE_HOME=str(self.root / 'state'), XDG_DATA_HOME=str(self.root / 'data'),
                            XDG_DATA_DIRS=str(self.root / 'empty'))
        apps = self.root / 'data/applications'; apps.mkdir(parents=True)
        for i, (a, w) in enumerate(self.ipc.clients.items()):
            w.update({'class': 'app-' + a, 'initialClass': 'app-' + a, 'title': 'Title ' + a,
                      'at': [i * 500, 0], 'size': [500, 700]})
            (apps / (a + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName=App ' + a +
                '\nStartupWMClass=app-' + a + '\nExec=/usr/bin/true\n')
        self.original = deepcopy(self.ipc.clients)
        self.recipe = setup.Saved.capture(self.ipc.card, self.ipc.windows())
        self.store = setup.RecipeStore(self.ipc.env); self.store.update('Comms', self.recipe, None)

    def prepare(self, *answers):
        flow = setup.Edit(self.ipc, Menu('repair', *answers))
        return flow, flow.prepare(self.ipc.active)

    def launch(self, entry):
        old = entry.id.removesuffix('.desktop')
        address = hex(int(old, 16) + 32)
        self.ipc.clients[address] = self.original[old] | {'address': address, 'pid': 90 + int(old, 16)}
        self.ipc.active = address
        return Mock(poll=lambda: 0)

    def apply(self, flow, plan):
        with patch.object(setup.DesktopApps, 'launch', side_effect=self.launch), patch.object(setup, 'Opening'):
            flow.apply(plan)

    def test_first_middle_and_last_missing_pane_restore_in_place_and_preserve_survivor_weights(self):
        for missing in ('0xb', '0xc', '0xd'):
            with self.subTest(missing=missing):
                self.ipc = RepairIPC(); self.ipc.env = dict(XDG_STATE_HOME=str(self.root / 'state'),
                    XDG_DATA_HOME=str(self.root / 'data'), XDG_DATA_DIRS=str(self.root / 'empty'))
                self.ipc.clients = deepcopy(self.original)
                self.ipc.remove(missing)
                self.ipc.card['layouts'][1].update(axis='horizontal', ratios=[.7, .3])
                before = deepcopy(self.ipc.card); survivors = list(before['faces'][1])
                flow, plan = self.prepare(); self.apply(flow, plan)
                new = hex(int(missing, 16) + 32)
                expected = [[a.replace(missing, new) for a in face] for face in [['0xa'], ['0xb', '0xc', '0xd']]]
                self.assertEqual(self.ipc.card['faces'], expected)
                self.assertEqual(self.ipc.card['id'], before['id'])
                self.assertEqual(self.ipc.active, before['current'])
                layout = self.ipc.card['layouts'][1]; weights = dict(zip(expected[1], layout['ratios']))
                self.assertAlmostEqual(weights[survivors[0]] / weights[survivors[1]], 7 / 3)
                self.assertAlmostEqual(weights[new], self.recipe['faces'][1]['ratios'][['0xb','0xc','0xd'].index(missing)])
                self.assertEqual(layout['axis'], 'horizontal')
                self.assertEqual(self.ipc.card['layouts'][0], before['layouts'][0])
                self.assertFalse(any(action in ('pair', 'unpair') for kind, action, *rest in self.ipc.mutations if kind == 'action'))

    def test_two_missing_apps_restore_to_original_slots_and_keep_front_visible_unfolded(self):
        self.ipc.remove('0xb'); self.ipc.remove('0xd'); self.ipc.focus('0xa')
        self.ipc.card['unfolded'] = True
        flow, plan = self.prepare(); self.apply(flow, plan)
        self.assertEqual(self.ipc.card['faces'], [['0xa'], ['0x2b','0xc','0x2d']])
        self.assertEqual(self.ipc.card['layouts'][1]['ratios'], [.2,.3,.5])
        self.assertEqual(self.ipc.card['layouts'][1]['axis'], 'vertical')
        self.assertEqual(self.ipc.card['current'], '0xa'); self.assertTrue(self.ipc.card['unfolded'])

    def test_existing_remote_float_is_reused_without_launching(self):
        self.ipc.remove('0xc', close=False)
        self.ipc.clients['0xc'].update(workspace={'id':8,'name':'8'}, floating=True)
        flow, plan = self.prepare()
        with patch.object(setup.DesktopApps, 'launch') as launch: flow.apply(plan)
        launch.assert_not_called()
        self.assertEqual(self.ipc.card['faces'][1], ['0xb','0xc','0xd'])
        self.assertEqual(self.ipc.clients['0xc']['workspace']['id'], 2)
        self.assertFalse(self.ipc.clients['0xc']['floating'])

    def test_ambiguous_definitions_require_one_choice_and_no_extra_confirmation(self):
        self.store.update('Work', self.recipe, None); self.ipc.remove('0xc')
        flow, plan = self.prepare('1')
        self.assertEqual(plan.name, 'Work')
        self.assertEqual(len(flow.menu.prompts), 2)
        self.assertEqual([c.label for c in flow.menu.prompts[1][1]], ['Comms','Work'])
        self.assertEqual(self.ipc.mutations, [])

    def test_indistinguishable_slots_and_changed_sides_are_not_guessed(self):
        self.ipc.remove('0xc')
        recipe = deepcopy(self.recipe)
        for app in recipe['faces'][1]['apps']: app.update({'class':'browser', 'initial_class':'browser', 'title':'Same'})
        for a in ('0xb','0xd'): self.ipc.clients[a].update({'class':'browser','initialClass':'browser','title':'Changed'})
        self.assertIsNone(setup.Saved.surviving_slots(recipe, self.ipc.card, self.ipc.clients))
        self.ipc.clients['0xb']['title'] = 'First'; recipe['faces'][1]['apps'][0]['title'] = 'First'
        self.ipc.clients['0xd']['title'] = 'Last'; recipe['faces'][1]['apps'][2]['title'] = 'Last'
        self.assertEqual(setup.Saved.surviving_slots(recipe, self.ipc.card, self.ipc.clients), ['0xa','0xb',None,'0xd'])
        self.ipc.card['faces'].reverse()
        self.assertIsNone(setup.Saved.surviving_slots(recipe, self.ipc.card, self.ipc.clients))

    def test_complete_and_unknown_cards_explain_why_nothing_can_reopen(self):
        with self.assertRaisesRegex(setup.SetupError, 'already here'): self.prepare()
        self.store.update('Comms', None, self.recipe)
        with self.assertRaisesRegex(setup.SetupError, 'Save the complete card'): self.prepare()
        self.assertEqual(self.ipc.mutations, [])

    def test_app_in_another_card_is_never_stolen_or_duplicated(self):
        self.ipc.remove('0xc', close=False)
        self.ipc.snapshot['containers'].append(dict(id=2, faces=[['0xc'],['0xe']]))
        with self.assertRaisesRegex(setup.SetupError, 'already open but unavailable'): self.prepare()
        self.assertEqual(self.ipc.mutations, [])

    def test_changed_card_during_launch_aborts_before_layout_mutation(self):
        self.ipc.remove('0xc'); flow, plan = self.prepare()
        def launch(entry):
            result = self.launch(entry)
            self.ipc.card['layouts'][1]['ratios'] = [.1,.9]
            return result
        with patch.object(setup.DesktopApps, 'launch', side_effect=launch), patch.object(setup, 'Opening'):
            with self.assertRaisesRegex(setup.SetupError, 'layout changed'): flow.apply(plan)
        self.assertFalse(any(m[0] == 'focus' or m[0] == 'move' for m in self.ipc.mutations))
        self.assertEqual(self.ipc.card['faces'], [['0xa'],['0xb','0xd']])

    def test_timeout_leaves_card_untouched_and_apps_open(self):
        self.ipc.remove('0xc'); _, plan = self.prepare(); before = deepcopy(self.ipc.card)
        flow = setup.Saved(self.ipc, Menu())
        with patch.object(setup.DesktopApps, 'launch', return_value=Mock(poll=lambda: 0)), patch.object(setup, 'Opening'):
            with self.assertRaisesRegex(setup.SetupError, 'Still waiting'): flow.apply_open(plan, timeout=0)
        self.assertEqual(self.ipc.card, before)

    def test_a_resize_during_import_is_not_overwritten_by_recovery(self):
        self.ipc.remove('0xc', close=False)
        self.ipc.clients['0xc']['workspace'] = {'id':8,'name':'8'}
        flow, plan = self.prepare(); move = self.ipc.move
        def resized(address, workspace):
            move(address, workspace)
            self.ipc.card['layouts'][1]['ratios'] = [.1,.9]
        with patch.object(self.ipc, 'move', side_effect=resized):
            with self.assertRaisesRegex(setup.SetupError, 'layout changed'): flow.apply(plan)
        self.assertEqual(self.ipc.card['layouts'][1]['ratios'], [.1,.9])
        self.assertEqual(self.ipc.card['faces'][1], ['0xb','0xd'])
        self.assertEqual(self.ipc.clients['0xc']['workspace']['id'], 8)
        self.assertFalse(any(m[0] == 'action' and m[1].startswith(('attach','arrange')) for m in self.ipc.mutations))

    def test_cancellation_leaves_card_untouched(self):
        self.ipc.remove('0xc'); flow, plan = self.prepare(); before = deepcopy(self.ipc.card)
        with patch.object(setup.DesktopApps, 'launch', side_effect=self.launch), patch.object(setup, 'Opening') as progress:
            progress.return_value.check.side_effect = setup.Cancelled()
            with self.assertRaises(setup.Cancelled): flow.apply(plan)
        self.assertEqual(self.ipc.card, before); self.assertIn('0x2c', self.ipc.clients)

    def test_failed_second_attachment_rolls_back_only_additions(self):
        self.ipc.remove('0xb'); self.ipc.remove('0xd'); self.ipc.focus('0xa')
        before = deepcopy(self.ipc.card); flow, plan = self.prepare()
        self.ipc.fail = lambda action: action.startswith('attach ') and len(self.ipc.card['faces'][1]) == 2
        with self.assertRaisesRegex(setup.SetupError, 'Injected layout failure'): self.apply(flow, plan)
        self.assertEqual(self.ipc.card, before); self.assertEqual(self.ipc.active, '0xa')
        self.assertTrue({'0x2b','0x2d'} <= self.ipc.clients.keys())
        self.assertNotIn(('action','unpair'), self.ipc.mutations)

    def test_failed_final_layout_returns_imported_float_and_restores_ratios_and_mark(self):
        self.ipc.remove('0xc', close=False)
        self.ipc.clients['0xc'].update(workspace={'id':8,'name':'8'}, floating=True)
        self.ipc.clients['0xe'] = window('0xe'); self.ipc.snapshot['marked'] = '0xe'
        before = deepcopy(self.ipc.card); flow, plan = self.prepare(); refused = False
        def fail(action):
            nonlocal refused
            if action.startswith('arrange ') and not refused: refused = True; return True
            return False
        self.ipc.fail = fail
        with self.assertRaisesRegex(setup.SetupError, 'Injected layout failure'): flow.apply(plan)
        for old, actual in zip(before['layouts'], self.ipc.card['layouts']):
            for a,b in zip(old['ratios'], actual['ratios']): self.assertAlmostEqual(a,b)
        self.assertEqual(self.ipc.card['faces'], before['faces'])
        self.assertEqual(self.ipc.active, before['current']); self.assertEqual(self.ipc.snapshot['marked'], '0xe')
        self.assertEqual(self.ipc.clients['0xc']['workspace']['id'], 8); self.assertTrue(self.ipc.clients['0xc']['floating'])


if __name__ == '__main__': unittest.main()
