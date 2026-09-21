# Design

Hyprflip treats two application windows as two faces of one object. The applications keep their own contents and state; the visible face is the native group member that receives input.

## Native grouping

Hyprland owns the group and its layout target. Hyprflip stores weak references to exactly two members, locks that group against ordinary automatic insertion, and relinquishes ownership if external commands change its membership. Moving, resizing and fullscreen use native behavior. Unload settles the turn and leaves an accessible ordinary group.

The optional [container experiment](CONTAINERS.md) uses a separately built hy3
provider instead. Hy3 owns a two-tab group with one or two leaf windows per tab.
The controller consumes a bounded face snapshot, selects the visible face, and
attaches the same temporary transformers to its members with a shared pivot.
There is one animation controller and no second layout tree. Native pairs keep
their existing backend and recovery behavior.

## Rendering

A temporary `IWindowTransformer` projects the visible member's main pass. The outgoing face rotates toward its edge; before gathering the midpoint frame, the controller selects the incoming native member. The incoming face then rotates into view with readable text. A shared pose keeps the color and blur-matte passes consistent.

The animation samples time on the pair's output render cycle. A 250 ms timer is only a watchdog for an output that stops rendering. The output is retained weakly from `preChecks`: Hyprland clears its renderer's monitor reference before `RENDER_POST`, where the next frame must be requested.

The symmetric quintic angle curve meets rest with zero velocity and acceleration. Another flip retargets the timeline's velocity with a short exponential response, preserving the visible angle and angular velocity. The response is integrated analytically, splitting at the turnaround before clamping the card to its bounds, so dropped frames do not change the trajectory. There is one destination and no queue. Uninterrupted turns keep the configured duration.

The shader keeps projected corners inside the normal window bounds. Output mapping accounts for monitor rotation and fractional scale. Four spatial samples reduce minification shimmer, converging on the original sample positions as the face returns flat. There are no CPU pixel copies, retained screenshot snapshots or client resizes in the animation path.

A restrained directional light field follows the angle in shared card coordinates,
so every pane on a face receives consistent shading. It modifies RGB only, remains
within premultiplied-alpha bounds, and becomes exactly neutral at rest. The lighting
adds no texture samples or offscreen passes and does not change the blur matte.

Input, popups and geometry changes can settle or bypass the turn so native interaction remains coherent. Application popups are separate passes and are not projected. Hyprglass's independent background is temporarily opted out during a turn using its public tag, then restored.

## Prior art

- [Compiz Group and Tab Windows](https://github.com/compiz-reloaded/compiz-plugins-extra/tree/master/src/group) grouped application windows and used a rotating tab transition.
- [Sun Project Looking Glass](https://www.freedesktop.org/software/XDevConf/LG-Xdevconf.pdf) explored ordinary application windows as objects in a 3D desktop, including useful reverse sides.
- Apple Dashboard widgets made the front/back flip a familiar interaction for revealing settings.

These are interaction precedents. Hyprflip's implementation uses Hyprland's native groups and framebuffer-transformer API.
