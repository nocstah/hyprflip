-- Optional Omarchy-compatible movement bindings, loaded after existing binds
-- and hyprflip-containers. A failed card move never falls back to moving one pane.
-- scripts/install-setup.py --navigation installs this file, and updates replace it
-- while it is unchanged: keep settings of your own in your own config.

-- The plugin when the focused window is itself in a multi-app card. With
-- nearby_card on, in_container() also answers for the card beside a window in no
-- card, so that the card keys reach it from there. These keys move the focused
-- window, so a window beside a card moves on its own: card_box() answers only for
-- a card's own windows. When that cannot be told, the card keeps the key.
local function container()
    local plugin = hl.plugin.hyprflip
    if not (plugin and plugin.in_container and plugin.in_container()) then return end
    if not plugin.card_box then return plugin end -- a core from before nearby_card
    local window = hl.get_active_window()
    local ok, x = pcall(plugin.card_box, window and window.address)
    if not ok or x then return plugin end
end

local function xy(value) -- HL.Vec2, {x=, y=} or {x, y}
    if type(value) ~= "table" then return 0, 0 end
    return value.x or value[1] or 0, value.y or value[2] or 0
end

-- Whether the nearest tile in this direction from a window in no card is a card,
-- counted as its whole box. Hyprland swaps no window with a card's locked group,
-- so such a window moves past the card instead; other neighbours swap as before.
local function card_ahead(window, direction)
    local plugin = hl.plugin.hyprflip
    if not (plugin and plugin.card_box and hl.get_windows and window.workspace) then return false end
    local function box(of)
        local ok, x, y, w, h = pcall(plugin.card_box, of.address)
        if ok and x then return x, y, w, h, true end
        local px, py = xy(of.at)
        local sw, sh = xy(of.size)
        return px, py, sw, sh, false
    end
    local x, y, w, h, own = box(window)
    if own then return false end
    local nearest, card
    for _, other in ipairs(hl.get_windows({ workspace = window.workspace.id })) do
        if other.address ~= window.address and other.visible and not other.floating then
            local ox, oy, ow, oh, is_card = box(other)
            local gap, beside
            if direction == "l" then gap, beside = x - (ox + ow), oy < y + h and y < oy + oh
            elseif direction == "r" then gap, beside = ox - (x + w), oy < y + h and y < oy + oh
            elseif direction == "u" then gap, beside = y - (oy + oh), ox < x + w and x < ox + ow
            else gap, beside = oy - (y + h), ox < x + w and x < ox + ow end
            if beside and gap > -1 and (not nearest or gap < nearest) then nearest, card = gap, is_card end
        end
    end
    return card == true
end

-- Omarchy's per-monitor workspaces (Omarchy 4.5: each monitor its own block of ten), when it has them.
local function omarchy_workspaces()
    local omarchy = rawget(_G, "o")
    local workspaces = type(omarchy) == "table" and omarchy.workspaces
    if type(workspaces) == "table" and type(workspaces.workspace_id) == "function" then return workspaces end
end

local function whole(id)
    id = tonumber(id)
    if id and id >= 1 and id % 1 == 0 then return id end
end

-- The workspace a number key means, asked when the key is pressed. A config of your
-- own can define a global function hyprflip_workspace_id(number) that returns it, for
-- a monitor layout of your own; this file can then be replaced on updates. Without
-- one, Omarchy's numbering applies where Omarchy has it, else the number itself. The
-- second value says whether your function answered.
local function workspace_id(number)
    local custom = rawget(_G, "hyprflip_workspace_id")
    if type(custom) == "function" then
        local ok, id = pcall(custom, number)
        if ok and whole(id) then return whole(id), true end
    end
    local workspaces = omarchy_workspaces()
    local monitor = workspaces and hl.get_active_monitor()
    if monitor then
        local ok, id = pcall(workspaces.workspace_id, monitor, number)
        if ok and whole(id) then return whole(id), false end
    end
    return number, false
end

local function move_workspace(number, follow)
    -- A window in no card moves with Omarchy's own key where Omarchy has one, so its
    -- workspace bookkeeping runs as well.
    local workspaces = omarchy_workspaces()
    local omarchy_move = workspaces and type(workspaces.move_window) == "function"
        and workspaces.move_window(number, follow)
    return function()
        local workspace, custom = workspace_id(number)
        local plugin = container()
        if plugin then
            plugin.workspace(workspace, follow)
        elseif type(omarchy_move) == "function" and not custom then
            omarchy_move()
        else
            hl.dispatch(hl.dsp.window.move({ workspace = tostring(workspace), follow = follow }))
        end
    end
end

for number = 1, 10 do
    -- Physical number-row keys, matching Omarchy's default bindings.
    local key = "code:" .. tostring(number + 9)
    hl.unbind("SUPER + SHIFT + " .. key)
    hl.bind("SUPER + SHIFT + " .. key, move_workspace(number, true),
        { description = "Move card or window to workspace " .. number })
    hl.unbind("SUPER + SHIFT + ALT + " .. key)
    hl.bind("SUPER + SHIFT + ALT + " .. key, move_workspace(number, false),
        { description = "Move card or window silently to workspace " .. number })
end

for key, direction in pairs({ LEFT = "l", RIGHT = "r", UP = "u", DOWN = "d" }) do
    hl.unbind("SUPER + SHIFT + " .. key)
    hl.bind("SUPER + SHIFT + " .. key, function()
        local plugin = container()
        if plugin then
            plugin.move(direction)
            return
        end
        local window, workspace = hl.get_active_window(), hl.get_active_workspace()
        local hy3 = hl.plugin.hy3
        if window and not window.floating and workspace and workspace.tiled_layout == "hy3" and hy3 then
            hl.dispatch(hy3.move_window(direction, { visible = true }))
        elseif window and not window.floating and card_ahead(window, direction) then
            hl.dispatch(hl.dsp.window.move({ direction = direction }))
        else
            hl.dispatch(hl.dsp.window.swap({ direction = direction }))
        end
    end, { description = "Move card or window " .. key:lower() })
end
