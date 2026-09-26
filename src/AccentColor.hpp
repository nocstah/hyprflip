// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <optional>
#include <string_view>

namespace Hyprflip {
// Accent ring color as #RRGGBB. Returns opaque 0xAARRGGBB; empty means unset.
inline std::optional<uint32_t> parseAccent(std::string_view value) {
    if (value.size() != 7 || value[0] != '#')
        return std::nullopt;
    uint32_t rgb = 0;
    for (const char c : value.substr(1)) {
        const int digit = c >= '0' && c <= '9' ? c - '0'
                        : c >= 'a' && c <= 'f' ? c - 'a' + 10
                        : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                               : -1;
        if (digit < 0)
            return std::nullopt;
        rgb = rgb << 4 | uint32_t(digit);
    }
    return 0xff000000u | rgb;
}
} // namespace Hyprflip
