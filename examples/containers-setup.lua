-- Optional guided creation and editing, after the other Hyprflip bindings.
-- Installed by scripts/install-setup.py. Uses the running Omarchy 4 menu.
-- Plain preference written by the transition picker, preserved across reloads.
if hl.plugin.hyprflip and hl.plugin.hyprflip.preview then
    local root = os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")
    local file = io.open(root .. "/hyprflip/transition", "r")
    if file then
        local mode = (file:read("*l") or ""):match("^%s*(%a+)%s*$")
        file:close()
        local allowed = {flip=true,vertical=true,slide=true,fade=true,dissolve=true,portal=true,instant=true}
        if allowed[mode] then hl.config({plugin={hyprflip={transition=mode}}}) end
    end
end

local function shell_quote(value)
    return "'" .. value:gsub("'", "'\\''") .. "'"
end

hl.unbind("SUPER + CTRL + ALT + O")
hl.bind("SUPER + CTRL + ALT + O", function()
    local plugin = hl.plugin.hyprflip
    if not plugin or not plugin.unfold then return end
    if plugin.in_container and plugin.in_container() then
        plugin.unfold()
        return
    end
    local window = hl.get_active_window()
    if not window then
        hl.dispatch(hl.dsp.exec_cmd("notify-send --app-name=Hyprflip Hyprflip " ..
            shell_quote("Focus the window you want on the front, then press Super+Ctrl+Alt+O.")))
        return
    end
    local helper = os.getenv("HOME") .. "/.local/lib/hyprflip/setup.py"
    hl.dispatch(hl.dsp.exec_cmd("python3 " .. shell_quote(helper) .. " --front " .. shell_quote(tostring(window.address))))
end, { description = "Hyprflip: unfold, fold or create a card" })

hl.unbind("SUPER + CTRL + ALT + C")
hl.bind("SUPER + CTRL + ALT + C", function()
    local helper = os.getenv("HOME") .. "/.local/lib/hyprflip/setup.py"
    hl.dispatch(hl.dsp.exec_cmd("python3 " .. shell_quote(helper) .. " --cards"))
end, { description = "Hyprflip: edit card" })

if hl.plugin.hyprflip and hl.plugin.hyprflip.peek then
    hl.unbind("SUPER + CTRL + ALT + SPACE")
    hl.bind("SUPER + CTRL + ALT + SPACE", function()
        local plugin = hl.plugin.hyprflip
        if plugin and plugin.peek then plugin.peek() end
    end, { description = "Hyprflip: hold to peek at the other side" })
    -- Hyprflip observes the physical Space release, including when the
    -- modifiers are released first. Clicking or typing keeps the visible side.
end
