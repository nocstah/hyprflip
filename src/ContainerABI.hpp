// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>

// Optional provider boundary. No Hyprland, hy3, STL containers or owning pointers
// cross it. Window addresses are identifiers, resolved against live windows.
namespace Hyprflip {
inline constexpr uint32_t CONTAINER_ABI_VERSION = 4;
inline constexpr uint32_t CONTAINER_MAX_PANES = 3;
enum class ContainerEdit : uint32_t { Horizontal, Vertical, Balance, OtherSide };
struct ContainerSnapshot {
    uint32_t active = 0;
    uint32_t unfolded = 0;
    uint32_t count[2]{};
    uintptr_t windows[2][CONTAINER_MAX_PANES]{};
    uintptr_t focused[2]{};
    double x = 0, y = 0, width = 0, height = 0;
};
struct ContainerAPI {
    uint32_t version, size;
    uint64_t epoch;
    bool (*supports)(uintptr_t window);
    uint64_t (*create)(uintptr_t front, uintptr_t back);
    bool (*inspect)(uint64_t id, ContainerSnapshot *out);
    bool (*select)(uint64_t id, uint32_t side, bool focus);
    bool (*attach)(uint64_t id, uintptr_t window, uint32_t side, bool vertical);
    bool (*release)(uint64_t id, uintptr_t window);
    bool (*dissolve)(uint64_t id);
    bool (*workspace)(uint64_t id, uint32_t destination, bool follow);
    bool (*move)(uint64_t id, uint32_t direction);
    bool (*unfold)(uint64_t id, bool enabled);
    bool (*edit)(uint64_t id, uintptr_t window, ContainerEdit operation);
    void (*animating)(uint64_t id, bool enabled);
};
using ContainerEntry = const ContainerAPI *(*)();
inline constexpr auto CONTAINER_SYMBOL = "hyprflip_hy3_bridge_v4";
} // namespace Hyprflip
