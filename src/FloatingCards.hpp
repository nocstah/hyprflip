#pragma once
#include "ContainerABI.hpp"
#include <hyprland/src/desktop/DesktopTypes.hpp>
#include <hyprutils/math/Box.hpp>

namespace Hyprflip::FloatingCards {
inline constexpr uint64_t EPOCH = 0x484650464c4f4154ULL;
// Space between the panes of a fullscreen card, filled by a divider line.
inline constexpr double FULLSCREEN_DIVIDER = 2;
const ContainerAPI *api();
// A native outer group can occupy a dwindle tile or float as one unit.
uint64_t create(const ContainerSnapshot &snapshot, bool floating = true);
bool canCreate(const ContainerSnapshot &snapshot);
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
} // namespace Hyprflip::FloatingCards
