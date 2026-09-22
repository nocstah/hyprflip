# Changelog

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
