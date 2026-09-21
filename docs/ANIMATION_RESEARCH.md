# Animation direction: HyprWindowShade and Cybex

Research date: 2026-09-21. The first implementation follows this proposal in
Hyprflip's existing renderer. Neither reference project is a runtime dependency.

**Recommendation:** refine the existing Hyprflip turn with a small amount of
depth shading and better interruption behavior. Use HyprWindowShade as a rendering
reference and Cybex as a motion reference. Keep a single animation owner per card.

## What the projects offer

| Project | Relevant implementation | Fit for Hyprflip |
| --- | --- | --- |
| [HyprWindowShade](https://github.com/ManofJELLO/HyprWindowShade/tree/4414596c2fbb64cb5bb4aa7342900051338fed7a) | Per-surface fragment shaders, event-driven effects, motion sampling, shader composition | Useful techniques for effects and compositor compatibility. Direct flip synchronization would need a new interface. |
| [Cybex look'n'feel](https://github.com/DigitalPals/omarchy-cybex/blob/e76c323ed69baf0efae12b2e7afb42635920607a/config/hyprland/looknfeel.conf) | Hyprland animation configuration: easing curves, slides, fades and border animation | Most relevant to layout movement and unfold/fold. It does not implement a card turn. |

The inspected revisions are HyprWindowShade `4414596` (2026-09-18) and Cybex
`e76c323` (2025-12-16). Source files were read at those revisions through GitHub.

### HyprWindowShade

The project supplies elapsed-time and progress uniforms, distinguishes raw
progress from eased motion, and supports effects during move/resize plus a
bounded settling period. Its motion record is shared across a window's surfaces
and sampled once per render frame. This is useful for keeping effects coherent.
[Motion state and uniforms](https://github.com/ManofJELLO/HyprWindowShade/blob/4414596c2fbb64cb5bb4aa7342900051338fed7a/Globals.hpp#L251-L433).

Its current public actions set or toggle shaders and configure layer open/close
effects. There is no public action to supply another plugin's reversible progress
or to animate a whole Hyprflip card. Open/close and focus effects listen to actual
window events. A flip keeps applications open; treating its midpoint focus change
as an animation trigger would start a separate effect halfway through the turn.
That conclusion follows from its event listeners and exposed functions.
[Event handling and API](https://github.com/ManofJELLO/HyprWindowShade/blob/4414596c2fbb64cb5bb4aa7342900051338fed7a/main.cpp#L346-L548).

The renderer runs shader stages into intermediate textures and normally hands the
result back to Hyprland's own drawing program. Its intermediate path currently
declines rotated source buffers and rotated monitors, falling back to the top
shader. The fallback has fewer native effects. This matters for the user's
portrait display: successful compilation would not establish equivalent output
on both monitors. The implementation also adds framebuffer work for each shaded
surface, so shader stacking needs measurement.
[Composition and rotation handling](https://github.com/ManofJELLO/HyprWindowShade/blob/4414596c2fbb64cb5bb4aa7342900051338fed7a/Hooks.cpp#L988-L1110).

The reusable lesson is to share motion state, finish effects at the application's
ordinary appearance, preserve premultiplied alpha, cache shader resources, and
schedule repainting only while an effect is active. Its GLSL interface targets
ES 3.20; Hyprflip currently uses ES 3.00 and different texture coordinates.
Selected shader formulas can be adapted, but arbitrary files are not drop-in
replacements. HyprWindowShade is MIT licensed; any copied implementation should
retain the relevant attribution.
[Shader contract](https://github.com/ManofJELLO/HyprWindowShade/tree/4414596c2fbb64cb5bb4aa7342900051338fed7a#shader-uniforms),
[license](https://github.com/ManofJELLO/HyprWindowShade/blob/4414596c2fbb64cb5bb4aa7342900051338fed7a/LICENSE).

### Cybex

Its file assigns a 400 ms overshoot curve to window movement, a 500 ms ease-out
slide to workspaces, and slide/fade effects to layers. It also enables a looping
border-angle animation and changes rounding and a dwindle setting. It is a global
desktop preset using the older `.conf` syntax.
[Exact preset](https://github.com/DigitalPals/omarchy-cybex/blob/e76c323ed69baf0efae12b2e7afb42635920607a/config/hyprland/looknfeel.conf).
Hyprland documents animation speed in units of 100 ms, and warns that looping
border-angle animation requires continual rendering.
[Hyprland animation documentation](https://wiki.hypr.land/configuring/core/animations/).

The installed Omarchy defaults already define the same `easeOutQuint`,
`easeInOutCubic`, `linear`, `almostLinear` and `quick` curves. Cybex's distinctive
choices are the overshoot, slides and their assignments. Its preset cannot alter
Hyprflip's custom angle calculation. It can influence unfold/fold because those
operations resize real windows through hy3 and Hyprland.

For Hyprflip, prefer a restrained deceleration for layout transitions. A rebound
in a pane containing small text can make the interface feel less settled. Any
optional preset should be written in Lua and narrowly scoped; the Cybex installer
and unrelated desktop settings are unnecessary for this work.

## Baseline examined

- [Timeline.hpp](../src/Timeline.hpp) uses a symmetric quintic easing curve with
  zero velocity and acceleration at the resting endpoints. The default duration
  is 420 ms. Changing to an arbitrary bezier is not automatically an improvement.
- [Controller.cpp](../src/Controller.cpp) samples progress in the output render
  cycle, changes the real active face at the midpoint, and shares one pose across
  all panes. The timer is a watchdog, not the animation clock.
- [FlipTransformer.cpp](../src/FlipTransformer.cpp) already provides perspective,
  retreat, edge coverage and four subpixel texture samples. It accounts for output
  transforms. The card has geometry but no authored lighting cue.
- A repeated flip reverses the timeline immediately. Position remains continuous,
  but velocity changes sign immediately. That is a concrete candidate for improving
  interruption feel; it is not proof of a frame-pacing fault during ordinary flips.
- Each visible pane uses a window transformer and a monitor-sized framebuffer
  pass. Adding another plugin's stages could increase GPU work. Profile before
  adding passes or attempting framebuffer restructuring.

## Proposed first implementation

The focal moment is one solid card turning to reveal its other face. The back's
two apps should move and catch light together. Supporting layout transitions
should preserve location and focus while keeping text readable.

1. **Establish a baseline.** Capture normal turns and rapid reversals at the
   current 420 ms on landscape and portrait outputs. Compare one-pane and two-pane
   faces. Record frame intervals, first-use shader compilation and midpoint focus
   handoff. Distinguish missed frames from an unconvincing motion curve.
2. **Add one depth cue in the existing shader.** Prototype a faint directional
   light gradient that follows the card's angle, using coordinates relative to
   the shared card box. Keep alpha and geometry unchanged. The effect must become
   exactly neutral at both resting positions, so removing the transformer cannot
   cause a brightness flash. Compare roughly 360–420 ms; these are trial values.
   Avoid a separate blur or shadow pass in this iteration.
3. **Improve reversals if the baseline confirms the issue.** Retarget the turn
   from its current angle and angular velocity instead of flipping velocity's
   sign. Keep one target and no queue. If progress semantics change, derive face
   selection from the actual angle: the existing time midpoint assumes a symmetric
   curve. An overshooting or asymmetric curve cannot simply replace that formula.
4. **Check unfold/fold in the same session.** Keep the front in place as the other
   face appears beside it. Start with the user's existing native layout animation;
   only introduce card-specific timing if an observed discontinuity requires it.
   Avoid applying global `windowsMove` overrides just to improve Hyprflip.

The first rendering prototype belongs in `FlipTransformer.cpp` and its shared
`Pose`. Reversal work belongs in `Timeline.hpp` and `Controller.cpp`. The card model
and core/provider ABI need no new feature for these changes.

A shared projected light field does not require combining panes into one texture.
Effects spanning empty gaps, one outer shadow, or transitions blending both faces'
pixels would require additional composition work. Defer those until a visual
comparison demonstrates a useful improvement.

## Optional integration later

If running HyprWindowShade alongside Hyprflip is desirable, first test its ordinary
shaders with the flip transformer: order of application, borders, blur, focus
effects, alpha and portrait behavior. That compatibility check is separate from
using it to drive the turn.

True delegated animation would need an explicit interface accepting card identity,
members, shared geometry, actual progress/direction, reversal and cancellation.
It would also need a defined render order and fallback when either plugin unloads.
Polling IPC or starting two independent timed shaders would not maintain those
invariants. This dependency and coordination cost is unnecessary for the first
polish pass.

## Acceptance criteria

- Normal and reversed turns keep the correct face focused, with no queued flips.
- Both apps on a face share the same visual field, including uneven splits.
- No first/last-frame brightness jump, midpoint flash, or new edge shimmer.
- Portrait rotation, fractional scaling, transparent clients and Hyprglass retain
  their current behavior; no claim of compatibility based on compilation alone.
- No additional offscreen pass or idle redraw for the first lighting prototype.
- Frame timing shows no regression against the baseline on the target displays.
- Disabling animations still switches immediately and leaves focus correct.

## First implementation

The first pass adds one directional light field to the existing shader and a
short exponential response when reversing. It keeps the 420 ms default and the
existing angle curve for ordinary turns. Analytical integration preserves the
trajectory across varying frame intervals, including a coast that reaches an
endpoint before returning. Container geometry, the provider ABI and desktop
animation settings remain unchanged.

The render probe also exposed a missed redraw request: `RENDER_POST` runs after
`endRender()`, when the renderer's monitor reference is already cleared. The
controller now retains the frame's monitor weakly from `preChecks` and uses it
when requesting the next frame. The probe tracks the same event context.
[Hyprland render ordering](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/render/Renderer.cpp#L2039-L2260).

Measurements and completed checks are recorded in [TESTING.md](../TESTING.md).
