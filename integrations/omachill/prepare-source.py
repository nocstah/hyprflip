#!/usr/bin/env python3
"""Add the optional Hyprflip integration to Omachill 1.2 without vendoring its engine.

Omachill 1.4.0 includes it already; this adapter leaves such engines unchanged.

v1 guards protected card workspaces; v2 measures a native card as one window, so
Chill floats and tiles it back whole. Each step applies once and upgrades a
source that already carries an earlier step.
"""
import argparse
from pathlib import Path

MARKER = '-- Hyprflip workspace protection v1'
GEOMETRY = '-- Hyprflip card geometry v2'
FULLSCREEN = '-- Hyprflip fullscreen chill v3'


def prepare(source):
    if MARKER not in source:
        source = protection(source)
    if GEOMETRY not in source:
        source = geometry(source)
    if FULLSCREEN not in source:
        source = fullscreen(source)
    return source


def fullscreen(source):
    state, replace = replacer(source)
    replace('local function toggle(selector)\n', '''-- Hyprflip fullscreen chill v3
-- Chill takes precedence over a fullscreen card: leave fullscreen, then chill.
-- A card that still cannot chill (hy3) gets its fullscreen back.
local function leave_card_fullscreen(ws)
  local plugin = hl.plugin and hl.plugin.hyprflip
  if not plugin or not plugin.card_box then return {} end
  local left = {}
  for _, w in ipairs(hl.get_windows({ workspace = ws.id })) do
    local ok, x = pcall(plugin.card_box, w.address)
    if w.fullscreen ~= 0 and ok and x then
      left[#left + 1] = { w = w, mode = w.fullscreen == 1 and "maximized" or "fullscreen" }
      on_window(hl.dsp.window.fullscreen, w, { action = "unset" })
    end
  end
  return left
end

local function toggle(selector)
''')
    replace('''  if card_workspace(ws) and not off then
    notify("This workspace's Hyprflip card can't chill right now. Leave fullscreen, or ungroup an hy3 card.")
    return
  end''', '''  if card_workspace(ws) and not off then
    local left = leave_card_fullscreen(ws)
    if card_workspace(ws) then
      for _, e in ipairs(left) do on_window(hl.dsp.window.fullscreen, e.w, { mode = e.mode, action = "set" }) end
      notify("This workspace's Hyprflip card can't chill. Ungroup an hy3 card first.")
      return
    end
  end''')
    return state['source']


def replacer(source):
    state = {'source': source}

    def replace(old, new):
        if state['source'].count(old) != 1:
            raise ValueError('Omachill changed; review the integration at: ' + old.splitlines()[0])
        state['source'] = state['source'].replace(old, new)
    return state, replace


