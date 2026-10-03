# Changelog

## Unreleased

- Fix a floating card turning behind another floating window. Focusing a card
  raised only the focused pane's own target, so a card could stay under other
  windows, and a flip passed behind them. Focus and face changes now raise
  every app of the card together, focused app last.
- A native card moved onto a chilled workspace joins Chill like a newly opened
  app instead of being refused, through Omachill's `chillmode.join` (1.5.0, or
  adapter v4). hy3 cards and engines without `join` keep the refusal.
- Omachill 1.4.0 includes the card integration (adapter v1–v3), so updating
  Omachill no longer drops it; `prepare-source.py` is only needed for older
  engines.
## 0.3.0-rc.3 — 2026-10-02

- Show Hyprflip's messages as desktop notifications through `notify-send`
  (mako on Omarchy), with a newer message replacing an older one, instead of
  Hyprland's notification bar. `desktop_notifications = false` restores the
  bar, which is also the fallback when `notify-send` is missing.
- Omachill adapter v3: toggling Chill on a workspace with a fullscreen native
  card leaves fullscreen and chills the card instead of refusing. An hy3 card
  keeps its fullscreen and Chill explains why. v3 upgrades v1 and v2 engines.
- Fullscreen a whole card on dwindle and floating cards. Fullscreening any
  app (or maximizing it) fills the screen with every app on the visible face,
  meeting at a thin divider in the accent color (`accent_color`, else the
  active border color) with no gaps, borders or rounding between them; the
  card frame hides until you leave. The pointer focuses whichever app it is
  over. Flip, peek, unfold and
  face layout changes keep working, and moving focus between the card's apps
  keeps the card fullscreen under every `misc:on_focus_under_fullscreen`
  setting. Leaving fullscreen restores the card's tile or floating frame.
  hy3 cards keep the previous single-app fullscreen. Status reports
  `fullscreen_focus` and `card_dividers`.
- Add, replace, release and drag apps into a fullscreen native card without
  leaving fullscreen. `hyprflip mark 0x<address>` marks an app without
  focusing it, since focusing an outside app would end fullscreen.
- `fullscreen_divider` (0–16 px, default 2; 0 lets apps touch) and
  `divider_color` (`#RRGGBB`; empty follows `accent_color`, then the active
  border) style the line between fullscreen apps.
- A `fullscreen` action (Lua `hyprflip.fullscreen()`) fills the screen with
  the whole card without telling the apps they are fullscreen, so browsers
  keep their toolbars. It follows flips and focus; the action or the normal
  fullscreen toggle leaves. Status reports each card's `fullscreen`.
- Chill mode can take a workspace that holds native dwindle cards. The card
  floats in place as one chilled window at the chilled size, both faces
  sharing that frame, and tiles back into its slot. New `chill_blocked`,
  `card_box` and `card_place` Lua functions support Omachill adapter v2
  (`integrations/omachill/prepare-source.py`, which also upgrades a v1
  engine). `protects_workspace` is unchanged, so engines with only the v1
  guard still keep card workspaces tiled. hy3 cards and fullscreen cards stay
  out of Chill.
- Helper and panel: add a `fullscreen` panel action (targeted like `floating`,
  native dwindle/floating cards only) and a `divider` action (`width` 0–16,
  optional `color` `#RRGGBB` or empty to follow the accent). Snapshots report
  `capabilities.fullscreen`/`capabilities.divider`, `fullscreen_divider`,
  `divider_color`, and per-card `fullscreen` and `native`. The divider width
  and color persist in `$XDG_STATE_HOME/hyprflip` with rollback on failure and
  are reapplied at login by `preferences.lua`.
- Guided setup binds **Super+Ctrl+Alt+Return** to fullscreen the whole card
  (on cores that support it), checks it for conflicts, and lists it in the
  shortcut editor as **Fullscreen whole card**.
- Keep editing a fullscreen native card from the helper: flip, unfold, layout,
  add, replace, remove and Find app no longer ask you to leave fullscreen when
  the only fullscreen app on the workspace belongs to that card. Added apps are
  marked by address (`hyprflip mark 0x…`) so focus never leaves the card.
  hy3 cards, unrelated fullscreen apps, ungrouping and reopening missing apps
  still require leaving fullscreen first.
- Add an optional accent ring around every card, in Classic tabs and Card
  frame appearances. `accent_ring` turns it on; `accent_color` (`#RRGGBB`) sets
  its color. The focused card's ring is fully opaque and other cards' rings are
  quieter. The helper persists both, reapplies them at login, and adds an
  `accent` panel action plus `control.py accent-color` so a shell can follow
  its theme. Status reports `card_rings` for tests.
- Recognise Chromium web apps in saved cards after the default browser
  changes. A card saved with Brave's `brave-gmail.com__-Default` now reopens
  with Helium's or Chrome's `chrome-gmail.com__-Default` instead of waiting
  for a window that never appears. The site and browser profile must still
  match.

## 0.3.0-rc.2 — 2026-09-23

