-- Hyprflip's nested test desktops (Aquamarine windows, app id "aquamarine")
-- open on a hidden special workspace without taking focus, and keep drawing
-- there so their screenshot and motion checks still run. Press the special
-- workspace toggle for "hftests" to watch one.
o.window("aquamarine", {
    workspace = "special:hftests silent",
    no_initial_focus = true,
    no_focus = true,
    render_unfocused = true,
    suppress_event = "fullscreen maximize activate activatefocus",
})
-- Hidden windows draw at this rate; animation captures need full speed.
hl.config({ misc = { render_unfocused_fps = 60 } })
