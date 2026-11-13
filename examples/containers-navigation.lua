-- Optional Omarchy-compatible movement bindings, loaded after existing binds
-- and hyprflip-containers. A failed card move never falls back to moving one pane.

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

local function move_workspace(workspace, follow)
    return function()
        local plugin = container()
        if plugin then
            plugin.workspace(workspace, follow)
        else
            hl.dispatch(hl.dsp.window.move({ workspace = tostring(workspace), follow = follow }))
        end
    end
end

for workspace = 1, 10 do
    -- Physical number-row keys, matching Omarchy's default bindings.
    local key = "code:" .. tostring(workspace + 9)
    hl.unbind("SUPER + SHIFT + " .. key)
    hl.bind("SUPER + SHIFT + " .. key, move_workspace(workspace, true),
        { description = "Move card or window to workspace " .. workspace })
    hl.unbind("SUPER + SHIFT + ALT + " .. key)
    hl.bind("SUPER + SHIFT + ALT + " .. key, move_workspace(workspace, false),
        { description = "Move card or window silently to workspace " .. workspace })
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
        else
            hl.dispatch(hl.dsp.window.swap({ direction = direction }))
        end
    end, { description = "Move card or window " .. key:lower() })
end
