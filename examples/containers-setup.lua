-- Share owned shortcut handles with OmaCards when guided setup is installed.
local ok_shortcuts, shortcuts = pcall(require, "hypr.hyprflip-shortcuts")
if not ok_shortcuts then shortcuts = hl end

-- Optional guided creation and editing, after the other Hyprflip bindings.
-- Installed by scripts/install-setup.py.
require("hypr.hyprflip-preferences")

local function shell_quote(value)
    return "'" .. value:gsub("'", "'\\''") .. "'"
end

shortcuts.unbind("SUPER + CTRL + ALT + O")
shortcuts.bind("SUPER + CTRL + ALT + O", function()
    local plugin = hl.plugin.hyprflip
    if not plugin or not plugin.unfold then return end
    if plugin.in_container and plugin.in_container() then
        plugin.unfold()
        return
    end
    local window = hl.get_active_window()
    if not window then
        hl.dispatch(hl.dsp.exec_cmd("notify-send --app-name=Hyprflip Hyprflip " ..
            shell_quote("Focus the window you want on the front, then use Create card again.")))
        return
    end
    local helper = os.getenv("HOME") .. "/.local/lib/hyprflip/setup.py"
    hl.dispatch(hl.dsp.exec_cmd("python3 " .. shell_quote(helper) .. " --front " .. shell_quote(tostring(window.address))))
end, { description = "Hyprflip: unfold, fold or create a card" })

shortcuts.unbind("SUPER + CTRL + ALT + C")
shortcuts.bind("SUPER + CTRL + ALT + C", function()
    local helper = os.getenv("HOME") .. "/.local/lib/hyprflip/setup.py"
    hl.dispatch(hl.dsp.exec_cmd("python3 " .. shell_quote(helper) .. " --cards"))
end, { description = "Hyprflip: edit card" })

shortcuts.unbind("SUPER + CTRL + ALT + L")
shortcuts.bind("SUPER + CTRL + ALT + L", function()
    local helper = os.getenv("HOME") .. "/.local/lib/hyprflip/setup.py"
    hl.dispatch(hl.dsp.exec_cmd("python3 " .. shell_quote(helper) .. " --launch"))
end, { description = "Hyprflip: open saved card" })

if hl.plugin.hyprflip and hl.plugin.hyprflip.peek then
    shortcuts.unbind("SUPER + CTRL + ALT + SPACE")
    shortcuts.bind("SUPER + CTRL + ALT + SPACE", function()
        local plugin = hl.plugin.hyprflip
        if plugin and plugin.peek then plugin.peek() end
    end, { description = "Hyprflip: hold to peek at the other side" })
    -- Hyprflip observes the triggering key’s physical release, including when the
    -- modifiers are released first. Clicking or typing keeps the visible side.
end
