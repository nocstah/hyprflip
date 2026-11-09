# Multi-app cards

A multi-app card holds one to five apps on each of its faces: two, or up to four. The Hyprflip
core builds it on Omarchy's default **dwindle** layout, or as a floating card;
no other layout plugin is involved. For installation, follow the
[dwindle installation guide](INSTALL.md#dwindle-multi-app-cards), including the
optional guided menus. This document covers card behavior, direct commands and
acceptance checks.

## Goal

Flip one desktop tile between two views of a task. For example, Gmail on the
front and up to five messaging applications sharing its reverse side.

Two to four faces, at most five panes per face, one split per face. The card's workspace
command moves its applications together. A flip restores the last focused application on
the destination face. Closing an application never closes the other applications.
Releasing a pane and disabling the effect must leave ordinary usable windows.

## How a card sits in the layout

On dwindle, a card is one locked Hyprland outer group, which dwindle places as a
single tile like any other window. The core's card engine
(`src/FloatingCards.cpp`) divides that tile into the two faces, arranges each
face's panes in a row or column, and shows only the visible face. A floating
card uses the same engine; its outer group is the floating move/resize target.
Removing an app or unloading the plugin restores each app's own window target,
so it returns to the layout as an ordinary window.

The controller talks to the engine through a small fixed interface
(`src/ContainerABI.hpp`). It is internal to the core: nothing outside the plugin
loads against it, and there is nothing to match or pin when you install.

Two-window pairs made with M/P on a tiled dwindle workspace remain plain
Hyprland groups with one app per face. They flip and peek, but do not take extra
apps; ungroup one and recreate it with O to get an editable card.

## Frame and spacing

With `plugin.hyprflip.card_frame = true` (the default), a shared outline and
compact Flip/Fold control mark the card. The label identifies the visible side
and app count. Other Hyprland groups keep their usual group bars. With
`card_frame = false` (Classic tabs), dwindle and floating multi-app cards use a
border-only appearance and two-window pairs show their native group bar.

Inner gaps inherit the workspace's tiling configuration, including directional
values. `gaps_in = 14` leaves 28 pixels of empty space between adjacent window
borders, just as it does between ordinary tiles. Pane geometry accounts for each
app's actual border width; it does not consume that gap with borders.
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
refuse a drop. Cards and apps must be on the same visible workspace. Two-window
pairs do not expose this target. Use `drag_to_add = false` to disable it. Both
Classic tabs and Card frame support the interaction.

## Try it in isolation

For an interactive demo with three shells already arranged into a dwindle card:

```sh
make test
python3 tests/nested_session.py --directory /tmp/hf-demo --native-cards
```

Click inside the demo and press **F8** to flip. These bindings exist only
inside the disposable compositor. Press Ctrl+C in the launcher to finish;
closing a nested output window alone can leave its compositor running without
an output. Use a fresh short `/tmp` directory for each running session.

For automated checks, start the regular fixture session instead and keep its
launcher running:

```sh
python3 tests/nested_session.py --directory /tmp/hf-dw
```

In another terminal, run a suite against it, for example:

```sh
python3 tests/dwindle_workflows.py /tmp/hf-dw/session.json
```

The suites load the built core into the selected disposable session, create real
terminal applications and clean up. Their IPC guard rejects the live compositor.
GPU access and an awake parent output are required. [TESTING.md](../TESTING.md)
lists the other suites and their options.

## Normal movement shortcuts

[`examples/containers-navigation.lua`](../examples/containers-navigation.lua)
optionally replaces Omarchy's existing movement bindings. Load it after the
Hyprflip modules and other keybindings. It calls `hl.unbind` before
replacing each binding:

| Shortcut | Behavior |
| --- | --- |
| Super+Shift+1…0 | Move the entire focused card to workspace 1…10 and follow it |
| Super+Shift+Alt+1…0 | Move the card there and keep focus on the source workspace |
| Super+Shift+arrows | Reorder the whole card toward a neighboring tile |

These keys previously moved or swapped the selected window. Ordinary windows
retain workspace movement and the standard swap command. A failed card move
leaves all panes in place. A directional card move at an outer edge does
nothing. Scratchpad and drag bindings are not replaced by this module.

## More than two faces

A card starts with a front and a back. Mark an app and run `attach face`
(`hl.plugin.hyprflip.attach("face")`, or **Add an app as a new face** in the
card menu and OmaCards) to add it as Face 3, then Face 4; the card turns to the
new face. Each flip turns to the next face, and the last comes round to the
front; `card <id> show <n>` turns straight to face `n`. Moving an app to the
other side moves it to the next face. Taking the only app off a face removes
that face while the card keeps at least two; on a two-face card it takes the
card apart as before. Unfolding lays every face out side by side, each with at
least the room its apps need. Saved cards, updates and `restore` keep every
face; `restore` writes faces after the back as `face …`.

A card with three or more faces slides sideways instead of flipping: the faces
stand in a row, the next one comes in from the right and the one before from
the left, and a face further away slides past the ones between.
A tap of the flip key goes back to the last face shown, so two faces in use
are one tap apart. Hold the key to see every face: a strip of previews opens
over the card after `switcher_delay_ms` (200 ms). Press the key again, Tab or
the arrow keys to step, a digit to pick, Escape to put it away, or click a
preview; letting go of the key and its modifiers turns to the face
highlighted. The previews are snapshots taken as the strip opens, since a
hidden face does not draw. `plugin:hyprflip:switcher = false` makes every tap
turn to the next face. Scripts use `hyprctl hyprflip switcher
open|step [back]|pick <n>|commit|cancel|last`.

## Temporary unfold

**Super+Ctrl+Alt+O** shows both faces in the card's existing tile. The wider axis
is preferred, with the other axis tried if application size limits require it.
Faces get unequal space when their apps need it, while each face keeps its own
pane proportions. If neither arrangement fits, the card stays folded. Both faces
contain live, interactive applications.

Press **Super+Ctrl+Alt+O** again to fold onto the face containing the focused
application. Inner split proportions are retained. While unfolded,
**Super+Ctrl+Alt+F** folds onto the
opposite face; it does not run the perspective turn while both faces are visible.
Movement, release, close and config reload continue to work. Leave fullscreen
before moving a card. Cards fullscreen as a whole:
fullscreen any app and the visible face (or both faces, unfolded) fills the
screen; flip, peek, unfold and layout changes work there too.

## Guided creation from O

Install the optional guided picker:

```sh
python3 scripts/install-setup.py --dry-run
python3 scripts/install-setup.py
```

This adds a small Python helper and
[`examples/containers-setup.lua`](../examples/containers-setup.lua), loaded after
the other Hyprflip bindings. It backs up affected files and installs
**Super+Ctrl+Alt+O/C/L/K/Space** for guided creation, editing, saved-card launching,
finding open card apps and hold-to-peek, plus **Super+Ctrl+Alt+Return** to fullscreen
the whole card. While a card is
fullscreen, editing, adding and removing apps keep it fullscreen; ungrouping and
reopening missing apps wait until you leave. No compositor library is replaced or unloaded.

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

The current workspace must use dwindle. Choices include ungrouped windows
from any normal workspace; existing cards, pinned windows and scratchpads
are excluded. Local apps appear first, followed by **Add from workspace X**
entries in workspace order. Each entry opens that workspace's app list, with
**Back to all apps** to return. Selected remote apps move to the front window's
workspace after all choices are complete. App names and window
titles distinguish choices; same-named windows get separate entries. The helper
rechecks window identity, workspace and ownership before applying the selection.
Guided creation never launches or closes applications. A second pane uses the card's longer
axis; the `attach horizontal`/`attach vertical` commands can establish the first
split in either direction. A third app joins the existing row or column,
retaining its direction and the relative sizes of its existing panes. Creation
does not require enough space to show both faces simultaneously.

Floating apps are fitted into the card automatically after selection, with no
separate tiling confirmation. Their picker rows say **Resizes to fit card**.
Cancelling before the final selection preserves their arrangement.
Creating tiles only the selected apps; a failure restores
their previous floating positions and returns imported apps to their workspaces.
For apps managed by Omachill, install the optional
[Chill integration](TRANSITIONS.md#chill-mode) so Auto Chill respects cards.

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
  It releases the chosen app into its own tile and keeps it open. The keyboard
  stays where it was: on the released app if you were using it, otherwise on
  the app you were using. The other apps remain in the card. The menu
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
- **Move an app to the other side…** lets you choose any pane and moves it
  onto the opposite face; the card turns to that face, taking the keyboard
  along if it was in the card. It is offered when the source has at least two
  apps and the destination has room. The apps left behind keep their
  proportions among themselves, and the moved app joins with an equal share.
  The destination keeps its existing direction, or uses the card's longer axis
  when gaining its second app.

Layout controls edit the existing card in place and preserve folded/unfolded
state. If an application's size limits prevent a change, the original
membership, order, proportions and focus are restored. Custom bindings can call
`hl.plugin.hyprflip.layout("horizontal")`, `layout("vertical")`,
`layout("balance")` or `other_side()`; the last function optionally accepts a
live address on the focused face. IPC equivalents are
`hyprctl hyprflip 'layout horizontal'` and `hyprctl hyprflip other_side`.

Omarchy's **Super+J** keeps toggling the focused split between beside and
stacked. App order and replacement use C; no desktop shortcuts are reassigned.
On a tiled card, a tiled replacement trades places with the outgoing app: the
outgoing app takes the replacement's former tile and the card keeps its own
tile and size. A replacement whose tile is too small for the outgoing app is
refused before anything moves. Importing a replacement from another workspace
can reflow the surrounding workspace first, just as adding an app does. The
direct API expects an ungrouped replacement already on this workspace:
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

To update an existing guided setup installation, run
`python3 scripts/install-setup.py`. It checks O/C/L/Space for shortcut conflicts, backs
up the helper and Lua files, and reloads configuration. It does not replace or
unload compositor libraries.

## Updating

Open dwindle and floating cards stay open through a core update:
`python3 scripts/bootstrap.py` (or `scripts/install.py` followed by
`scripts/install-setup.py`) records each card, reloads the core and rebuilds it
with the same apps, sides, proportions, focus and floating frame. Leave
fullscreen first. See [updating](INSTALL.md#update) for what the installer
reports and how it rolls back.

## Interaction

`hyprctl hyprflip card` creates a multi-app card from the marked and focused
windows. Its Lua equivalent is `hl.plugin.hyprflip.card()`. On a tiled dwindle
workspace, `pair` (the **P** shortcut) keeps the simpler two-window group; with
floating windows, both actions create a floating card. On another tiled layout,
`card` is refused.

Use the following actions through `hyprctl hyprflip`, or prefix them with
`python3 tests/control.py /tmp/hf-dw/session.json` when controlling a disposable
session from the parent desktop.

1. Focus the front application and run `hyprflip mark`.
2. Focus the back application and run `hyprflip card`.
3. Focus a third application and run `hyprflip mark`.
4. Focus the card face that should receive it and run `hyprflip attach`.
5. Run `hyprflip flip` for the everyday front/back switch.

| Action | Behavior |
| --- | --- |
| `attach` or `attach horizontal` | Add a second app beside the first, or a third in the existing row/column |
| `attach vertical` | Add a second app below the first, or a third in the existing row/column |
| `release` | Move the focused pane outside the card; dissolve if that empties a face |
| `workspace 2` | Move all card members to numbered workspace 2 and follow them |
| `workspace 2 silent` | Move the card and remain on the source workspace |
| `move left` / `right` / `up` / `down` | Reorder the entire card toward a neighbor |
| `unfold` | Toggle showing both faces together in the existing card frame |
| `floating` | Toggle the whole card between floating and tiled placement |
| `fullscreen` | Toggle whole-card fullscreen |
| `unpair` | Turn both faces into ordinary visible windows |
| `cancel` | Clear the pending mark |
| `status` | Report two-window `pairs` and multi-app `containers` separately |
| `card <id> …`, `restore [quiet] …` | Act on a card by its id, or build one, without taking the focus ([scripting](SCRIPTING.md)) |

Lua exposes `hl.plugin.hyprflip.attach("horizontal")`, `release()`,
`workspace(2, follow)`, `move("left")`, `unfold()`, `floating()`,
`fullscreen()` and `in_container()` alongside the existing direct action
functions. `follow` defaults to true. The supplied modules bind M/P/F/U/Escape;
the guided setup module adds its keys plus H and V (`attach` beside or below)
and E (`release`). Without guided setup, `examples/pane-keys.lua` binds H, V,
E and a plain O unfold. Change any of them in OmaCards.

Focus and close still act on real applications. Tiled resizing adjusts panes;
floating movement and resizing adjust the shared frame. Use the navigation module
or explicit `workspace` action to move a whole card; an unadapted window-move
command can act on the selected pane. Leave fullscreen before moving a card.
New windows open outside the card. Unloading Hyprflip dissolves its cards
into ordinary windows; the supplied installer rebuilds them across an update.

## Current boundaries

- Hyprland 0.56.2 only. Tiled cards need a dwindle workspace; floating cards
  keep their shared frame on other layouts.
- Tiled or floating cards on one workspace; no nested flip cards.
- At most five apps per face, arranged in one row or column. No nested splits
  within a face.
- Unfold places rows of three or more apps above one another and columns beside
  one another. Mixed split directions use the card's proportions. Application
  size limits can select the alternate arrangement or refuse the unfold.
- Shortcut and Lua workspace moves accept positive numeric IDs. A card moves to
  named and special workspaces by its id
  ([driving cards from other programs](SCRIPTING.md)). Floating cards support
  whole-card dragging and resizing.
- The navigation module does not automatically replace existing movement
  shortcuts; load it explicitly.
- Floating cards hide the native group bar. Popups do not rotate;
  unsuitable rendering conditions switch instantly.
- The compositor does not restore sessions at login or add individual-pane
  capture semantics. The optional guided helper handles saved cards and explicit
  missing-app launching separately.

## Usability boundaries

- Flip is the everyday operation. Setup actions explicitly add or release a
  window; unrelated new windows are not silently adopted.
- Input settles a turn before normal delivery. External focus never gets pulled
  back. Urgency alone does not flip a card.
- Ordinary focus and close act on real applications. Do not leave keyboard focus
  on a structural group as a side effect of a flip.
- Preserve the external footprint during a flip and the split ratio on each face.
- Reject unsuitable transient, fullscreen or already-owned windows at setup
  rather than guessing a layout transformation.
- External membership changes cancel the effect safely. An empty face or a
  changed layout must never leave an application inaccessible.
- [Saved arrangements and hold-to-peek](SAVED_CARDS.md) use the existing two-face
  model. Gestures, nested flip cards and linked flips remain deferred.
  See the [workflow roadmap](ROADMAP.md) for the remaining ideas and priorities.

## Acceptance checks

Run automated checks in a disposable nested session. Desktop trials are a
separate step after isolated validation. Copy libraries before loading so
rebuilding cannot overwrite a mapped file.

- Three real windows, only the active face visible and accepting input.
- Repeated switches preserve the outer geometry and restore each face's focus.
- Up to five panes per face share one pivot during animation; reversal and new input settle
  consistently.
- Closing/releasing a member, changing workspace, config reload, plugin unload,
  and external layout edits leave surviving applications accessible.
- A normal adjacent window remains independently focusable and is not moved by
  a flip.
- Workspace shortcuts preserve the complete card, with follow and silent moves
  across outputs; directional shortcuts stop at an outer edge.
- Unfold keeps every pane live within the original footprint, preserves
  inner proportions and focused face on refold, and rejects inadequate space.
- Updating the core keeps open cards and native pairs; a failed update rolls
  back and rebuilds the prior arrangements.
- Existing native pair lifecycle and installer tests continue to pass.

## Prior art

[Hypertile](https://github.com/jdvmi00/hypertile),
[hyprdeck](https://github.com/chpock/hyprdeck), and
[hypr-layout](https://github.com/sim590/hypr-layout) provide useful layout,
lifecycle and setup references. No external implementation is copied into
Hyprflip; cards are built from Hyprland's own groups and the dwindle layout.

Earlier previews could also build cards through an optional hy3 provider. That
provider has been removed; to move an existing setup off it, see
[leaving the hy3 provider](INSTALL.md#leaving-the-retired-hy3-provider).

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
