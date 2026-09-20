#include "Timeline.hpp"
#include <cstdlib>
#include <iostream>

static void require(bool condition, const char *message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

int main() {
    using namespace Hyprflip;
    Timeline t(280);
    require(!t.finished() && !t.secondSide() && t.angle() == 0, "initial front");
    t.advance(139);
    require(!t.secondSide() && t.angle() > 1.5, "outgoing edge");
    t.advance(2);
    require(t.secondSide() && t.angle() < -1.5, "incoming edge without mirrored face");
    t.reverse();
    t.advance(2);
    require(!t.secondSide(), "reverse crosses midpoint back exactly once");
    t.advance(1000);
    require(t.finished() && t.progress() == 0, "reverse settles to original");
    t.reverse();
    t.advance(1000);
    require(t.finished() && t.secondSide() && t.angle() == 0, "stall settles cleanly");
    t.reverse();
    t.advance(-100);
    require(t.progress() == 1, "negative time cannot advance");
    // A one-millisecond step must meet rest gently at either endpoint. This
    // guards the abrupt acceleration of the previous cubic ease, not a copy
    // of the new polynomial's implementation.
    Timeline start(420), end(420);
    start.advance(1);
    end.advance(419);
    require(start.angle() < 0.000001, "departure acceleration approaches zero");
    require(std::abs(end.angle()) < 0.000001, "arrival acceleration approaches zero");
    require(std::abs(start.angle() + end.angle()) < 1e-12, "turn is symmetric");
    double previous = 0;
    Timeline smooth(420);
    for (int i = 1; i <= 420; ++i) {
        smooth.advance(1);
        const double angle = smooth.angle() + (smooth.secondSide() ? std::numbers::pi : 0.0);
        require(angle >= previous, "full physical angle is monotonic through the side change");
        previous = angle;
    }
    for (int direction : {-1, 1}) {
        for (int i = 0; i <= 1000; ++i) {
            const double a = direction * i * std::numbers::pi / 2000.0;
            const double s = std::sin(a), c = std::cos(a);
            for (double d : {2.0, 3.2, 5.0, 8.0}) {
                const double k = projectionScale(s, d, .035);
                for (double x : {-1.0, -.4, 0.0, .6, 1.0}) {
                    for (double y : {-1.0, 0.0, 1.0}) {
                        double px = c * x * k / (d + x * s), py = y * k / (d + x * s);
                        require(std::abs(px) <= 1.000001 && std::abs(py) <= 1.000001, "projection fits damage bounds");
                        if (c < .0001)
                            continue;
                        double ix = px * d / (k * c - px * s), iy = py * (d + ix * s) / k;
                        require(std::abs(ix - x) < 1e-8 && std::abs(iy - y) < 1e-8, "inverse projection round trip");
                    }
                }
            }
        }
    }
    std::cout << "Timeline, reversals, stalls and perspective bounds passed\n";
}
