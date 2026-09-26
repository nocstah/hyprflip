#include "AccentColor.hpp"
#include "SplitLayout.hpp"
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
    require(balancedSplit(840, {200, 2000}, {200, 2000}) == 420, "unfold keeps balanced faces when both fit");
    require(balancedSplit(840, {200, 2000}, {530, 2000}) == 310, "a tall back face gets enough room on a laptop");
    require(balancedSplit(1400, {860, 2000}, {450, 2000}) == 860, "a wide front face keeps its minimum width");
    require(balancedSplit(840, {200, 300}, {200, 2000}) == 300, "unfold respects a face maximum size");
    require(!balancedSplit(840, {420, 2000}, {430, 2000}), "unfold refuses when the combined minima cannot fit");
    require(!balancedSplit(840, {200, 300}, {200, 400}), "unfold refuses when both maxima are too small");
    require(balancedSplit(841, {420.2, 2000}, {419.8, 2000}) == 421, "fractional minima retain whole-pixel boundaries");
    require(parseAccent("#F78DBB") == 0xfff78dbbu && parseAccent("#00aa11") == 0xff00aa11u, "accent parses #RRGGBB");
    require(!parseAccent("") && !parseAccent("F78DBB") && !parseAccent("#F78DB") && !parseAccent("#F78DBBAA") &&
                !parseAccent("#G78DBB"),
            "accent rejects anything but #RRGGBB");
    Timeline t(280);
    require(!t.finished() && !t.secondSide() && t.angle() == 0, "initial front");
    t.advance(139);
    require(!t.secondSide() && t.angle() > 1.5, "outgoing edge");
    t.advance(2);
    require(t.secondSide() && t.angle() < -1.5, "incoming edge without mirrored face");
    t.reverse();
    t.advance(2);
    require(t.secondSide(), "reversal brakes before changing direction");
    t.advance(60);
    require(!t.secondSide(), "reverse returns across the actual edge");
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
    const auto physical = [](const Timeline &turn) {
        return turn.angle() + (turn.secondSide() ? std::numbers::pi : 0.0);
    };
    for (double elapsed : {80.0, 209.0, 211.0, 350.0}) {
        Timeline reversing(420);
        reversing.advance(elapsed);
        const auto before = physical(reversing);
        reversing.advance(.001);
        const auto atReverse = physical(reversing);
        const auto incoming = atReverse - before;
        reversing.reverse();
        require(physical(reversing) == atReverse, "retarget preserves the physical angle");
        reversing.advance(.001);
        const auto outgoing = physical(reversing) - atReverse;
        require(std::abs(outgoing - incoming) < incoming * .002, "retarget preserves angular velocity");
        reversing.advance(1000);
        require(reversing.finished() && !reversing.secondSide(), "retarget settles on the requested face");
    }
    // Dropped frames must not change the trajectory, even when the coast hits
    // an endpoint before turning back. Exercise repeated retargeting as well.
    for (double initial : {1.0, 200.0, 419.0}) {
        for (double interval : {15.0, 60.0, 200.0, 700.0}) {
            Timeline coarse(420), fine(420);
            coarse.advance(initial);
            fine.advance(initial);
            for (int retarget = 0; retarget < 5; ++retarget) {
                coarse.reverse();
                fine.reverse();
                coarse.advance(interval);
                for (int frame = 0; frame < int(interval); ++frame)
                    fine.advance(1);
                require(std::abs(physical(coarse) - physical(fine)) < 1e-10,
                        "reversals are independent of frame subdivision");
                require(coarse.progress() >= 0 && coarse.progress() <= 1, "reversal stays within the card's two faces");
            }
        }
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
    std::cout << "Face size constraints, timeline, reversals, stalls and perspective bounds passed\n";
}
