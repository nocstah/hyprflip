#pragma once
#include <array>
#include <optional>
#include <string_view>

namespace Hyprflip {
// Strip is internal: cards with three or more faces slide along a row of faces.
enum class Transition { Flip, Vertical, Slide, Fade, Dissolve, Portal, Instant, Strip };
inline constexpr std::array<std::string_view, 7> TRANSITIONS{
    "flip", "vertical", "slide", "fade", "dissolve", "portal", "instant"};
inline std::optional<Transition> transition(std::string_view value) {
    for (unsigned i = 0; i < TRANSITIONS.size(); ++i)
        if (TRANSITIONS[i] == value) return static_cast<Transition>(i);
    return std::nullopt;
}
inline std::string_view name(Transition mode) {
    return mode == Transition::Strip ? "slide" : TRANSITIONS[static_cast<unsigned>(mode)];
}
inline bool snapshots(Transition mode) { return mode >= Transition::Slide && mode <= Transition::Portal || mode == Transition::Strip; }
// Cards with more than two faces slide sideways along their row of faces
// instead of turning over.
inline Transition forFaces(Transition mode, unsigned faces) {
    return faces > 2 && (mode == Transition::Flip || mode == Transition::Vertical || mode == Transition::Slide)
               ? Transition::Strip
               : mode;
}
} // namespace Hyprflip