def geometry(source):
    state, replace = replacer(source)
    replace('local function tiled(w)', '''-- Hyprflip card geometry v2
-- A native Hyprflip card is one native group, but its visible window fills
-- only one pane. Measure the whole card so it chills and tiles back whole.
local function tile_geometry(w)
  local plugin = hl.plugin and hl.plugin.hyprflip
  if plugin and plugin.card_box and w and w.address then
    local ok, x, y, width, height = pcall(plugin.card_box, w.address)
    if ok and x then return x, y, width, height end
  end
  local x, y = xy(w.at)
  local width, height = xy(w.size)
  return x, y, width, height
end

-- Hyprland resizes and moves a group through one window, relative to that
-- window. A card's window is one pane: place a floating card's frame itself,
-- and turn a tiled card size into the size of that pane.
local function place_tile(w, x, y, width, height)
  local plugin = hl.plugin and hl.plugin.hyprflip
  if plugin and plugin.card_place and w and w.address then
    local ok, placed = pcall(plugin.card_place, w.address, x, y, width, height)
    if ok and placed then return end
  end
  on_window(hl.dsp.window.resize, w, { x = width, y = height })
  on_window(hl.dsp.window.move, w, { x = x, y = y })
end

local function pane_inset(addr)
  local w = hl.get_window("address:" .. addr)
  if not w then return 0, 0 end
  local _, _, cw, ch = tile_geometry(w)
  local ww, wh = xy(w.size)
  return cw - ww, ch - wh
end

local function tiled(w)''')
    replace('''    on_window(hl.dsp.window.resize, w, { x = g.w, y = g.h })
    on_window(hl.dsp.window.move, w, { x = g.x, y = g.y })''', '''    place_tile(w, g.x, g.y, g.w, g.h)''')
    replace('''  on_window(hl.dsp.window.resize, w, { x = fw, y = fh })
  on_window(hl.dsp.window.move, w, { x = x, y = y })''', '''  place_tile(w, x, y, fw, fh)''')
    replace('''    focus_addr(keep)
    hl.dispatch(hl.dsp.window.resize({
      window = "address:" .. keep,
      x = node.axis == "x" and px or gk.w,
      y = node.axis == "y" and px or gk.h,
    }))''', '''    focus_addr(keep)
    local dw, dh = pane_inset(keep)
    hl.dispatch(hl.dsp.window.resize({
      window = "address:" .. keep,
      x = (node.axis == "x" and px or gk.w) - dw,
      y = (node.axis == "y" and px or gk.h) - dh,
    }))''')
    replace('''    local x, y = xy(w.at)
    local sw, sh = xy(w.size)
    local ix, iy''', '''    local x, y, sw, sh = tile_geometry(w)
    local ix, iy''')
    replace('''local function target_rect(w)
  local x, y = xy(w.at)
  local sw, sh = xy(w.size)''', '''local function target_rect(w)
  local x, y, sw, sh = tile_geometry(w)''')
    replace('''      local x, y = xy(all[i].at)
      local w, h = xy(all[i].size)''', '''      local x, y, w, h = tile_geometry(all[i])''')
    replace('''    local sw, sh = xy(o.size)
    tw, th''', '''    local _, _, sw, sh = tile_geometry(o)
    tw, th''')
    replace('''    local ox, oy = xy(o.at)
    local ow, oh = xy(o.size)
    cx, cy''', '''    local ox, oy, ow, oh = tile_geometry(o)
    cx, cy''')
    replace('''        local ox, oy = xy(o.at)
        local ow, oh = xy(o.size)''', '''        local ox, oy, ow, oh = tile_geometry(o)''')
    # Chill decisions use chill_blocked: native cards chill whole, hy3 and
    # fullscreen cards stay out. Handing an app over still requires a
    # workspace Hyprflip itself protects (a picker reservation or a card).
    replace('''  if not plugin or not plugin.protects_workspace then return false end
  local ok, protected = pcall(plugin.protects_workspace, ws.id)
  return ok and protected == true
end
''', '''  local check = plugin and (plugin.chill_blocked or plugin.protects_workspace)
  if not check then return false end
  local ok, protected = pcall(check, ws.id)
  return ok and protected == true
end

local function card_protected(ws)
  if not ws or not ws.id then return false end
  if (card_holds[ws.id] or 0) > os.time() then return true end
  local plugin = hl.plugin and hl.plugin.hyprflip
  if not plugin or not plugin.protects_workspace then return false end
  local ok, protected = pcall(plugin.protects_workspace, ws.id)
  return ok and protected == true
end
''')
    replace('''  if not w or not w.mapped or not card_workspace(w.workspace) then return false end''',
            '''  if not w or not w.mapped or not card_protected(w.workspace) then return false end''')
    # Native cards now chill; only hy3 and fullscreen cards remain protected.
    replace('''    notify("This workspace has a Hyprflip card. Ungroup the card before enabling Chill mode.")''',
            '''    notify("This workspace's Hyprflip card can't chill right now. Leave fullscreen, or ungroup an hy3 card.")''')
    return state['source']


def protection(source):
    state, replace = replacer(source)

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
    return state['source']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(prepare(args.source.read_text()))
