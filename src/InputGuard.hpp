#pragma once

namespace Hyprflip {
// Input in progress when an action arrives. heldOverTarget: a button is held
// and the pointer is over one of the windows the action would move.
struct InputState {
    bool locked, grab, dnd, constrained, held, heldOverTarget;
};
// Keyboard and menu actions: anything in progress refuses (today's inputBusy).
constexpr bool interactiveBusy(const InputState &s) { return s.locked || s.grab || s.dnd || s.constrained || s.held; }
// Id-addressed silent actions move nothing under the pointer: a locked screen,
// or a button held over another window, does not stop them.
constexpr bool scriptedBusy(const InputState &s) { return s.grab || s.dnd || s.constrained || s.heldOverTarget; }
} // namespace Hyprflip
