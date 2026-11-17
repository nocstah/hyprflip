#!/usr/bin/env python3
"""Hyprctl.call reads replies that carry app- and user-chosen text: a window class
or workspace name holding "Lua error", or bytes that are not UTF-8, must not make
a status read fail. A recording hyprctl first on PATH answers with given bytes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w


class HyprctlCallTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.reply = self.root / 'reply'
        self.code = self.root / 'code'
        fake = self.root / 'hyprctl'
        fake.write_text(f'#!{sys.executable} -I\n'
                        'import sys\n'
                        f'sys.stdout.buffer.write(open({str(self.reply)!r}, "rb").read())\n'
                        f'sys.exit(int(open({str(self.code)!r}).read()))\n')
        fake.chmod(0o700)
        self.ipc = w.Hyprctl(dict(os.environ, PATH=f'{self.root}:{os.environ["PATH"]}',
                                  HYPRLAND_INSTANCE_SIGNATURE='hyprctl-call-test-bogus'))

    def tearDown(self):
        self.directory.cleanup()

    def answer(self, reply: bytes, code=0):
        self.reply.write_bytes(reply)
        self.code.write_text(str(code))

    def test_json_naming_lua_error_parses(self):
        status = {'containers': [], 'closes': {'list': [{'initial_class': 'Lua error x', 'reason': 'requested'}]}}
        self.answer(json.dumps(status).encode())
        self.assertEqual(self.ipc.status(), status)
        self.answer(json.dumps([{'class': 'Lua error: boom', 'address': '0x1'}]).encode())
        self.assertEqual(self.ipc.windows(), {'0x1': {'class': 'Lua error: boom', 'address': '0x1'}})

    def test_plain_lua_error_still_raises(self):
        self.answer(b'Lua error: boom\n')
        with self.assertRaises(w.SetupError):
            self.ipc.call('eval', 'boom()')
        self.answer(b'error: no such window\n')
        with self.assertRaises(w.SetupError) as raised:
            self.ipc.call('hyprflip', 'flip')
        self.assertEqual(str(raised.exception), 'no such window')
        self.answer(b'{}', code=1)
        with self.assertRaises(w.SetupError):
            self.ipc.call('hyprflip', 'status')

    def test_invalid_utf8_inside_json_parses_as_replacement(self):
        self.answer(b'{"closes":{"list":[{"initial_class":"app\xff\xfeend"}]}}')
        self.assertEqual(self.ipc.status()['closes']['list'][0]['initial_class'], 'app��end')


if __name__ == '__main__':
    unittest.main()
