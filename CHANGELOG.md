# Changelog

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
