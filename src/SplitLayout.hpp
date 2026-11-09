#pragma once
#include <algorithm>
#include <cmath>
#include <optional>
#include <vector>

namespace Hyprflip {
struct ExtentRange {
    double minimum;
    double maximum;
};

// Keep faces balanced when possible, but give each face the room its apps
// require. Whole-pixel boundaries avoid rounding a pane below its minimum.
inline std::optional<double> balancedSplit(double available, ExtentRange first, ExtentRange second) {
    const double lower = std::ceil(std::max(first.minimum, available - second.maximum));
    const double upper = std::floor(std::min(first.maximum, available - second.minimum));
    if (!std::isfinite(available) || available <= 0 || lower > upper)
        return {};
    return std::clamp(std::round(available / 2), lower, upper);
}
// Three or more faces side by side: equal shares, each clamped to its range,
// with what one face cannot take shared among the others. When the ranges
// cannot be met the shares still add up to the room there is; fits() refuses.
inline std::vector<double> sharedSplit(double available, const std::vector<ExtentRange> &ranges) {
    const size_t n = ranges.size();
    std::vector<double> extents(n, 0);
    std::vector<bool> fixed(n, false);
    if (!n)
        return extents;
    double room = std::max(0., available);
    for (size_t pass = 0; pass < n; ++pass) {
        size_t open = 0;
        for (size_t i = 0; i < n; ++i)
            open += !fixed[i];
        if (!open)
            break;
        const double equal = room / open;
        bool changed = false;
        for (size_t i = 0; i < n; ++i) {
            if (fixed[i])
                continue;
            const double clamped = std::clamp(equal, ranges[i].minimum, std::max(ranges[i].minimum, ranges[i].maximum));
            if (clamped != equal) {
                extents[i] = clamped;
                fixed[i] = true;
                room -= clamped;
                changed = true;
            }
        }
        if (!changed) {
            for (size_t i = 0; i < n; ++i)
                if (!fixed[i])
                    extents[i] = equal;
            break;
        }
    }
    // Whole pixels, with the last face taking the remainder.
    double used = 0;
    for (size_t i = 0; i + 1 < n; ++i) {
        extents[i] = std::round(extents[i]);
        used += extents[i];
    }
    extents[n - 1] = std::max(1., std::max(0., available) - used);
    return extents;
}
} // namespace Hyprflip
