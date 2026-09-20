-- Hyprland 0.56.2. Load after your other desktop configuration.
-- For a hyprpm installation, omit the load call: hyprpm loads the library.
-- Keep this declaration on every parse: it is Hyprland's desired plugin list,
-- not an immediate load operation. Guarding it would unload on the next parse.
hl.plugin.load(os.getenv("HOME") .. "/.local/lib/hyprflip/hyprflip.so")

if hl.plugin.hyprflip then
    hl.config({
        plugin = {
            hyprflip = {
                duration_ms = 420,
                enabled = true,
                notifications = true,
                perspective = 5.0,
                retreat = 0.02,
            },
        },
    })

    -- Resolve each function when pressed, so unloading the plugin does not
    -- leave a keybind holding a function pointer into an unloaded library.
    local function run(action)
        return function()
            local plugin = hl.plugin.hyprflip
            if plugin and plugin[action] then plugin[action]() end
        end
    end
    hl.bind("SUPER + CTRL + ALT + M", run("mark"), { description = "Hyprflip: mark first side" })
    hl.bind("SUPER + CTRL + ALT + P", run("pair"), { description = "Hyprflip: attach second side" })
    hl.bind("SUPER + CTRL + ALT + F", run("flip"), { description = "Hyprflip: turn window over" })
    hl.bind("SUPER + CTRL + ALT + U", run("unpair"), { description = "Hyprflip: separate windows" })
    hl.bind("SUPER + CTRL + ALT + Escape", run("cancel"), { description = "Hyprflip: cancel pairing" })
end
