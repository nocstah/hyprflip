#pragma once
#include <array>
#include <optional>
#include <string_view>

namespace Hyprflip {
enum class Transition { Flip, Vertical, Slide, Fade, Dissolve, Portal, Instant };
inline constexpr std::array<std::string_view, 7> TRANSITIONS{
    "flip", "vertical", "slide", "fade", "dissolve", "portal", "instant"};
inline std::optional<Transition> transition(std::string_view value) {
    for (unsigned i = 0; i < TRANSITIONS.size(); ++i)
        if (TRANSITIONS[i] == value) return static_cast<Transition>(i);
    return std::nullopt;
}
inline std::string_view name(Transition mode) { return TRANSITIONS[static_cast<unsigned>(mode)]; }
inline bool snapshots(Transition mode) { return mode >= Transition::Slide && mode <= Transition::Portal; }
} // namespace Hyprflip
