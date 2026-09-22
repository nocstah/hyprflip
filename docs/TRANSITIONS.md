# Card transitions and Chill compatibility

The focal motion is one card revealing its other face. Panes share one progress,
direction and geometry; repeated flips reverse the same transition. Choosing an
effect must not change membership, focus rules or the application's resting look.

Offer Flip, Vertical flip, Slide, Fade, Dissolve, Portal and Instant through the
existing card menu, with a reversible preview before saving a global preference.
Flip remains the default. Respect disabled Hyprland animations. Use the detected
menu and its theme: Omarchy shell by default, then Fuzzel, Rofi or Wofi when
unavailable. No additional keybinding or shader plugin is required.

Flip and Vertical flip transform live panes. The other effects compose snapshots
of both faces for the short transition, then release them. Capture once per turn,
never redraw while idle, keep premultiplied alpha, and fall back to an immediate
switch on a failed capture or changed geometry. Dissolve and Portal are optional
experimental effects with no looping flashes. Their field covers the whole card.

Use the existing reversible timeline for state and input handoff. Keep the real
active face consistent with progress and settle before accepting application
input. Verify fractional scaling, both monitor orientations, one to three panes,
rapid reversals, close/workspace/config interruptions and Hyprglass coexistence.
Measure frame intervals and CPU submission separately from screenshot capture;
these measurements do not establish GPU execution or physical scanout latency.

## Choosing a transition

Focus a container and press **Super+Ctrl+Alt+C → Transition**. Choose a mode,
then **Preview** or **Use**. Preview turns over and back; Escape keeps the
previous preference. Fold an unfolded card with O to preview motion. Instant
has no preview animation. Application input settles a running preview just as
it settles a normal turn.

The helper stores a plain mode name at `$XDG_STATE_HOME/hyprflip/transition`
(normally `~/.local/state/hyprflip/transition`). The optional setup Lua module
reads it on reload. Without the picker, set `plugin.hyprflip.transition` in
your normal Lua config. `hyprctl hyprflip preview portal` previews via IPC.
Status reports `transition`, `transition_modes` and the most recent
`capture_ms`. Flip remains the default.

Snapshot effects pause app pixels only for the turn, with no disk capture or
background recording. Their peak RGBA buffer budget is 256 MiB; larger outputs
fall back to an instant switch. Changed geometry, closed windows, popups and
unloading release snapshots and return to live windows. Keep Flip for live
video throughout the turn. All modes preserve premultiplied alpha; Hyprglass's
separate decoration is suppressed temporarily and restored when motion ends.

## Chill mode

Chill mode recognizes protected Hyprflip workspaces through a small live Lua
query. Cards and short creation/movement reservations keep their workspaces tiled.
Apply the guard in automatic and manual chilling, adoption and workspace moves.
O can offer to tile floating apps when creating a card; collect choices before
mutation and restore floating state on a failed creation. Protection must expire
or be released after cancellation, helper failure, card removal or plugin unload.

The optional adapter targets Omachill 1.2.0. Prepare a copy with:

```sh
python integrations/omachill/prepare-source.py /path/to/omachill/chillmode.lua /tmp/chillmode-with-hyprflip.lua
```

Review the diff and replace the source and installed Omachill engine using its
normal update procedure, with a backup. The script checks each expected source
context and leaves unrelated engine changes intact. Run `tests/chill_workflows.py`
against the prepared copy in a disposable compositor before installing it.

The engine queries `hl.plugin.hyprflip.protects_workspace(id)` where it would
float or reposition apps. It resolves the optional plugin on every call and
still works when Hyprflip is absent. Cards protect their normal workspaces.
Creation and imports reserve their involved workspaces for at most 60 seconds;
completion and cancellation release reservations. The updater uses bounded
120-second holds while compositor libraries are replaced. Moving a card onto
a workspace that already has chilled floaters asks you to turn off Chill there
first and leaves the card in place.

Upgrade holds are stored briefly in the compositor's private runtime directory,
keyed by its instance signature, and read once when the Chill engine loads.
This covers automatic Lua reloads during plugin loading without polling a file
on window events. Expired holds are ignored, including after a failed updater.

Rendering references: [HyprWindowShade](https://github.com/ManofJELLO/HyprWindowShade/tree/4414596c2fbb64cb5bb4aa7342900051338fed7a)
for shared progress and shader composition, and [Cybex](https://github.com/DigitalPals/omarchy-cybex/blob/e76c323ed69baf0efae12b2e7afb42635920607a/config/hyprland/looknfeel.conf)
for timing and slide references. The experimental formulas belong to Hyprflip;
the reference projects are not runtime dependencies.
