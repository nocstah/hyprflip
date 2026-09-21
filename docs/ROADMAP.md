# Workflow roadmap

Keep the model small: two faces, at most three panes per face, one split per face.
An addition should remove a recurring workflow interruption without introducing
another kind of group or requiring users to manage a layout tree.

## Current milestone

- Normal workspace shortcuts move the entire card. Silent moves keep the user
  on the source workspace; an unsupported destination leaves the card intact.
- Directional movement reorders the whole card. Resize and close continue to
  address the focused application; release explicitly removes a pane.
- Temporary unfold shows both faces in the card's footprint. Fold restores the
  two-sided view onto the face containing the focused application. Inner splits
  retain their proportions. Applications remain live and usable throughout.
- An explicit experimental updater restores cards after replacing both libraries
  and rolls back a failed load. The native installer refuses active containers.
- Optional Omarchy guided setup makes O create a card when the focused window
  has none. Choose one to three back apps in the native menu; cancellation leaves
  the windows unchanged. Creation finishes folded onto the front. Existing cards
  keep immediate unfold/fold behavior.
- Flips use a shared depth light across all panes and smoothly brake when
  reversed. The core requests subsequent render frames using the monitor from
  the frame event. Ordinary turns retain the 420 ms default; no shader plugin
  or global animation preset is required.
- Edit card uses the same Omarchy picker to add an app to the focused side or
  release any app. Local choices precede workspace submenus; choosing a remote
  app moves it here, with workspace recovery after a refused attachment. C opens
  editing, while O keeps unfold/fold. A full
  side explains its three-app limit; removing a side's only app is explicitly
  labeled Ungroup card.
- Each side supports three apps in one row or column. A third app keeps the
  split direction and relative sizes already chosen. H/V establish the first
  split; no nested layout editor or additional shortcuts are introduced. The
  matching ABI 3 core/provider and updater handle cards with up to six apps.
  Unfold keeps three-app rows above one another and columns beside one another,
  trying the alternate arrangement when application minimums need it.

The user selected temporary unfold as the next feature after movement on
2026-09-20. It takes priority over saved setups and hold-to-peek.

## Before a wider container preview

- Resolve the known native-group migration and combined-plugin unload hazards,
  including a reproduction independent of Hyprglass where possible.
- Broaden monitor coverage to hotplug, and exercise application size changes,
  suspend/resume and longer daily use. Keep isolated test evidence separate from
  desktop evidence.
- Publish the matching core/provider sources together, with exact ABI pins,
  recovery instructions and a short communications-workflow recording.

## Earlier ideas, ordered by likely usefulness

1. **Saved setups.** Recreate a named arrangement, such as Gmail versus WhatsApp
   and Telegram, from windows already open. Start with explicit restore and
   handle ambiguous matches visibly. Automatic launching and complete session
   restoration are separate work.
2. **Hold to peek.** Press and hold to inspect the opposite face; release to
   return. Define what happens if the user clicks, types, changes workspace or
   receives a modal dialog before implementing it. Never undo an explicit focus
   change just because a key was released.
3. **Touchpad-controlled turns.** Consider after keyboard workflows are stable.
   Gestures must coexist with workspace gestures and have predictable cancel
   and completion behavior. They add input-state complexity.
4. **Explicit companion launching.** A saved setup may launch a missing app,
   but only with a clear match and timeout. Browser windows can share processes
   and classes; avoid attaching an unrelated window by accident.

## Ideas to defer

- Linked flips need a concrete use case before several cards change together.
- Arbitrary nesting, more faces, and unlimited panes obscure the two-sided
  model. Existing workspaces and hy3 groups already cover larger arrangements.
- Floating containers require a separate geometry and lifecycle solution; do
  not make a second compositor layout merely to extend this prototype.

These are proposed directions, not promises or evidence of implementation.
