# Lessons from WinMux

The [WinMux 0.5.4 discussion](https://www.reddit.com/r/MacOS/comments/1wed10s/double_sided_windows_in_winmux_054/)
is useful because it raises workflow and discoverability questions alongside the
visual effect. The author describes two apps as two faces and three or more as
tabs. Comments ask about finding hidden apps and using the feature independently
of a larger window manager.

Source reviewed: [WinMux commit 470eedbf9e6a1bfe78e8cf199053df434af77c81](https://github.com/ZimengXiong/winmux/tree/470eedbf9e6a1bfe78e8cf199053df434af77c81).
No source code was copied.

## Applied to Hyprflip

- **Finding the hidden app matters.** [Find app](FIND_APPS.md) lists live panes
  with their workspace and face, then reveals the selected app. It reuses card
  state instead of introducing another launcher database or a background service.
- **Make the desktop integration optional.** The same Python workflow now runs
  through Omarchy, Fuzzel, Rofi or Wofi. OmaCards remains an optional companion.
- **Offer a deliberate mouse shortcut.** WinMux's
  [gesture handling](https://github.com/ZimengXiong/winmux/blob/470eedbf9e6a1bfe78e8cf199053df434af77c81/Sources/AppBundle/ui/tabs/DoubleSidedWindowGesture.swift)
  distinguishes an Option-click from a drag. Hyprflip uses Hyprland's existing
  click-on-release support with an optional modifier + middle-click binding.
  This keeps ordinary window movement available without another input hook.

## Motion ideas to evaluate separately

WinMux's [transition controller](https://github.com/ZimengXiong/winmux/blob/470eedbf9e6a1bfe78e8cf199053df434af77c81/Sources/AppBundle/ui/tabs/DoubleSidedWindowController.swift)
uses captured faces, a padded background capture, perspective layers with edge
antialiasing, a 480 ms eased turn, and an immediate switch when reduced motion
or capture failure prevents animation. It focuses the destination behind the
temporary overlay and removes that overlay after the turn.

That suggests checking edge shimmer, shadow/background continuity and the last
frame's handoff before adding more effects. Hyprflip already has live-surface
flips, snapshot modes, reversals and immediate fallback. Copying a macOS capture
and overlay design wholesale would introduce different lifecycle and privacy
tradeoffs. No renderer changes are included in the portability/finder work.

Keep Hyprflip's two-face, multi-app model. Automatically replacing the reverse
face with tabs when a third app is added would change the communications and
project workflows that cards already serve. A small face indicator can be
considered later if searching and explicit Front/Back labels prove insufficient.
