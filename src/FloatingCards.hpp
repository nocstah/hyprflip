#pragma once
#include "ContainerABI.hpp"
#include <hyprland/src/desktop/DesktopTypes.hpp>

namespace Hyprflip::FloatingCards {
inline constexpr uint64_t EPOCH = 0x484650464c4f4154ULL;
const ContainerAPI *api();
// A native outer group can occupy a dwindle tile or float as one unit.
uint64_t create(const ContainerSnapshot &snapshot, bool floating = true);
bool canCreate(const ContainerSnapshot &snapshot);
void closing(PHLWINDOW window);
void focused(PHLWINDOW window);
void shutdown();
bool toggle(uint64_t id);
bool setStyle(uint64_t id, double header, double gap);
} // namespace Hyprflip::FloatingCards
