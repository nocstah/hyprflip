"""Exercise the panel protocol at its trust and cancellation boundaries."""
from contextlib import nullcontext
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from edit_test import CardIPC
from setup_test import setup

sys.modules['workflow'] = setup
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('hyprflip_panel_control', Path(__file__).resolve().parents[1] / 'scripts/control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class Request:
    def check(self): pass
    def exclusive(self): return nullcontext()


class Channel:
    def __init__(self, callback=lambda: None): self.callback, self.handoffs = callback, 0
    def handoff(self): self.handoffs += 1; self.callback()


class PanelControlTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ipc = CardIPC(full=True)
        settings = patch.object(control.shortcuts, 'snapshot', return_value={'available': False, 'rows': [], 'occupied': []})
        settings.start()
        self.addCleanup(settings.stop)
        self.ipc.env = {'HYPRLAND_INSTANCE_SIGNATURE': 'test-instance', 'XDG_STATE_HOME': self.directory.name}
        original = self.ipc.data
        self.ipc.data = lambda *args: {'int': 420 if args[-1].endswith('duration_ms') else 1} if 'getoption' in args else original(*args)
        self.ipc.snapshot.update(transition='flip', transition_modes=['flip', 'instant'], layout_controls=True)
        self.ctx = control.context(self.ipc)
        card = self.ipc.snapshot['containers'][0]
        self.target = dict(id=1, kind='container', token=control.card_token(card, 'container', self.ipc.windows(), self.ctx['instance']))

    def payload(self, action='flip', **extra):
        return dict(protocol=1, action=action, context=self.ctx, target=self.target, **extra)

    def run_action(self, payload, callback=lambda: None):
        channel = Channel(callback)
        return control.run_operation(self.ipc, payload, control.PanelMenu(channel, Request()))

    def test_snapshot_is_read_only_and_normalizes_both_faces(self):
        result = control.snapshot(self.ipc)
        self.assertTrue(result['available'])
        self.assertEqual(result['cards'][0]['faces'][1]['panes'][1]['address'], '0xc')
        self.assertEqual(result['cards'][0]['token'], self.target['token'])
        self.assertEqual(result['duration_ms'], 420)
        self.assertTrue(result['motion_enabled'])
        self.assertEqual(result['context']['anchor_label'], 'Terminal')
        self.assertEqual(self.ipc.mutations, [])

    def test_context_rejects_navigation_restart_and_reused_address(self):
        for mutation in ('workspace', 'focus', 'restart', 'pid'):
            with self.subTest(mutation=mutation):
                saved = deepcopy((self.ipc.clients, self.ipc.env))
                if mutation == 'workspace': self.ipc.workspace = 9
                if mutation == 'focus': self.ipc.active = '0xd'
                if mutation == 'restart': self.ipc.env['HYPRLAND_INSTANCE_SIGNATURE'] = 'new'
                if mutation == 'pid': self.ipc.clients['0xb']['pid'] += 1
                with self.assertRaises(setup.SetupError): self.run_action(self.payload())
                self.assertEqual(self.ipc.mutations, [])
                self.ipc.clients, self.ipc.env = saved
                self.ipc.workspace, self.ipc.active = 2, '0xb'

    def test_native_boolean_animation_setting_is_reported(self):
        original = self.ipc.data
        self.ipc.data = lambda *args: {'bool': False} if args[-1] == 'animations:enabled' else original(*args)
        self.assertFalse(control.snapshot(self.ipc)['motion_enabled'])

    def test_layer_surface_can_release_focus_without_retargeting(self):
        self.ipc.active = None
        self.run_action(self.payload())
        self.assertIn(('action', 'flip'), self.ipc.mutations)
        self.assertEqual(self.ipc.active, '0xb')

    def test_handoff_revalidates_card_before_mutation(self):
        def change(): self.ipc.snapshot['containers'][0]['faces'][1].pop()
        with self.assertRaisesRegex(setup.SetupError, 'card changed'):
            self.run_action(self.payload(), change)
        self.assertEqual(self.ipc.mutations, [])

    def test_invalid_choices_never_move_focus(self):
        invalid = [self.payload('preview', mode='flip; bad'), self.payload('edit', face=True),
                   self.payload('edit', face=0, intent='remove', pane='0xb'),
                   self.payload('edit', face=0, intent='remove', pane='0xa'),
                   self.payload() | {'protocol': True}]
        for payload in invalid:
            with self.assertRaises(setup.SetupError): self.run_action(payload)
        self.assertEqual(self.ipc.mutations, [])

    def test_native_pair_edits_explain_card_requirement(self):
        pair = dict(id=3, front='0xa', back='0xb', current='0xb')
        self.ipc.snapshot['pairs'] = [pair]
        target = dict(id=3, kind='pair', token=control.card_token(pair, 'pair', self.ipc.windows(), self.ctx['instance']))
        with self.assertRaisesRegex(setup.SetupError, 'multi-app card'):
            self.run_action(self.payload('edit') | {'target': target})
        self.assertEqual(self.ipc.mutations, [])

    def test_pane_actions_route_by_ids_and_keep_unfocused_pane(self):
        card = self.ipc.snapshot['containers'][0]
        self.assertEqual(control.edit_prefix('remove', '0xc', 1, card, {}), ['release:0xc'])
        self.assertEqual(control.edit_prefix('replace', '0xc', 1, card, {}), ['replace', '0xc'])
        self.assertEqual(control.edit_prefix('previous', '0xc', 1, card, {}), ['layout', 'reorder'])
        card['faces'][1].append('0xd')
        self.assertEqual(control.edit_prefix('next', '0xc', 1, card, {}), ['layout', 'reorder', '1:2'])

    def test_hidden_face_is_shown_before_focusing_its_app(self):
        def flip(*operations):
            self.assertEqual(operations, (('0xb', 'flip'),))
            card = self.ipc.snapshot['containers'][0]
            card['active'], card['current'] = 0, '0xa'
        with patch.object(self.ipc, 'focused', side_effect=flip), \
             patch.object(setup.Edit, 'prepare', side_effect=setup.Cancelled) as prepare:
            with self.assertRaises(setup.Cancelled): self.run_action(self.payload('edit', face=0))
            prepare.assert_called_once_with('0xa')
            self.assertEqual(self.ipc.active, '0xa')

    def test_named_open_has_no_extra_confirmation(self):
        recipe = {'example': 'definition'}
        plan = setup.SavedPlan('goto', 'Mail', recipe, None)
        with patch.object(setup.RecipeStore, 'read', return_value={'Mail': recipe}), \
             patch.object(setup.Saved, 'prepare_named', return_value=plan) as prepare, \
             patch.object(setup.Saved, 'apply', return_value='Opened') as apply:
            result = self.run_action(self.payload('open', name='Mail', recipe_token=control.digest(recipe)))
            self.assertEqual(result, 'Opened')
            prepare.assert_called_once_with('Mail', recipe, 2, '0xb')
            apply.assert_called_once_with(plan)

    def test_changed_saved_definition_is_rejected(self):
        with patch.object(setup.RecipeStore, 'read', return_value={'Mail': {'new': True}}):
            with self.assertRaisesRegex(setup.SetupError, 'saved card changed'):
                self.run_action(self.payload('open', name='Mail', recipe_token=control.digest({'old': True})))


class ChannelTest(unittest.TestCase):
    def setUp(self):
        read, write = os.pipe()
        self.source, self.writer = os.fdopen(read, 'r'), os.fdopen(write, 'w')
        self.addCleanup(self.source.close)
        self.addCleanup(self.writer.close)
        self.out = io.StringIO()
        self.channel = control.Channel(self.source, self.out)

    def send(self, value):
        self.writer.write(json.dumps(value) + '\n'); self.writer.flush()

    def test_choice_round_trip_does_not_evaluate_labels(self):
        label = '<b>$(touch nope)</b>'
        self.send({'reply': 1, 'value': 'pane:2'})
        self.send({'resume': 2})
        menu = control.PanelMenu(self.channel, Request())
        self.assertEqual(menu.choose('Choose', [setup.Choice('pane:2', label)]), 'pane:2')
        self.assertEqual(json.loads(self.out.getvalue().splitlines()[0])['choices'][0]['label'], label)

    def test_cancel_interrupts_even_when_a_reply_is_already_buffered(self):
        self.send({'reply': 1, 'value': 'ok'})
        self.send({'cancel': True})
        with self.assertRaises(setup.Cancelled): self.channel.pump()

    def test_closed_panel_cancels_pending_open(self):
        self.writer.close()
        with self.assertRaises(setup.Cancelled): self.channel.wait('resume', 1)

    def test_expired_or_unbounded_responses_are_rejected(self):
        self.send({'reply': 0, 'value': 'wrong'})
        with self.assertRaisesRegex(setup.SetupError, 'expired'): self.channel.wait('reply', 1)
        self.channel.buffer = b'x' * control.MAX_MESSAGE
        self.send({})
        with self.assertRaisesRegex(setup.SetupError, 'large'): self.channel.pump()


class DurationTest(unittest.TestCase):
    def test_persistence_and_failed_config_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = setup.Hyprctl({'XDG_STATE_HOME': directory})
            pref = Path(directory) / 'hyprflip/duration_ms'
            with patch.object(ipc, 'data', side_effect=[{'int': 420}, {'int': 280}]), patch.object(ipc, 'call'):
                ipc.save_duration(280)
            self.assertEqual(pref.read_text(), '280\n')
            with patch.object(ipc, 'data', side_effect=[{'int': 280}, {'int': 280}]), patch.object(ipc, 'call') as call:
                with self.assertRaises(setup.SetupError): ipc.save_duration(600)
                self.assertIn('duration_ms=280', call.call_args.args[1])
            self.assertEqual(pref.read_text(), '280\n')
            for bad in (True, -1, 2001, '500; bad'):
                with self.assertRaises(setup.SetupError): ipc.save_duration(bad)


if __name__ == '__main__': unittest.main()
