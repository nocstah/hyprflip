-- Optional: Super+Ctrl+Alt+middle-click flips the focused card on release.
-- Left/right mouse movement bindings keep their normal behavior.
hl.bind("SUPER + CTRL + ALT + mouse:274", function()
    local plugin = hl.plugin.hyprflip
    if plugin and plugin.flip then plugin.flip() end
end, { click = true, description = "Hyprflip: flip focused card with mouse" })
