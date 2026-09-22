-- Share owned shortcut handles with OmaCards when guided setup is installed.
local ok_shortcuts, shortcuts = pcall(require, "hypr.hyprflip-shortcuts")
if not ok_shortcuts then shortcuts = hl end

-- Optional container trial for Hyprland 0.56.2, after hypr.hyprflip.
-- Requires the pinned provider built by scripts/build-containers.
-- Set to nil to enable containers on all normal workspaces instead.
local trial_workspace = "8"
hl.plugin.load(os.getenv("HOME") .. "/.local/lib/hyprflip/containers/libhy3.so")

if hl.plugin.hy3 then
    if trial_workspace then
        hl.workspace_rule({ workspace = trial_workspace, layout = "hy3" })
    else
        hl.config({ general = { layout = "hy3" } })
        -- Load after saved layout overrides. Also cover existing workspaces;
        -- keep special scratchpads on the regular layout.
        hl.workspace_rule({ workspace = "s[false]", layout = "hy3" })
        hl.workspace_rule({ workspace = "s[true]", layout = "dwindle" })
    end
end

if hl.plugin.hyprflip and hl.plugin.hyprflip.attach then
    -- Resolve at press time so unloading a plugin leaves no stale function.
    local function run(action, argument)
        return function()
            local plugin = hl.plugin.hyprflip
            if plugin and plugin[action] then plugin[action](argument) end
        end
    end
    shortcuts.bind("SUPER + CTRL + ALT + H", run("attach", "horizontal"), { description = "Hyprflip: attach pane beside" })
    shortcuts.bind("SUPER + CTRL + ALT + V", run("attach", "vertical"), { description = "Hyprflip: attach pane below" })
    shortcuts.bind("SUPER + CTRL + ALT + E", run("release"), { description = "Hyprflip: release focused pane" })
    if hl.plugin.hyprflip.unfold then
        shortcuts.bind("SUPER + CTRL + ALT + O", run("unfold"), { description = "Hyprflip: unfold or fold both faces" })
    end
end
