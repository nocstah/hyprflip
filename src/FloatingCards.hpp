#pragma once
#include "ContainerABI.hpp"
#include <hyprland/src/desktop/DesktopTypes.hpp>
#include <hyprutils/math/Box.hpp>
#include <string>

namespace Hyprflip::FloatingCards {
inline constexpr uint64_t EPOCH = 0x484650464c4f4154ULL;
// Space between the panes of a fullscreen card, filled by a divider line.
inline constexpr double FULLSCREEN_DIVIDER = 2;
const ContainerAPI *api();
// A native outer group can occupy a dwindle tile or float as one unit. Without
// focus the card leaves the focus where it is.
uint64_t create(const ContainerSnapshot &snapshot, bool floating = true, bool focus = true);
bool canCreate(const ContainerSnapshot &snapshot);
// Names a face; an empty name gives it back its default.
bool name(uint64_t id, unsigned side, const std::string &value);
// Why the card a snapshot describes cannot be made, in words for the person:
// which app needs more room than the card or the screen has.
std::string fitProblem(const ContainerSnapshot &snapshot, bool floating);
// An app's name for messages: its class, never its title, shortened.
std::string appName(const PHLWINDOW &w);
void closing(PHLWINDOW window);
void focused(PHLWINDOW window);
void shutdown();
// Keeps fullscreen on the focused pane of a fullscreen card.
void install(void *handle);
bool focusShared();
void fullscreened(PHLWINDOW window);
bool toggle(uint64_t id);
bool setStyle(uint64_t id, double header, double gap, double divider);
// Toggles whole-card fullscreen without telling the apps they are fullscreen.
bool fullscreen(uint64_t id);
// Sets a floating card's whole frame; false for tiled or fullscreen cards.
bool place(uint64_t id, Hyprutils::Math::CBox box);
// Moves a card to a workspace as Hyprland names it: a number, name:<name>,
// special or special:<name>. Focus goes along only when it follows; a silent
// move takes the focus off the card only when it was there.
bool moveTo(uint64_t id, const std::string &destination, bool follow);
} // namespace Hyprflip::FloatingCards
