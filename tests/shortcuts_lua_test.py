"""examples/shortcuts.lua leaves keys that another module claims (hyprflip_claimed_keys) to that module.

Runs the shipped module in a plain Lua interpreter with a stand-in for Hyprland's hl.bind.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LUA = shutil.which('lua') or shutil.which('lua5.4')

DRIVER = r'''
local bound = {}
hl = {bind = function(chord, callback, options)
    local handle = {chord = chord, description = options.description}
    function handle:remove() self.removed = true end
    bound[#bound + 1] = handle
    return handle
end}
hyprflip_claimed_keys = CLAIMS
local M = dofile(MODULE)
local function bind(chord, description) return M.bind(chord, function() end, {description = description}) end
local results = {
    create = bind("SUPER + CTRL + ALT + O", "Hyprflip: unfold, fold or create a card") == nil,
    edit = bind("SUPER + CTRL + ALT + C", "Hyprflip: edit card") ~= nil,
    find = bind("SUPER + CTRL + ALT + K", "Hyprflip: find an app in cards") ~= nil,
    other = bind("SUPER + CTRL + ALT + O", "Somebody else's action") ~= nil,
    configure_onto_claim = M.configure("edit", 76, "o"),
    configure_elsewhere = M.configure("edit", 76, "X"),
    configure_claimed = M.configure("create", 76, "F9"),
}
local names = {}
for name in pairs(results) do names[#names + 1] = name end
table.sort(names)
for _, name in ipairs(names) do print(name .. "=" .. tostring(results[name])) end
'''


@unittest.skipUnless(LUA, 'a Lua interpreter is needed')
class ShortcutsLuaTest(unittest.TestCase):
    def run_driver(self, claims):
        with tempfile.TemporaryDirectory() as state:
            source = DRIVER.replace('CLAIMS', claims).replace('MODULE', repr(str(ROOT / 'examples/shortcuts.lua')))
            result = subprocess.run([LUA, '-'], input=source, capture_output=True, text=True, timeout=10,
                                    env={'XDG_STATE_HOME': state, 'HOME': state, 'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split('=') for line in result.stdout.split())

    def test_a_claimed_key_is_not_bound_and_cannot_be_configured_onto(self):
        results = self.run_driver('{["super+ctrl+alt+o"] = "Manager", ["SUPER + HYPER + K"] = "Unreadable"}')
        self.assertEqual(results, {
            'create': 'true',                # Hyprflip's own O is left to the owner, whatever the case or spacing
            'edit': 'true', 'find': 'true',  # other keys bind; an unknown modifier claims nothing
            'other': 'true',                 # binds that are not Hyprflip's go straight to hl.bind
            'configure_onto_claim': 'false', 'configure_elsewhere': 'true',
            'configure_claimed': 'false',    # nothing of Hyprflip's is bound there to move
        })

    def test_without_claims_every_key_binds(self):
        for claims in ('nil', '{}', '"not a table"'):
            with self.subTest(claims=claims):
                results = self.run_driver(claims)
                self.assertEqual(results['create'], 'false')
                self.assertEqual(results['configure_onto_claim'], 'true')


if __name__ == '__main__':
    unittest.main()
