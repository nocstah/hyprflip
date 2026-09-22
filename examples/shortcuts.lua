-- Owned binding registry. Plain preferences are parsed, never evaluated.
local M = { version = 1 }
local names = {
    ["turn window over"]="flip", ["unfold, fold or create a card"]="create",
    ["unfold or fold both faces"]="create", ["edit card"]="edit",
    ["open saved card"]="library", ["hold to peek at the other side"]="peek",
    ["separate windows"]="unpair", ["mark first side"]="mark",
    ["attach second side"]="pair", ["attach pane beside"]="attach_h",
    ["attach pane below"]="attach_v", ["release focused pane"]="release",
    ["cancel pairing"]="cancel",
}
local entries, preferences = {}, {}
local function chord(mask, key)
    if type(mask) ~= "number" or mask % 1 ~= 0 or mask < 1 or mask > 77
       or type(key) ~= "string" or not key:match("^[%w_]+$") or #key > 40 then return nil end
    local parts = {}
    local bits = {{64,"SUPER"},{4,"CTRL"},{8,"ALT"},{1,"SHIFT"}}
    local remaining = mask
    for _, bit in ipairs(bits) do
        if math.floor(mask / bit[1]) % 2 == 1 then
            parts[#parts+1] = bit[2]
            remaining = remaining - bit[1]
        end
    end
    if remaining ~= 0 or mask == 1 then return nil end
    parts[#parts+1] = key
    return table.concat(parts, " + ")
end
local root = os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")
local file = io.open(root .. "/hyprflip/shortcuts", "r")
if file then
    for line in file:lines() do
        local id, mask, key = line:match("^([%w_]+)\t(%d+)\t([%w_]+)$")
        if id and chord(tonumber(mask), key) then preferences[id] = chord(tonumber(mask), key) end
    end
    file:close()
end
function M.bind(default, callback, options)
    local id = names[(options.description or ""):gsub("^Hyprflip: ", "")]
    if not id then return hl.bind(default, callback, options) end
    if entries[id] then entries[id].handle:remove() end
    local value = preferences[id] or default
    local handle = hl.bind(value, callback, options)
    entries[id] = {handle=handle, callback=callback, options=options, chord=value}
    return handle
end
function M.unbind(default)
    -- The setup module replaces the basic O action. Remove only our own handle.
    for id, entry in pairs(entries) do
        if entry.chord:upper() == default:upper() then
            entry.handle:remove()
            entries[id] = nil
        end
    end
end
function M.configure(id, mask, key)
    local entry, value = entries[id], chord(mask, key)
    if not entry or not value then return false end
    entry.handle:remove()
    entry.handle = hl.bind(value, entry.callback, entry.options)
    entry.chord = value
    return entry.handle ~= nil
end
return M
