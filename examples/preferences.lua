-- Plain preferences shared by OmaCards and the native menus.
if hl.plugin.hyprflip and hl.plugin.hyprflip.preview then
    local root = os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")
    local file = io.open(root .. "/hyprflip/transition", "r")
    if file then
        local mode = (file:read("*l") or ""):match("^%s*(%a+)%s*$")
        file:close()
        local allowed = {flip=true,vertical=true,slide=true,fade=true,dissolve=true,portal=true,instant=true}
        if allowed[mode] then hl.config({plugin={hyprflip={transition=mode}}}) end
    end
    local duration_file = io.open(root .. "/hyprflip/duration_ms", "r")
    if duration_file then
        local text = duration_file:read("*l") or ""
        duration_file:close()
        local duration = text:match("^%d+$") and tonumber(text) or nil
        if duration and duration >= 0 and duration <= 2000 then
            hl.config({plugin={hyprflip={duration_ms=duration}}})
        end
    end
    local appearance_file = io.open(root .. "/hyprflip/appearance", "r")
    if appearance_file then
        local style = appearance_file:read("*l")
        appearance_file:close()
        if style == "classic" or style == "frame" then
            -- Older cores can still load the helper's other preferences.
            pcall(function() hl.config({plugin={hyprflip={card_frame=style == "frame"}}}) end)
        end
    end
    local gap_file = io.open(root .. "/hyprflip/card_gap", "r")
    if gap_file then
        local text = gap_file:read("*l") or ""
        gap_file:close()
        local gap = text:match("^%-?%d+$") and tonumber(text) or nil
        if gap and gap >= -1 and gap <= 128 then
            pcall(function() hl.config({plugin={hyprflip={card_gap=gap}}}) end)
        end
    end
end
