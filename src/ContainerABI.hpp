// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>

// The boundary between the controller and the card engine (FloatingCards). No
// Hyprland types, STL containers or owning pointers cross it. Window addresses are identifiers, resolved against live windows.
namespace Hyprflip {
inline constexpr uint32_t CONTAINER_ABI_VERSION = 9;
// A face name, NUL-terminated; empty uses Front, Back, Face 3, Face 4.
inline constexpr uint32_t CONTAINER_NAME_SIZE = 48;
inline constexpr uint32_t CONTAINER_MAX_PANES = 5;
// A card has two faces, or up to this many; flipping turns to the next one.
inline constexpr uint32_t CONTAINER_MAX_FACES = 4;
// OtherSide moves a pane to the next face (the other one, on a two-face card).
enum class ContainerEdit : uint32_t { Horizontal, Vertical, Balance, OtherSide };
struct ContainerSnapshot {
    uint32_t active = 0;
    uint32_t unfolded = 0;
    uint32_t faces = 2;
    uint32_t count[CONTAINER_MAX_FACES]{};
    uintptr_t windows[CONTAINER_MAX_FACES][CONTAINER_MAX_PANES]{};
    uintptr_t focused[CONTAINER_MAX_FACES]{};
    uint32_t vertical[CONTAINER_MAX_FACES]{};
    double ratios[CONTAINER_MAX_FACES][CONTAINER_MAX_PANES]{};
    double x = 0, y = 0, width = 0, height = 0;
    char names[CONTAINER_MAX_FACES][CONTAINER_NAME_SIZE]{};
};
struct ContainerAPI {
    uint32_t version, size;
    uint64_t epoch;
    bool (*supports)(uintptr_t window);
    uint64_t (*create)(uintptr_t front, uintptr_t back);
    bool (*inspect)(uint64_t id, ContainerSnapshot *out);
    bool (*select)(uint64_t id, uint32_t side, bool focus);
    // side == the card's face count adds the window as a new face.
    bool (*attach)(uint64_t id, uintptr_t window, uint32_t side, bool vertical);
    bool (*release)(uint64_t id, uintptr_t window);
    bool (*dissolve)(uint64_t id);
    bool (*workspace)(uint64_t id, uint32_t destination, bool follow);
    bool (*move)(uint64_t id, uint32_t direction);
    bool (*unfold)(uint64_t id, bool enabled);
    bool (*edit)(uint64_t id, uintptr_t window, ContainerEdit operation);
    bool (*arrange)(uint64_t id, uint32_t side, bool vertical, uint32_t count,
                    const uintptr_t *windows, const double *ratios);
    bool (*replace)(uint64_t id, uintptr_t outgoing, uintptr_t incoming);
    void (*animating)(uint64_t id, bool enabled);
};
} // namespace Hyprflip
