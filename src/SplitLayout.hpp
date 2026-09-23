#pragma once
#include <algorithm>
#include <cmath>
#include <optional>

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
} // namespace Hyprflip
