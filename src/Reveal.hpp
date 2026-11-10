// SPDX-License-Identifier: MIT
// Windows and cards that were parked come into view the way a new window opens,
// over a still picture of what they replace.
#pragma once
#include <hyprland/src/desktop/view/Window.hpp>
#include <vector>

namespace Hyprflip::Reveal {
// One card: its windows scale about one centre, so the gap between panes shrinks with them.
// extraTop is the height of its header, or 0 for a card without one.
struct Card {
    bool whole = false;
    double extraTop = 0;
};
// A reveal with a direction slides instead of opening: what arrives moves up into place from below (Up) or down into
// place from above (Down), and the picture of what it replaces moves the same way out of it, alongside, with no fade.
enum class Slide { None, Up, Down };
// What a map does to windows that have been mapped all along: the user's windowsIn on position and size, fadeIn on the
// fade, from the style's start box to the tile. speed scales the duration (1 is exactly the user's animation).
bool reveal(const std::vector<PHLWINDOW> &windows, float speed, Card card, Slide slide = Slide::None);
// The real close animation (windowsOut, fadeOut) of a live window, drawn from a snapshot: call before it moves away.
bool leave(const std::vector<PHLWINDOW> &windows);
// A still picture of a live window, under every window, until what is revealed next has faded in over it.
bool hold(const std::vector<PHLWINDOW> &windows, Card card);
// The window came in over a picture of a card's header: its own card's frame stays where it is, solid, instead of
// animating.
bool steady(const PHLWINDOW &w);
// Runs every frame: hands finished windows back to the move animation, and keeps pictures that are fading damaged.
void frame();
// The monitor went away: its pictures go now, whether or not a frame follows.
void monitorGone(const PHLMONITOR &monitor);
// Before the plugin unloads: nothing of ours may stay in Hyprland's lists.
void shutdown();
} // namespace Hyprflip::Reveal