- Let native dwindle and floating cards allocate unequal space to unfolded
  faces according to application minimum and maximum sizes. Keep balanced
  faces when they fit, try both directions, and retain the saved pane layouts.
  Gmail / WhatsApp + Telegram now unfolds in the existing 1440×900 laptop tile.
- Add real GTK regressions at 1440×900 and 1280×800, with Classic and Card frame
  appearance, exact fold restoration and refusal when neither direction fits.
- Validate the published installers with a fresh home, stock Omarchy 4.0.4
  configuration and real shell menus: no hy3, no shortcut conflicts, and a
  saved three-app card cold-launches correctly. This uses existing host
  packages; a fresh OS install and independent-user beta remain outstanding.
- Add a reproducible isolated installer test, beta checklist and invitation
  draft for default-dwindle users.

## 0.3.0-rc.1 — 2026-09-23

Preview release for Hyprland 0.56.2, focused on Omarchy's default dwindle layout.

- Create, edit, unfold and reopen multi-app cards directly on dwindle using
  native Hyprland groups. The core alone supplies the card backend; the hy3
  provider remains optional for hy3 workspaces. Preserve the existing M/P
  two-window pairing path and use O for editable cards.
- Add a core-only dwindle demo with `tests/nested_session.py --native-cards`.
- Check tiled app size limits after the incoming tile releases its space.
  Saved cards can now group apps whose minimum sizes fit the completed card
  but exceed the smaller tile available during construction.
- Restore saved native-card pane proportions through the card layout API;
  ordinary dwindle resizing operates on the card's outer tile.
- Support up to five apps per face with the matching ABI 7 core and hy3 provider.
  Preserve pane proportions when adding or removing apps, and unfold large
  horizontal faces above one another to retain their width.
- Add temporary Front/Back drop targets for dragging outside windows into
  containers, with slot previews, Escape cancellation and size-limit rollback.
- Offer Classic tabs or an experimental shared card frame with Flip/Fold
  controls. OmaCards saves appearance and Desktop/Compact spacing preferences;
  compact gaps leave 12 logical pixels between card apps.
- Preserve application minimum sizes during upgrades by reconstructing cards
  on a temporary workspace, then restoring their original workspace and size.
  Failed or interrupted reconstruction rolls back with recovery metadata.
- Run guided creation, editing and saved-card workflows without Omarchy. Prefer
  its responding shell; otherwise detect Fuzzel, Rofi or Wofi, with an explicit
  override and clear feedback when no picker is installed.
- Make Lua module imports work in plain Hyprland and use portable notification
  flags for saved-card launch progress and cancellation.
- Find apps across open cards with Super+Ctrl+Alt+K: show the workspace and face,
  reveal hidden panes, and focus the exact app without changing membership.
- Offer an optional Super+Ctrl+Alt+middle-click flip binding through
  `install-setup.py --mouse-flip`; existing drag bindings remain available.

## 0.2.0 — 2026-09-22

Two-face workflows and the first public [OmaCards](https://github.com/nocstah/omacards)
companion. Hyprland remains pinned to 0.56.2; the optional hy3 bridge uses ABI 6.

- Tiled or floating cards with up to three live apps on each face. Floating cards
  move and resize as one unit and retain membership through edits and transitions.
- Unfold/fold, hold to peek, seven transitions, previews and saved motion preferences.
- Add, remove, replace, reorder or transfer any pane; import apps from other workspaces.
- Save named arrangements, launch missing apps, reuse existing windows, and repair
  missing panes. Assign a destination workspace and remember floating mode.
- OmaCards adds a native Omarchy bar library, two-face editor and Settings for
  motion and keyboard shortcuts. Shortcut recording temporarily inhibits desktop
  bindings; changes persist, check conflicts and roll back on failure.
- Share one guarded workflow backend between the panel and native menus.
- Preserve cards during matching core/provider upgrades. Refuse an update while
  the desktop is locked, before touching compositor libraries or arrangements.

Build from source against the running compositor's matching headers and compiler.
See [installation and upgrade paths](docs/INSTALL.md), [tested behavior](TESTING.md),
and [compatibility limits](README.md#compatibility-and-limits).

## 0.1.1 — 2026-09-20

First public release, for Hyprland 0.56.2.

- Pair two real windows as the front and back of a rotating card.
- Reuse native groups for layout, focus, movement, resizing and fullscreen.
- Synchronize the perspective turn to the pair's output render cycle.
- Use a reversible 420 ms turn with gentle departure and landing, restrained perspective and filtered texture detail.
- Provide Lua and IPC actions, optional shortcuts, reduced motion and clean unpairing.
- Handle window closure, external group changes, input interruption and plugin unloading.
- Support tested Wayland/XWayland pairs, fractional scaling, rotated outputs and Hyprglass 1.0 coexistence.
- Preserve native pairs through installer upgrades; retain recovery metadata until restoration succeeds.
- Include a nested compositor test harness and automated core/installer checks.

Pairs are not persisted across compositor restarts. See [TESTING.md](TESTING.md) for the tested configurations and limits.
