-- Hyprflip module search path (works with or without Omarchy).
do
    local root = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
    local pattern = root .. "/?.lua;"
    if not package.path:find(pattern, 1, true) then
        package.path = pattern .. package.path
    end
end
