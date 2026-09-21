#!/usr/bin/env python3
"""Add the optional Hyprflip guard to Omachill 1.2 without vendoring its engine."""
import argparse
from pathlib import Path

MARKER = '-- Hyprflip workspace protection v1'


def prepare(source):
    if MARKER in source:
        return source

    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('Omachill changed; review the integration at: ' + old.splitlines()[0])
        source = source.replace(old, new)

    replace('local function tiled(w)', '''-- Hyprflip workspace protection v1
-- Resolve on every call: unloading/reloading the optional plugin must never
-- leave a Lua closure pointing into an unloaded shared library.
local card_holds = {} -- short leases for updating an unloaded compositor plugin
-- Lua is rebuilt during plugin loading. Read leases once on engine load so
-- the gap before the core can register its own reservations is also covered.
local card_holds_file = os.getenv("XDG_RUNTIME_DIR") .. "/hyprflip-chill-holds-"
  .. (os.getenv("HYPRLAND_INSTANCE_SIGNATURE") or "session")
do
  local file = io.open(card_holds_file, "r")
  if file then
    for line in file:lines() do
      local workspace, expiry = line:match("^(%d+) (%d+)$")
      workspace, expiry = tonumber(workspace), tonumber(expiry)
      if workspace and workspace > 0 and workspace < 2147483648 and expiry
        and expiry > os.time() and expiry <= os.time() + 120 then
        card_holds[workspace] = expiry
      end
    end
    file:close()
  end
end

local function card_workspace(ws)
  if not ws or not ws.id then return false end
  if (card_holds[ws.id] or 0) > os.time() then return true end
  local plugin = hl.plugin and hl.plugin.hyprflip
  if not plugin or not plugin.protects_workspace then return false end
  local ok, protected = pcall(plugin.protects_workspace, ws.id)
  return ok and protected == true
end

local function tiled(w)''')
    for name, args, guard in (
        ('float_into', 'w, ws', 'ws'),
        ('adopt_dropped', 'w, geo', 'w and w.workspace'),
        ('place_chilled', 'w, ws', 'ws'),
    ):
        anchor = f'local function {name}({args})\n'
        replace(anchor, anchor + f'  if card_workspace({guard}) then return end\n')
    replace('local function chill(ws)\n',
            'local function chill(ws)\n  if card_workspace(ws) then return 0 end\n')
    replace('if not win or not win.workspace or win.workspace.id ~= wsid then',
            'if not win or not win.workspace or win.workspace.id ~= wsid or card_workspace(win.workspace) then')
    replace('  local off = #windows_on(ws, chilled) > 0\n',
            '''  local off = #windows_on(ws, chilled) > 0
  if card_workspace(ws) and not off then
    notify("This workspace has a Hyprflip card. Ungroup the card before enabling Chill mode.")
    return
  end
''')
    replace('  if not AUTO or unloaded or in_auto or not ws or ws.special then return end\n',
            '  if not AUTO or unloaded or in_auto or not ws or ws.special or card_workspace(ws) then return end\n')
    replace('  if not CONVERT then return end\n',
            '  if not CONVERT or card_workspace(ws) then return end\n')
    replace('_G.chillmode = { toggle = toggle, state = state, hide = hide, restore = restore,',
            '''-- The picker has already reserved the workspace and collected every choice.
-- Hand over only the selected ungrouped app; leave unrelated floaters alone.
local function handoff(address)
  local w = hl.get_window("address:" .. address)
  if not w or not w.mapped or not card_workspace(w.workspace) then return false end
  if #tile_members(w) ~= 1 or w.fullscreen ~= 0 then return false end
  guarded(function() tile_out(w) end)
  if not any_chilled() then chill_globals_pop() end
  return true
end

local function handback(address, x, y, width, height)
  local w = hl.get_window("address:" .. address)
  if not w or not w.mapped or #tile_members(w) ~= 1 or w.fullscreen ~= 0 then return false end
  chill_globals_push()
  guarded(function()
    on_window(hl.dsp.window.tag, w, { tag = "+" .. TAG })
    on_window(hl.dsp.window.float, w, { action = "enable" })
    on_window(hl.dsp.window.resize, w, { x = width, y = height })
    on_window(hl.dsp.window.move, w, { x = x, y = y })
  end)
  return true
end

local function hold_workspace(workspace, seconds)
  if type(workspace) ~= "number" or workspace < 1 then return false end
  if type(seconds) ~= "number" or seconds < 0 or seconds > 120 then return false end
  card_holds[workspace] = seconds > 0 and (os.time() + seconds) or nil
  local temporary = card_holds_file .. ".new"
  local file = io.open(temporary, "w")
  if not file then return false end
  for id, expiry in pairs(card_holds) do
    if expiry > os.time() then file:write(string.format("%d %d\\n", id, expiry)) end
  end
  file:close()
  local ok = os.rename(temporary, card_holds_file)
  if not ok then os.remove(temporary) return false end
  return true
end

_G.chillmode = { hold_workspace = hold_workspace, handoff = handoff, handback = handback, toggle = toggle, state = state, hide = hide, restore = restore,''')
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(prepare(args.source.read_text()))
