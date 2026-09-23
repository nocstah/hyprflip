# Container experiment

For native multi-app cards on dwindle, start with the
[dwindle installation guide](INSTALL.md#dwindle-multi-app-cards). This document
primarily describes the optional hy3 provider and its separate update path.

Status: opt-in development experiment for Hyprland 0.56.2. The native
two-window backend remains available. The regular installer does not enable this
provider or change workspace layouts.

For a first installation, follow the [installation guide](INSTALL.md#experimental-multi-app-cards),
including provider activation and optional guided menus. This document covers
container behavior, direct commands and compositor acceptance checks.

## Goal

Flip one desktop tile between two views of a task. For example, Gmail on the
front and up to five messaging applications sharing its reverse side.

Two sides, at most five panes per side, one split per face. The card's workspace
command moves its applications together. A flip restores the last focused application on
the destination face. Closing an application never closes the other applications.
Releasing a pane and disabling the effect must leave ordinary usable windows.

## Frame and spacing

With `plugin.hyprflip.card_frame = true` (the default), a shared outline and
compact Flip/Fold control replace the card's full-width hy3 tabs. The label
identifies the visible side and app count. Other hy3 tab groups keep their tabs.
Both the core and the provider must support this optional frame extension;
an older provider falls back to its original tabs.

Inner gaps inherit the workspace's tiling configuration, including directional
values. `gaps_in = 14` leaves 28 pixels of empty space between adjacent window
borders, just as it does between ordinary tiles. Floating pane geometry accounts
for each app's actual border width; it does not consume that gap with borders.
Unfolding uses the gap for the axis separating the two sides. Layout edits on a tiled
card recalculate its containing tile before arranging panes, retaining its outer
and neighboring gaps too.

OmaCards Settings can switch to **Classic tabs** and choose **Desktop spacing**
or **Compact spacing**. Compact uses 12 logical pixels between card apps; it
does not change `general:gaps_in` for ordinary tiles. Direct config supports
`card_gap = -1` (inherit) or `0`–`128` (full visible gap between borders).
Appearance and spacing chosen through OmaCards persist across reload/restart.

While moving an outside window, a **Drop to add to Front/Back** target appears
near the visible face’s top. Release over it to add the app; Escape or releasing
outside leaves ordinary movement intact. Both unfolded faces have their own
target. Full sides show the five-app limit, and application minimum sizes can
refuse a drop. Cards and apps must be on the same visible workspace. Native
one-app pairs do not expose this multi-app target. Use `drag_to_add = false`
to disable it. Both Classic tabs and Card frame support the interaction.

## Build and try in isolation

For an interactive demo with three shells already arranged into a card:

```sh
./scripts/build-containers
python -u tests/nested_session.py --directory /tmp/hf-demo --containers
```

Click inside the demo and press **F8** to flip. The front shows the other demo
shortcuts, including mark, pair, attach and release. These bindings exist only
inside the disposable compositor. Press Ctrl+C in the launcher to finish;
closing a nested output window alone can leave its compositor running without
an output. Use a fresh short `/tmp` directory for each running session.

For automated checks, start the regular fixture session instead:

```sh
./scripts/build-containers
python -u tests/nested_session.py --directory /tmp/hf-card
```

Keep that launcher running. In another terminal, run the acceptance suite:

```sh
python tests/containers.py /tmp/hf-card/session.json
```

The suite copies the libraries, loads them into the selected disposable session,
creates real terminal applications, captures the animation, and cleans up. Its
IPC guard rejects the live compositor. GPU access and an awake parent output are
required. The full build keeps Hyprland's ABI checks enabled and verifies the hy3
revision; it needs hy3's normal development dependencies too.

For a manual experiment inside that session, copy the two libraries first:

```sh
cp build/containers/provider/upstream/libhy3.so /tmp/hf-card/manual-hy3.so
cp build/containers/core/hyprflip.so /tmp/hf-card/manual-hyprflip.so
python tests/control.py /tmp/hf-card/session.json plugin load /tmp/hf-card/manual-hy3.so
python tests/control.py /tmp/hf-card/session.json plugin load /tmp/hf-card/manual-hyprflip.so
python tests/control.py /tmp/hf-card/session.json repl 'hl.config({general={layout="hy3"}})'
```

Set the layout after loading both libraries: plugin loading reloads the base
configuration. A persistent experiment must also declare its hy3 workspace
layout in that session's configuration. Do not load a stock hy3 and the
experimental hy3 simultaneously. Stop the disposable launcher with Ctrl+C.

## Dedicated workspace trial

[`examples/containers-trial.lua`](../examples/containers-trial.lua) is an optional
configuration for an explicitly enabled desktop trial. It selects hy3 only for
workspace **8** and adds **Super+Ctrl+Alt+H** (attach beside), **V** (attach below),
and **E** (release). The regular **M/P/F/U/Escape** shortcuts continue to handle
mark, pair, flip, unpair and cancel. **O** toggles temporary unfold. F6/F7/F8
belong only to the nested demo.

The example expects the updated core, the experimental provider at
`~/.local/lib/hyprflip/containers/libhy3.so`, and loading after `hypr.hyprflip`.
Check that workspace 8 is free and the new shortcuts are unused before enabling
it. The regular installer does not install the provider or load this module.

The matching `tests/trial.py` check runs in a disposable compositor. It verifies
native dwindle pairs alongside a hy3 workspace, the attach/release shortcuts,
Hyprglass during a container flip, reload and unpair. Passing these checks does
not establish day-to-day stability on the real desktop.

To expand an existing trial, set `trial_workspace = nil` in the example and load
it after any saved workspace layout rules. This selects hy3 for all normal
workspaces, including newly created ones and workspaces with earlier layout
overrides. Special scratchpads retain dwindle. The same Hyprflip shortcuts apply.

Before switching, unpair existing **tiled native pairs while their workspace
still uses dwindle**. After the switch, mark their original front and pair their
original back again; they now use containers. Existing hy3 containers can stay
in place. This ordering matters: the pinned hy3 can retain an expired native
group target when ungrouping after the layout change. Floating pairs remain
native and cannot accept additional panes.

The expansion regression adds native-pair conversion, existing-card preservation,
saved layout overrides, new workspaces, special scratchpads, whole-card moves
and reload:

```sh
python tests/trial.py /tmp/hf-test/session.json \
  --hyprglass /path/to/hyprglass.so --all-workspaces
```

When disabling several plugins, keep Hyprglass loaded until Hyprflip and hy3
have unloaded. Removing all three in one config reload exposed a teardown crash
with the installed Hyprglass 1.0 build; ordinary reloads keeping them loaded pass.

## Normal movement shortcuts

[`examples/containers-navigation.lua`](../examples/containers-navigation.lua)
optionally replaces Omarchy's existing movement bindings. Load it after the
container configuration and other keybindings. It calls `hl.unbind` before
replacing each binding:

| Shortcut | Behavior |
| --- | --- |
| Super+Shift+1…0 | Move the entire focused card to workspace 1…10 and follow it |
| Super+Shift+Alt+1…0 | Move the card there and keep focus on the source workspace |
| Super+Shift+arrows | Reorder the whole card toward a neighboring tile |

These keys previously moved or swapped the selected window. Ordinary windows
retain workspace movement and use hy3's directional movement on a hy3 layout;
other layouts retain the standard swap command. A failed card move leaves all
panes in place. A directional card move at an outer edge does nothing. Scratchpad
and drag bindings are not replaced by this module.

## Temporary unfold

**Super+Ctrl+Alt+O** shows both faces in the card's existing tile. The wider axis
is preferred, with the other axis tried if application size limits require it.
If neither arrangement fits, the card stays folded. Both faces contain live,
interactive applications; the normal Hyprland resize animation handles the
change, including reduced-motion settings.

Press **Super+Ctrl+Alt+O** again to fold onto the face containing the focused
application. Inner split proportions are retained. While unfolded,
**Super+Ctrl+Alt+F** folds onto the
opposite face; it does not run the perspective turn while both faces are visible.
Movement, release, close and config reload continue to work. Leave fullscreen
before unfolding or moving a card.

## Guided creation from O

For an enabled container trial, install the optional guided picker:

```sh
python scripts/install-setup.py --dry-run
python scripts/install-setup.py
```

This adds a small Python helper and
[`examples/containers-setup.lua`](../examples/containers-setup.lua), loaded after
the other Hyprflip bindings. It backs up affected files and installs
**Super+Ctrl+Alt+O/C/L/K/Space** for guided creation, editing, saved-card launching
finding open card apps and hold-to-peek. No compositor library is replaced or unloaded.

- On an existing card, **O** still unfolds or folds immediately.
- On an ungrouped app, **O** opens the automatically detected searchable menu. The focused
  app becomes the front. Choose an app for the back, then choose **Create card**
  or **Add [app name]** for a second app. After choosing a second app,
  choose **Create card** or add a third. When only one other window is
  available, one selection is enough.
- The selected apps group automatically, with the card folded onto the front.
  **Super+Ctrl+Alt+F** flips to the back; **Super+Ctrl+Alt+O** shows both faces
  together when you want them.
- **Escape** at any menu cancels without changing the windows, their layout or
  any pending mark. Ungrouping removes the card; the same shortcut can create it
  again through the picker.

The current workspace must use hy3. Choices include ungrouped windows
from any normal workspace; existing cards, pinned windows and scratchpads
are excluded. Local apps appear first, followed by **Add from workspace X**
entries in workspace order. Each entry opens that workspace's app list, with
**Back to all apps** to return. Selected remote apps move to the front window's
workspace after all choices are complete. App names and window
titles distinguish choices; same-named windows get separate entries. The helper
rechecks window identity, workspace and ownership before applying the selection.
Guided creation never launches or closes applications. A second pane uses the card's longer
axis; the explicit H/V commands can establish the first split in either direction.
A third app joins the existing row or column, retaining its direction and the
relative sizes of its existing panes. Creation
does not require enough space to show both faces simultaneously.

Floating apps are fitted into the card automatically after selection, with no
separate tiling confirmation. Their picker rows say **Resizes to fit card**.
Cancelling before the final selection preserves their arrangement.
Creating tiles only the selected apps; a failure restores
their previous floating positions and returns imported apps to their workspaces.
For apps managed by Omachill, install the optional
[Chill integration](TRANSITIONS.md#chill-mode) so Auto Chill respects cards.
An older core keeps the original tiled-only picker behavior.

The picker prefers the running Omarchy menu and otherwise detects Fuzzel, Rofi
with Wayland support, or Wofi. All support filtering, arrow keys, Return and
Escape. It requires Python 3, `notify-send` and GLib's `gio`/`gdbus` tools for
saved-card launching and its cancellable notification. See
[dependencies and backend overrides](INSTALL.md#add-the-guided-menus). This is guided creation;
live card identities do not survive compositor restarts. The optional
[saved-card menu](SAVED_CARDS.md) recreates named arrangements, reuses open apps
and launches missing ones, including their split directions and proportions.
**Super+Ctrl+Alt+L** opens that searchable launcher directly. Selecting a saved
card opens or switches to it; optional review is under **Manage saved cards…**.
**C → Manage card…** adds Update, Rename and Duplicate for saved arrangements.

## Edit an existing card

The same optional helper adds **Super+Ctrl+Alt+C** for **Edit card**. Focus the
app on the side you want to change, then open the menu:

- **Add an app to this side** opens the familiar app picker. Local apps appear
  first, followed by **Add from workspace X** entries. Choose an ungrouped
  app; floating apps are resized to fit automatically. A remote app moves here
  before joining the side and receives focus. The
  first split follows the available space: beside on a wide pane, below on a tall
  pane. Adding a third app keeps that row or column and its existing proportions.
- On a side with two to five apps, **Remove [app] from card** is available for each app.
  It releases the chosen app into its own tile and keeps it open. Removing the
  other app keeps focus on the app you were using. The other apps remain paired. The menu
  states that the side is full at five apps and omits Add until there is room.
- When the focused app is alone on its side, the option is **Ungroup card**.
  This explicitly dissolves the card and leaves all its apps open.
- **Layout of this side…** offers **Beside**, **Stacked** and **Equal sizes**
  when a side has multiple apps. Changing direction keeps its proportions;
  equalizing keeps its direction. The other face keeps its layout.
- The same layout menu offers **Swap app positions** for two apps, with no
  additional chooser, or **Reorder apps…** for three or more. Moves are labeled
  left/right for rows and up/down for columns. Split sizes stay with their
  positions, and focus stays on the app you were using.
- **Replace an app…** lets you replace any pane, including one that is not
  focused. A side with one app names it directly, for example **Replace Gmail…**.
  Choose an open app locally or under **Add from workspace X**. Floating apps
  are resized to fit automatically. The replacement keeps the pane's position and
  share of the side; the previous app stays open separately on the card's
  workspace. Replacing the focused app follows its replacement; replacing
  another pane retains your focus. Full five-app sides are supported.
- **Move an app to the other side…** lets you choose any pane and follows it
  onto the opposite face. It is offered when the source has at least two apps
  and the destination has room. The destination keeps its existing direction,
  or uses the card's longer axis when gaining its second app.

Layout controls require matching core/provider builds (ABI 4 or later;
reordering needs ABI 5 and replacement needs ABI 6). They edit the existing
tree in place and preserve folded/unfolded state. If an application's size
limits prevent a change, the original membership, order, proportions and focus
are restored. Custom bindings can call `hl.plugin.hyprflip.layout("horizontal")`,
`layout("vertical")`, `layout("balance")` or `other_side()`; the last function
optionally accepts a live address on the focused face. IPC equivalents are
`hyprctl hyprflip 'layout horizontal'` and `hyprctl hyprflip other_side`.

Omarchy's **Super+J** keeps toggling the focused split between beside and
stacked. App order and replacement use C; no desktop shortcuts are reassigned.
Replacement exchanges two existing hy3 leaf slots atomically. Both apps must
fit their new slots. Importing or tiling a replacement can reflow the surrounding
workspace first, just as adding an app does. The direct API expects an ungrouped,
tiled replacement already on this workspace:
`hyprctl hyprflip 'replace 0xOLD 0xNEW'` or
`hl.plugin.hyprflip.replace("0xOLD 0xNEW")`. A refused replacement keeps the
card intact and the helper returns imported/floating apps to their previous
workspace and state. Reordering and replacement do not change saved definitions;
use **Manage card… → Update saved card** to keep the new setup.

For example, open Telegram, then on your Gmail/WhatsApp card,
focus WhatsApp, press **Super+Ctrl+Alt+C**, choose **Add an app to this side**,
then choose **Telegram** locally or under **Add from workspace X**. The Gmail
face stays intact.

Editing also works while unfolded and preserves that state. **O** continues to
unfold/fold immediately; **C** opens the editor. Escape at either menu cancels
before changing focus, marks or layout. A card change, app closure, workspace
change or changed focus invalidates a pending selection. A refused attachment
keeps the existing card intact and returns imported apps to their original
workspaces when they remain available. A source layout may reflow on return.
Application size limits still apply. Enlarge the card if a third app cannot fit.
H/V choose the direction when adding a second app; a third retains it.

To update an existing guided setup installation, run
`python scripts/install-setup.py`. It checks O/C/L/Space for shortcut conflicts, backs
up the helper and Lua files, and reloads configuration. It does not replace or
unload compositor libraries.

## Updating an enabled trial

The current core and provider use bridge ABI **7**; rebuild both together.
The updater restores faces with one to five apps, including their split
proportions. An ABI 2 installation can upgrade without recreating its cards.
The regular installer refuses to replace the core while experimental cards are
active. For an already-enabled trial using the documented library paths:

```sh
./scripts/build-containers
make
python scripts/update-containers.py --dry-run
python scripts/update-containers.py
```

The updater backs up both libraries and same-session recovery metadata, settles
turns, unloads the core before the provider while leaving Hyprglass loaded,
updates both, and reconstructs the cards. It restores face membership, inner
split direction and proportion, current face, native pairs and application
focus. Multi-app provider cards are briefly rebuilt on an empty workspace on
the same monitor, so loose companion windows cannot make a partial split too
small. The complete card returns to its original workspace and its outer size
is restored where the tiling tree permits. Interrupted reconstruction returns
the apps before rollback. The surrounding tiling tree may reflow when hy3
reloads. No applications are launched or closed; configured keybindings and
layout rules are unchanged.

A failed load attempts to restore the previous libraries and cards. Backups live
under `~/.local/state/hyprflip/container-update-*`. Window addresses in the
recovery metadata are valid only in that compositor session; this is not saved
setup support. Complete any fullscreen or native-group changes before updating,
and dismiss screensavers covering a card workspace so restoration can focus its
applications. The dry run checks these conditions before any library changes.

## Interaction

On the current core, `hyprctl hyprflip card` creates a native multi-app card on
dwindle from the marked and focused windows. Its Lua equivalent is
`hl.plugin.hyprflip.card()`. Use `card` in step 2 below for dwindle; `pair`
retains the simpler two-window native group there. Both actions use the optional
provider on a hy3 workspace. The remaining card actions apply to either backend.

Use the following actions through `hyprctl hyprflip` in the experiment, or prefix
them with `python tests/control.py /tmp/hf-card/session.json` when controlling it
from the parent desktop.

1. Focus the front application and run `hyprflip mark`.
2. Focus the back application and run `hyprflip pair`.
3. Focus a third application and run `hyprflip mark`.
4. Focus the card face that should receive it and run `hyprflip attach`.
5. Run `hyprflip flip` for the everyday front/back switch.

| Action | Behavior |
| --- | --- |
| `attach` or `attach horizontal` | Add a second app beside the first, or a third in the existing row/column |
| `attach vertical` | Add a second app below the first, or a third in the existing row/column |
| `release` | Move the focused pane outside the card; dissolve if that empties a face |
| `workspace 2` | Move all card members to numbered hy3 workspace 2 and follow them |
| `workspace 2 silent` | Move the card and remain on the source workspace |
| `move left` / `right` / `up` / `down` | Reorder the entire card toward a neighbor |
| `unfold` | Toggle showing both faces together in the existing card frame |
| `floating` | Toggle the whole card between floating and tiled placement |
| `unpair` | Turn both faces into ordinary visible splits |
| `cancel` | Clear the pending mark |
| `status` | Report native `pairs` and experimental `containers` separately |

Lua exposes `hl.plugin.hyprflip.attach("horizontal")`, `release()` and
`workspace(2, follow)`, `move("left")`, `unfold()`, `floating()` and `in_container()` alongside
the existing direct action functions. `follow` defaults to true. Bindings are
installed only by the optional configuration modules. Existing mark/pair/flip shortcuts use containers when
both tiled windows belong to the experimental hy3 provider. Floating windows
form cards backed by a native group with the same two-face API.

Focus and close still act on real applications. Tiled resizing adjusts panes;
floating movement and resizing adjust the shared frame. Use the navigation module
or explicit `workspace` action to move a whole card; an unadapted window-move
command can act on the selected tiled pane. Leave fullscreen before flipping or moving a container.
New windows open outside the card. Unloading Hyprflip dissolves its containers
into visible splits; the experimental updater reconstructs them explicitly.

## Current boundaries

- Hyprland 0.56.2 and the pinned hy3 release only. Dwindle retains native pairs.
- Tiled or floating cards on one workspace; no nested flip cards.
- At most five apps per face, arranged in one row or column. No nested splits
  within a face. Hy3 supports larger trees; this is the supported Hyprflip subset.
- Unfold places rows of three or more apps above one another and columns beside
  one another. Mixed split directions use the card's proportions. Application
  size limits can select the alternate arrangement or refuse the unfold.
- Workspace moves accept positive numeric IDs. Tiled hy3 cards require hy3 at
  the destination; floating cards can move as a native group. Saved-card opening
  through the helper requires a hy3 destination. Named/special workspace moves
  are deferred. Floating cards support whole-card dragging and resizing.
- Layout navigation uses hy3's model. This does not make dwindle support nested
  containers, and does not automatically replace existing movement shortcuts.
- The hy3 tab bar is visible at rest and hidden during a turn; floating cards
  hide the native group bar. Popups do not rotate;
  unsuitable rendering conditions switch instantly.
- The compositor does not restore sessions at login or add individual-pane
  capture semantics. The optional guided helper handles saved cards and explicit
  missing-app launching separately.
- This is an optional development experiment. The native installation keeps
  its existing layout unless you explicitly enable the provider and its rules.

## Implementation sequence

1. Build a pinned hy3 revision against the installed Hyprland 0.56.2 headers and
   load it only in a disposable nested compositor. Stop extending this route if
   it needs a substantial compatibility fork.
2. Expose a small bridge to hy3's existing two-tab containers. Hy3 owns the tree,
   pane geometry, visibility and focus. Hyprflip keeps references to faces and
   temporary animation state, not another layout tree. Keep bridge code separate
   from the default native backend, with explicit compatibility checks.
3. Make a three-window container switch instantly, remember focus, and support
   release and normal cleanup. Prove lifecycle behavior before adding motion.
4. Reuse the current timeline and per-window render transformers with a shared
   container rectangle. Test clipping and both sides of the midpoint. Fall back
   to an instant switch when the surfaces or geometry are unsuitable.
5. Provide repeatable setup, commands, documentation and nested regression tests.

## Usability boundaries

- Flip is the everyday operation. Setup actions explicitly add or release a
  window; unrelated new windows are not silently adopted.
- Input settles a turn before normal delivery. External focus never gets pulled
  back. Urgency alone does not flip a container.
- Ordinary focus and close act on real applications. Do not leave keyboard focus
  on a structural group as a side effect of a flip.
- Preserve the external footprint during a flip and the split ratio on each face.
- Reject unsuitable transient, fullscreen, floating or already-owned windows at
  setup rather than guessing a layout transformation.
- External membership changes cancel the effect safely. An empty face or a
  changed layout must never leave an application inaccessible.
- [Saved arrangements and hold-to-peek](SAVED_CARDS.md) use the existing two-face
  model. Gestures, nested flip containers and linked flips remain deferred.
  See the [workflow roadmap](ROADMAP.md) for the remaining ideas and priorities.

## Acceptance checks

Run automated checks in a disposable nested session. Desktop trials are a
separate opt-in step after isolated validation. Copy libraries before loading so
rebuilding cannot overwrite a mapped file.

- Three real windows, only the active face visible and accepting input.
- Repeated switches preserve the outer geometry and restore each face's focus.
- Up to five panes per face share one pivot during animation; reversal and new input settle
  consistently.
- Closing/releasing a member, changing workspace, config reload, plugin unload,
  and external tree edits leave surviving applications accessible.
- A normal adjacent window remains independently focusable and is not moved by
  a flip.
- Workspace shortcuts preserve the complete card, with follow and silent moves
  across outputs; directional shortcuts stop at an outer edge.
- Unfold keeps two to six panes live within the original footprint, preserves
  inner proportions and focused face on refold, and rejects inadequate space.
- Updating both libraries preserves existing cards and native pairs; a failed
  load rolls back both libraries and reconstructs the prior arrangements.
- Existing native pair lifecycle and installer tests continue to pass.

## Evidence and open decisions

[hy3](https://github.com/outfoxxed/hy3) has the required nested tab/split model.
Its user commands do not constitute a stable inter-plugin container interface,
so the bridge and exact revision need explicit validation. A selected workspace
can use hy3, but compatibility does not imply unchanged navigation bindings.

[Hypertile](https://github.com/jdvmi00/hypertile),
[hyprdeck](https://github.com/chpock/hyprdeck), and
[hypr-layout](https://github.com/sim590/hypr-layout) provide useful layout,
lifecycle and setup references. They do not replace hy3's nested tab ownership
for this experiment. No external implementation is being copied into the native
Hyprflip backend.

## Floating cards and Settings

OmaCards offers **Float card** / **Tile card** on the selected card. Floating
cards use one native Hyprland group as their outer move/resize target; Hyprflip
arranges up to five apps on each face inside it. Drag or resize any visible
app with your usual window-manager mouse bindings. Flip, peek, unfold, pane
editing and workspace moves keep both faces together. Closing the last app on
one face releases the remaining apps. Unloading restores native window targets.

Guided creation inherits a floating front app's mode and position. Other apps
are fitted automatically. The Chill adapter hands those apps to Hyprflip and
protects the card from automatic rearrangement. Saved definitions remember
floating mode; they do not promise exact desktop coordinates after restarting.

In OmaCards, **Settings → Motion** chooses transition and speed, including
Instant for no animation. **Settings → Keyboard shortcuts** shows the actual
bindings. Choose an action, record a combination, then Save shortcut. Use default
restores that action's default after the same conflict checks. Preferences are
plain data in `$XDG_STATE_HOME/hyprflip`; install the updated guided setup to
load them on every Hyprland configuration parse.

Under a saved card's **Manage → Workspace…**, choose Current workspace or enter
a fixed workspace number. For example, Comms assigned to 3 always opens there;
an already-open Comms card moves there without launching another copy. Updating,
renaming and duplicating the saved setup preserve its workspace preference.
