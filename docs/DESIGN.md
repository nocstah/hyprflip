---
name: Hyprflip
description: Native application windows as two faces of one card.
spacing:
  card-compact: "12px"
  drop-target-inset: "8px"
rounded:
  drop-target: "6px"
components:
  card-drop-target:
    rounded: "{rounded.drop-target}"
---

# Design

## Overview

Hyprflip treats two application windows as two faces of one object. The applications keep their own contents and state; the visible face is the native group member that receives input.

## Native grouping

Hyprland owns the group and its layout target. Hyprflip stores weak references to exactly two members, locks that group against ordinary automatic insertion, and relinquishes ownership if external commands change its membership. Moving, resizing and fullscreen use native behavior. Unload settles the turn and leaves an accessible ordinary group.

Native multi-app cards use a locked Hyprland outer group as one dwindle layout
target. The pane adapter in `FloatingCards.cpp` divides its geometry into two
faces, restores original window targets before removal/unload, and shares the
same implementation between tiled and floating cards. Guided creation uses the
`card` action; `pair` keeps the existing two-window native behavior on dwindle.

The optional [container experiment](CONTAINERS.md) uses a separately built hy3
provider instead. Hy3 owns a two-tab group with one to five leaf windows per tab.
The controller consumes a bounded face snapshot, selects the visible face, and
attaches the same temporary transformers to its members with a shared pivot.
There is one animation controller and no second layout tree. Native pairs keep
their existing backend and recovery behavior.

### Related grouping plugins

[dwindle-autogroup](https://github.com/ItsDrike/hyprland-dwindle-autogroup)
collects a dwindle branch into ordinary tabs.
[hyprdeck](https://github.com/chpock/hyprdeck) uses the native Lua grouping API
for tab-group workspaces and group-aware movement. Their documented models show
one group member at a time; neither supplies multi-pane faces. Native Hyprland
groups already provide the outer layout target needed here, so the dwindle
backend adds no dependency on either plugin. This comparison was checked on
23 September 2026; it is not a runtime compatibility claim for those plugins.

## Layout

Each multi-app face holds one to five panes in a horizontal row or vertical
column. Adding an app preserves the destination face's orientation and the
relative proportions of its existing panes.

**Desktop spacing** (`card_gap = -1`) follows directional `general:gaps_in` and
workspace overrides: left plus right between horizontal neighbors, top plus
bottom between vertical neighbors. **Compact spacing** selects
`spacing.card-compact`. A custom `card_gap` from `0` through `128` measures the
full empty gap in logical pixels between neighboring pane borders, not an
inset on each pane. The override applies within and between visible faces in
both Classic tabs and Card frame appearances. It leaves the desktop's general,
outer and neighboring tile gaps intact.

Pane geometry accounts for each window's border so floating and tiled cards
leave the same empty gap. Hy3 splits a custom gap into floor and ceiling halves
so an odd value still adds up to the requested full gap. Desktop spacing keeps
the inherited directional values instead.

Unfolding preserves each face's pane arrangement. For faces with three or more
apps, horizontal rows prefer faces above and below each other, while vertical
columns prefer faces beside each other. Mixed or smaller layouts use the backend's
available footprint. The inter-face gap follows the chosen axis; application
size limits can select the other axis, and a layout that cannot fit is refused
without changing the card.

## Components

### Card frames

Settings offers **Classic tabs** and **Card frame (Experimental)**. The choice
applies to existing cards and persists across reloads and restarts. Appearance
and spacing are independent choices.

With Card frame enabled, native pairs, floating multi-app cards and compatible
hy3 containers share one compact frame. Its outline encloses the visible apps;
a label at the top left shows Front or Back and the app count, and Flip at the
top right turns the card.
Unfolded cards show Both sides, the combined count and Fold. Reserve one header
at the card root. Narrow cards drop the count, then the label, while retaining
the action when it fits. Existing keyboard dispatchers remain available.

The desktop theme remains the visual authority. The shared outline uses
Hyprland's active/inactive border colors, derives its width from the configured
border size and follows window rounding. Controls inherit the groupbar font
family, size and text color; their opaque fill maintains at least 4.5:1 text
contrast, including hover and pressed states. The normal active-pane outline
identifies the app receiving keyboard input independently of the shared card
boundary. Do not replace it with group-wide focus alone.

Flip/Fold activates on an unmodified left-button release inside the control;
dragging cancels the click. Menus, locks, grabs and covering windows retain input
priority. Frames disappear for fullscreen and return afterward; damage is
limited to changed frame state rather than an idle redraw loop.

The optional **accent ring** (`accent_ring = true`) marks card membership in
either appearance. It is drawn 2 logical pixels outside the card's window
borders (and the frame header), follows window rounding, and takes its width
from the border size, capped at 4. The focused card's ring is fully opaque;
other cards' rings use 55% opacity so they never compete with the focus border.
`accent_color` supplies the color; the shell sets it from its theme accent.
When unset or invalid, the ring uses the first active border color.

Choosing Classic tabs (`card_frame = false`) restores native/hy3 tab bars and
the floating multi-app card's border-only appearance. An older hy3 provider
without the optional frame extension keeps its original tabs. A provider with
only the older frame extension keeps native gaps; the spacing override needs
the style extension. Unrelated groups retain their native decorations, and
unload restores usable native windows and tabs.

### Drag to add

Moving an outside application window reveals a temporary target near the top
of each eligible visible face. Its label names the destination, **Drop to add
to Front** or **Drop to add to Back**. Hover highlights that target and shades
the extra pane slot along the face's current orientation. The preview does not
change membership or layout. Only a left-button release over the explicit
target adds the app; an ordinary release elsewhere keeps normal window dragging.

Both appearances use the same gesture for floating multi-app cards and hy3
containers. Folded cards expose only the visible face; unfolded cards offer
separate Front and Back targets. Native pairs with one app per face retain
native grouping.
A face at capacity shows **Front: 5 apps already** or **Back: 5 apps already**
and offers no extra-slot preview. Failed size checks restore the existing face
orientation, proportions and membership, and leave the outside app where normal
dragging placed it.

Targets use the desktop's active/inactive border colors and groupbar typography.
The frontmatter's inset and rounding tokens define their small, transient
silhouette. Their opaque fill is chosen for at least 4.5:1 contrast with the
configured text color; preview tint comes from the destination border color.
No separate palette, permanent bar or idle redraw loop is introduced.

Escape cancels adding for the rest of that drag. Resize gestures, file/text
drags, moving an existing card, covering windows, fullscreen, locked sessions,
input grabs and pointer constraints cannot attach an app. Reload, close and
unload clear transient feedback; release revalidates the destination before
changing membership. `drag_to_add = false` disables this gesture.

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
