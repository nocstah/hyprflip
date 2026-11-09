# Workflow roadmap

Keep the model small: two faces, at most five panes per face, one split per face.
An addition should remove a recurring workflow interruption without introducing
another kind of group or requiring users to manage a layout tree.

## Current milestone

- Native multi-app cards work directly on dwindle with the core and guided
  helper; the core's own card engine builds them, tiled or floating. A separate
  `card` action enables editable cards while M/P keeps two-window pairing.
- Normal workspace shortcuts move the entire card. Silent moves keep the user
  on the source workspace; an unsupported destination leaves the card intact.
- Directional movement reorders tiled cards. Tiled resize and close address the
  focused application; floating move/resize adjusts the whole card's frame.
  Release explicitly removes a pane.
- Temporary unfold shows both faces in the card's footprint. Fold restores the
  two-sided view onto the face containing the focused application. Inner splits
  retain their proportions. Applications remain live and usable throughout.
- The supplied installer keeps open dwindle and floating cards across a core
  update, rebuilding them with their apps, sides, proportions and focus, and
  rolls back a failed load.
- Optional guided setup makes O create a card when the focused window
  has none. Choose one to five back apps in the native menu; cancellation leaves
  the windows unchanged. Creation finishes folded onto the front. Existing cards
  keep immediate unfold/fold behavior.
- Flips use a shared depth light across all panes and smoothly brake when
  reversed. The core requests subsequent render frames using the monitor from
  the frame event. Ordinary turns retain the 420 ms default; no shader plugin
  or global animation preset is required.
- Edit card uses the same detected picker to add an app to the focused side or
  release any app. Local choices precede workspace submenus; choosing a remote
  app moves it here, with workspace recovery after a refused attachment. C opens
  editing, while O keeps unfold/fold. A full
  side explains its five-app limit; removing a side's only app is explicitly
  labeled Ungroup card.
- Each side supports up to five apps in one row or column. A third app keeps the
  split direction and relative sizes already chosen. `attach horizontal` and
  `attach vertical` establish the first split; no nested layout editor or
  additional shortcuts are introduced. Updates keep cards with up to ten apps.
  Unfold keeps rows of three or more apps above one another and columns beside one another,
  trying the alternate arrangement when application minimums need it.
- The transition picker offers Flip, Vertical Flip, Slide, Fade, Instant and
  experimental Dissolve and Portal, with reversible previews. Chill integration
  protects card arrangements and hands off selected floating apps with rollback.
- [Saved cards](SAVED_CARDS.md) remember a named two-face arrangement, pane
  proportions and focus. Open reuses open apps and launches missing ones through
  installed desktop entries. Selecting a saved card opens it directly; an
  optional app/launcher review lives under Manage. Cancellation and
  timeouts leave apps open. An already open card is focused without duplication.
  Manual restore remains available for choosing replacements.
- Super+Ctrl+Alt+L opens the searchable card launcher, displaying the workspace
  of running cards. C → Manage card updates the saved layout without retyping
  its name; Rename and Duplicate change saved definitions atomically.
- Beside, Stacked and Equal sizes, plus moving a pane to the other face, keep
  both faces populated with five apps maximum on each face. Refused changes
  restore the original arrangement in place.
- C → Reopen missing apps fills a partially intact saved card in place. It
  preserves the current face, remembered focus, unfolded state and surviving
  proportions, asks when several saved setups match, and restores saved pane
  positions through a guarded face arrangement operation. It shares the
  existing launcher, cancellation and workspace-protection flow.
- C → Layout offers a direct two-app swap and directional three-app reordering.
  Pane proportions remain attached to their slots; keyboard focus follows the
  same app. Super+J keeps its existing split-direction toggle.
- C → Replace exchanges any pane with an open app, including an unfocused pane,
  a full side or a side's only app. The old app remains open. The two apps
  trade places without dissolving the card; size limits are checked on both
  apps, and the card's identity, focus and folded/unfolded state are kept.
  Remote/floating choices reuse the guarded workspace handoff and rollback.
- Hold Super+Ctrl+Alt+Space to peek. Release returns smoothly; input, focus,
  popups, workspace changes and lifecycle interruptions cancel the return.
- Floating multi-app cards use a native outer group and two sets of live panes.
  They move and resize as one unit, support the same edits and transitions, and
  release ordinary windows when dissolved or unloaded.
- Saved definitions can choose a numbered workspace. Opening launches missing
  apps there or moves the already open card, and retains the saved floating mode.
- [OmaCards](https://github.com/nocstah/omacards) exposes the library, pane editor,
  motion and keyboard settings through an Omarchy bar panel. Both interfaces use
  one workflow backend and saved library. Shortcut recording inhibits compositor
  shortcuts temporarily; saved bindings survive configuration reloads.

- Guided workflows prefer Omarchy and automatically fall back to Fuzzel, Rofi
  or Wofi. The compositor plugin itself has no Omarchy dependency.
- Find an open app on either face with Super+Ctrl+Alt+K, including cards on other
  workspaces. Optional modifier + middle-click flips the focused card.

## To do: finish removing hy3

Decided 2026-11-01: hy3 support is no longer needed. Cards run on Hyprland's
own dwindle with the core alone. The hy3 lookup in the core, the external
bridge symbol, `integrations/hy3`, `scripts/build-containers`, the container
updater and the hy3 suites are gone; `src/ContainerABI.hpp` is now an internal
boundary between the controller and `FloatingCards.cpp`. Left to strip:

- The core's provider epochs, kept as an internal check.
- OmaCards: its hy3 mentions and pin checks (`tests/pin_check.py`,
  `tests/run-native.py`).

## To do: a nested check for drags the app starts

Scripted card calls refuse while one of the card's windows is dragged or
resized, including a move the app asks for itself, such as dragging a GTK
header bar. No surface holds the pointer focus during such a move, so the
guard reads the drag's target instead. That case was measured by hand in
nested sessions: the park was refused mid-drag and went ahead after release.
No committed suite covers it yet. A suite for it needs a GTK fixture window
with a `WindowHandle` to drag it by, and real pointer input from
`tests/frame_pointer.c`, which is built from the
`wlr-virtual-pointer-unstable-v1.xml` protocol file passed with `--protocol`,
as `tests/card_interactions.py` takes it.

## Before a wider preview

- Virtual monitor hotplug and DPMS off/on are covered. Physical monitor
  reconnection, actual system suspend/resume and longer daily use still need
  desktop evidence. Keep isolated checks separate from hardware claims.
- Publish the release with recovery instructions and a short
  communications-workflow recording on dwindle.

## Earlier ideas, ordered by likely usefulness

Saved setups, missing-pane recovery, layout controls, pane order/replacement and hold-to-peek are
implemented. The next candidates are:

Drag-to-add is implemented for multi-app cards: the visible face has an
explicit temporary target, Escape cancels, and the five-app/size limits remain.
The hidden face is intentionally reached by flipping or unfolding first.

1. **Undo the last card edit.** Start with membership and layout edits while all
   affected windows are still open and unchanged. Avoid a general desktop history.
2. **Touchpad-controlled turns.** Consider after keyboard workflows are stable.
   Gestures must coexist with workspace gestures and have predictable cancel
   and completion behavior. They add input-state complexity.

## Ideas to defer

- Linked flips need a concrete use case before several cards change together.
- Arbitrary nesting, more faces, and unlimited panes obscure the two-sided
  model. Existing workspaces and ordinary tiles already cover larger arrangements.

These are proposed directions, not promises or evidence of implementation.
