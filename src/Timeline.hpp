#pragma once
#include <algorithm>
#include <cmath>
#include <numbers>

namespace Hyprflip {
// A reversible position, not an animation queue. Side changes only at the edge.
class Timeline {
  public:
    explicit Timeline(double milliseconds) : duration(std::max(1.0, milliseconds)) {}
    void advance(double elapsedMs) {
        position = std::clamp(position + (forward ? 1.0 : -1.0) * std::max(0.0, elapsedMs) / duration, 0.0, 1.0);
    }
    void reverse() { forward = !forward; }
    bool finished() const { return forward ? position >= 1.0 : position <= 0.0; }
    bool secondSide() const { return position >= 0.5; }
    bool destination() const { return forward; }
    double progress() const { return position; }
    double angle() const {
        // Minimum-jerk turn: velocity AND acceleration meet the stationary
        // desktop at zero. The symmetric curve keeps the side swap at 1/2.
        const double eased = position * position * position * (position * (6.0 * position - 15.0) + 10.0);
        return std::numbers::pi * (eased - (secondSide() ? 1.0 : 0.0));
    }

  private:
    double duration;
    double position = 0;
    bool forward = true;
};

// Retreat guarantees that projected corners remain within native pass bounds.
inline double projectionScale(double sine, double distance, double retreat) {
    return (distance - std::abs(sine)) * (1.0 - retreat * std::abs(sine));
}
} // namespace Hyprflip
