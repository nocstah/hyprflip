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
end
