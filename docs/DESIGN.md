# Design

Hyprflip treats two application windows as two faces of one object. The applications keep their own contents and state; the visible face is the native group member that receives input.

## Native grouping

Hyprland owns the group and its layout target. Hyprflip stores weak references to exactly two members, locks that group against ordinary automatic insertion, and relinquishes ownership if external commands change its membership. Moving, resizing and fullscreen use native behavior. Unload settles the turn and leaves an accessible ordinary group.

## Rendering

A temporary `IWindowTransformer` projects the visible member's main pass. The outgoing face rotates toward its edge; before gathering the midpoint frame, the controller selects the incoming native member. The incoming face then rotates into view with readable text. A shared pose keeps the color and blur-matte passes consistent.

The animation samples time on the pair's output render cycle. A 250 ms timer is only a watchdog for an output that stops rendering. The symmetric quintic curve meets rest with zero velocity and acceleration; another flip reverses its timeline instead of adding a queued animation.

The shader keeps projected corners inside the normal window bounds. Output mapping accounts for monitor rotation and fractional scale. Four spatial samples reduce minification shimmer, converging on the original sample positions as the face returns flat. There are no CPU pixel copies, retained screenshot snapshots or client resizes in the animation path.

Input, popups and geometry changes can settle or bypass the turn so native interaction remains coherent. Application popups are separate passes and are not projected. Hyprglass's independent background is temporarily opted out during a turn using its public tag, then restored.

## Prior art

- [Compiz Group and Tab Windows](https://github.com/compiz-reloaded/compiz-plugins-extra/tree/master/src/group) grouped application windows and used a rotating tab transition.
- [Sun Project Looking Glass](https://www.freedesktop.org/software/XDevConf/LG-Xdevconf.pdf) explored ordinary application windows as objects in a 3D desktop, including useful reverse sides.
- Apple Dashboard widgets made the front/back flip a familiar interaction for revealing settings.

These are interaction precedents. Hyprflip's implementation uses Hyprland's native groups and framebuffer-transformer API.
