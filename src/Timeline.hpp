#pragma once
#include <algorithm>
#include <cmath>
#include <numbers>

namespace Hyprflip {
// A reversible position, not an animation queue. Side changes only at the edge.
class Timeline {
  public:
    explicit Timeline(double milliseconds)
        : duration(std::max(1.0, milliseconds)), response(std::min(30.0, duration * .06)) {}
    void advance(double elapsedMs) {
        double remaining = std::max(0.0, elapsedMs);
        if (rate * target() < 0) {
            // Integrate the coast and return separately. Clamping only their
            // combined displacement would depend on frame size near an end.
            const double braking = response * std::log1p(std::abs(rate));
            if (remaining >= braking) {
                step(braking);
                rate = 0;
                remaining -= braking;
            }
        }
        step(remaining);
    }
    void reverse() {
        // A resting face has no momentum. During a turn keep the current rate;
        // it approaches the new target smoothly, without a queue or a timer.
        if (position == 0 || position == 1)
            rate = 0;
        forward = !forward;
    }
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
    double target() const { return forward ? 1.0 : -1.0; }
    void step(double milliseconds) {
        // Exact integral of an exponential velocity response. Uninterrupted
        // turns retain their original duration and minimum-jerk angle curve.
        const double blend = -std::expm1(-milliseconds / response);
        position = std::clamp(position + (target() * milliseconds + (rate - target()) * response * blend) / duration,
                              0.0, 1.0);
        rate += (target() - rate) * blend;
    }
    double duration;
    double response;
    double position = 0;
    double rate = 1;
    bool forward = true;
};

// Retreat guarantees that projected corners remain within native pass bounds.
inline double projectionScale(double sine, double distance, double retreat) {
    return (distance - std::abs(sine)) * (1.0 - retreat * std::abs(sine));
}
} // namespace Hyprflip
