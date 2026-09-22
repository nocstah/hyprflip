# Find an app in your cards

Press **Super+Ctrl+Alt+K**, type an app name or part of its title, then press Enter.
The list includes both faces of open cards on normal workspaces. Each result
shows its workspace, Front/Back, and Hidden/Visible. Current-workspace apps come
first. Escape leaves the desktop as it was.

Selecting Telegram on the back of a communications card reveals that face and
focuses Telegram, even if WhatsApp was previously the active pane. Selecting an
app in another workspace takes you to it. Membership, layout, floating mode and
workspace assignments stay intact. An unfolded card stays unfolded. The finder
also works with native two-window pairs.

**K finds a running app. L opens a saved arrangement**, launching missing apps
when needed. The finder never launches apps. If an app closes, changes identity,
or moves while the menu is open, refresh the search. Leave fullscreen before
revealing another face.

Install or update the [guided helper](INSTALL.md#add-the-guided-menus) to register
K. OmaCards' Keyboard shortcuts settings can change that binding. The same
finder runs directly with Omarchy, Fuzzel, Rofi or Wofi:

```sh
python3 ~/.local/lib/hyprflip/setup.py --find
```

Native-pair users can install the helper with `--backend-only` and bind this
command themselves; that installation mode preserves existing keyboard bindings.

## Optional mouse flip

Opt in while installing or updating the helper:

```sh
python3 scripts/install-setup.py --dry-run --mouse-flip
python3 scripts/install-setup.py --mouse-flip
```

Hold **Super+Ctrl+Alt** and click the **middle mouse button** to flip the focused
card. It fires on release and uses Hyprland's click/drag threshold. Normal
left/right drag bindings remain available. This is a shortcut for the focused
card; it does not implement a pointer-driven interactive turn.

The installer refuses a conflicting chord. It adds
`require("hypr.hyprflip-mouse")` and installs
[`examples/mouse.lua`](../examples/mouse.lua) as `~/.config/hypr/hyprflip-mouse.lua`.
For native pairs, combine `--backend-only --mouse-flip`. Later helper updates
preserve the installed module and its settings.

To disable it, remove that `require` line and reload. To choose another mouse
chord, edit the installed module, check `hyprctl -j binds` for conflicts, then
run `hyprctl reload` and `hyprctl configerrors`. Keyboard shortcut recording in
OmaCards edits keyboard bindings; mouse configuration stays in this Lua module.

Hyprland supplies the [click flag](https://wiki.hypr.land/configuring/core/binds/flags/)
and [click-versus-drag behavior](https://wiki.hypr.land/configuring/core/binds/devices/mouse/).
No compositor event hook or additional background service is needed.
