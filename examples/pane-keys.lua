-- Pane shortcuts plus the plain O unfold, for tests and setups without the
-- guided setup module (which binds H, V and E itself and owns O).
local ok_shortcuts, shortcuts = pcall(require, "hypr.hyprflip-shortcuts")
if not ok_shortcuts then shortcuts = hl end

if hl.plugin.hyprflip and hl.plugin.hyprflip.attach then
    -- Resolve at press time so unloading the plugin leaves no stale function.
    local function run(action, argument)
        return function()
            local plugin = hl.plugin.hyprflip
            if plugin and plugin[action] then plugin[action](argument) end
        end
    end
    shortcuts.bind("SUPER + CTRL + ALT + H", run("attach", "horizontal"), { description = "Hyprflip: attach pane beside" })
    shortcuts.bind("SUPER + CTRL + ALT + V", run("attach", "vertical"), { description = "Hyprflip: attach pane below" })
    shortcuts.bind("SUPER + CTRL + ALT + E", run("release"), { description = "Hyprflip: release focused pane" })
    shortcuts.bind("SUPER + CTRL + ALT + N", run("attach", "face"), { description = "Hyprflip: attach app as a new face" })
    if hl.plugin.hyprflip.unfold then
        shortcuts.bind("SUPER + CTRL + ALT + O", run("unfold"), { description = "Hyprflip: unfold or fold both faces" })
    end
end
