# Changelog

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
