# Hyprflip

**Give your windows a back side.**

Keep Gmail on the front and WhatsApp + Telegram on the back. Flip to the apps
you need, briefly peek at the other side, or unfold the whole card to work with
both faces together. Each app stays a real, live window with its own state.

[![Gmail flips to WhatsApp and Telegram, then unfolds into three apps](media/hyprflip-preview.gif)](media/hyprflip-demo.mp4)

**[Watch / download the demo — MP4](media/hyprflip-demo.mp4)** ·
[Poster](media/hyprflip-poster.png) · [Recording details](media/README.md)

Actual desktop footage. The multi-app card in the video uses the optional
**experimental hy3 integration**.

[Features](#features) · [Install](#install) · [First card](#make-your-first-card) ·
[Shortcuts](#shortcuts) · [Transitions](#transitions) ·
[Compatibility](#compatibility-and-limits) · [Documentation](#documentation)

**Early release:** targets **Hyprland 0.56.2**, with matching development headers
and compiler ABI. The core is a native C++/GLES plugin. Multi-app cards use a
separately built, pinned hy3 provider; the guided menus use **Omarchy 4**.

## Features

| Feature | What it does |
| --- | --- |
| **Two faces, one tile** | Switch between related applications without moving to another workspace. |
| **Up to three apps per face** | Arrange each face in a row or column: up to six apps in one card. |
| **Flip and reverse** | Turn the card with perspective, easing and shared lighting. Press flip again mid-turn to smoothly reverse it. |
| **Hold to peek** | Hold a key to reveal the other side; release to return. Clicking or typing keeps the side you are using. |
| **Temporary unfold** | Show both faces together in the existing tile. Use any app, then fold onto the face you want. |
| **Edit either side** | Add or remove any app, including an unfocused pane. Released apps stay open. |
| **Replace an app** | Exchange a pane with an open app while retaining its position and share of the side. The previous app stays open. |
| **Layout controls** | Choose beside, stacked or equal sizes. Swap two apps, reorder three, or move an app to the other face. |
| **Apps from other workspaces** | Pick local apps first, or open an **Add from workspace X** submenu to bring another app into the card. |
| **Saved cards** | Name an arrangement and reopen it with its apps, split directions, proportions, remembered focus and visible face. |
| **Launch and repair** | Reuse open apps, launch missing apps through installed launchers, or reopen missing panes in a surviving saved card. |
| **Card library** | Search, open, update, rename, duplicate and delete saved definitions. An already-open card is focused without duplication. |
| **Move the whole card** | Optional navigation bindings move every member to another workspace or reorder the card beside neighboring tiles. |
| **Seven transitions** | Flip, Vertical flip, Slide, Fade, Dissolve, Portal and Instant, with preview and a saved preference. |
| **Omarchy integration** | Native themed menus, existing Super+J split toggling, and an optional Omachill adapter that keeps cards tiled. |

### Choose your setup

| | Native pairs | Experimental cards |
| --- | --- | --- |
| Apps per face | One | One to three |
| Layout | Native Hyprland groups; dwindle tested | Pinned hy3 provider, tiled windows |
| Floating windows | A pair can be floating | The guided menu can tile selected apps before adding them |
| Flip, transitions and peek | Yes; custom binding for peek | Yes |
| Unfold, pane editing and whole-card navigation | — | Yes |
| Guided menus and saved-card library | — | Optional Omarchy 4 helper |
| Installation | Supplied core installer or hyprpm | Core + matching provider + optional helper |

The default installer and hyprpm install **native pairs**. Follow the
[container installation guide](docs/INSTALL.md#experimental-multi-app-cards)
to get the workflow shown in the video. The three-app limit is Hyprflip's
supported model; it is not a limit of hy3 itself.

## Install

You need Hyprland **0.56.2**, its matching development headers, a matching
C++26-capable compiler, CMake 3.25+, Ninja, pkg-config, Lua 5.4 and GLES libraries.
The installer also needs Python 3 and an existing Hyprland Lua configuration.

### Native two-window pairs

Run from a terminal in your Hyprland session:

```sh
git clone https://github.com/nocstah/hyprflip.git
cd hyprflip
make test
python3 scripts/install.py --dry-run
python3 scripts/install.py
```

The installer checks shortcut conflicts, backs up affected files, installs the
core and Lua bindings, reloads configuration and validates the result. Existing
native pairs and customized settings are preserved during an update.

Prefer hyprpm? Use the [hyprpm instructions](docs/INSTALL.md#hyprpm).
For another configuration layout, use the
[manual loading instructions](docs/INSTALL.md#manual-core-loading).
Use one installation method for the core.

### Multi-app cards shown in the demo

The container build fetches the pinned hy3 source and builds both libraries:

```sh
./scripts/build-containers
```

Try it in a disposable nested desktop before enabling a real workspace:

```sh
python3 tests/nested_session.py --directory /tmp/hf-demo --containers
```

This demo needs `foot` and a running Wayland session. Click inside it and use
**F8** to flip. Stop its launcher with **Ctrl+C** when finished. F6/F7/F8 are
**demo-only** shortcuts.

Then follow **[first-time container activation](docs/INSTALL.md#first-time-activation)**
to install the provider, enable workspace 8 and add the Omarchy menus. The guide
also covers all-workspace operation, navigation bindings, upgrades and removal.
Building alone does not install or load either library.

## Make your first card

### Gmail in front, WhatsApp + Telegram behind

With the container provider and guided setup enabled:

1. Open Gmail, WhatsApp and Telegram as separate app windows. A browser tab must
   first be in its own window.
2. On a hy3 workspace, focus Gmail and press **Super+Ctrl+Alt+O**.
3. Choose WhatsApp, then **Add Telegram**. Choose **Only two apps** if offered.
   Apps on other workspaces are available under **Add from workspace X**.
4. The card groups automatically with Gmail in front. Press
   **Super+Ctrl+Alt+F** to turn it over.
5. Press **Super+Ctrl+Alt+O** to use all three apps together. Focus the side you
   want to keep and press O again with the same modifiers to fold back.

Already paired Gmail with WhatsApp? Flip to WhatsApp, press
**Super+Ctrl+Alt+C → Add an app to this side**, then choose Telegram.

For native pairs, focus the front app and press **Super+Ctrl+Alt+M**, focus the
back app and press **Super+Ctrl+Alt+P**, then use **F** with the same modifiers.
Both apps must share a workspace and both be tiled or both floating.

### Shape the card around your workflow

Focus the side you want to change and open **Super+Ctrl+Alt+C**:

- **Layout of this side…** changes direction, equalizes sizes, swaps two apps
  or reorders three. **Super+J** keeps Omarchy's existing split-direction toggle.
- **Replace an app…** exchanges any pane with an open app, including one from
  another workspace. This also works on a full side or its only app.
- **Move an app to the other side…** transfers a pane while keeping at least
  one app on each face.
- **Remove [app] from card** releases that app. When it is the side's only app,
  the menu explicitly offers **Ungroup card** instead. Apps remain open.

### Save it for later

Choose **C → Save card…**, enter a name, then use **Super+Ctrl+Alt+L** to search
and open it. Selecting a running card switches to it. Otherwise, matching open
apps are reused and missing apps launch through their installed desktop entries.

After editing a saved card, use **C → Manage card… → Update saved card**.
The same menu offers Rename, Duplicate and Delete. If a pane closes while the
card survives, **C → Reopen missing apps** can restore it in place. If a whole
face disappears, use L to reopen the saved arrangement.

Saved cards remember the arrangement, not browser tabs or documents. They open
when requested rather than automatically at login. See
[matching, launchers, cancellation and storage](docs/SAVED_CARDS.md).

## Shortcuts

Hold **Super + Ctrl + Alt** for the following keys:

| Key | Action | Required setup |
| --- | --- | --- |
| **F** | Flip the focused pair or card | Core bindings |
| **M** / **P** | Mark the front / pair the focused app as the back | Core bindings |
| **U** | Ungroup the card; keep its apps open | Core bindings |
| **Escape** | Cancel a pending mark | Core bindings |
| **O** | Unfold/fold; on an ungrouped app, open guided creation | Containers; helper for creation |
| **C** | Edit a card, choose transitions or manage saved cards | Omarchy helper |
| **L** | Search and open saved cards | Omarchy helper |
| **Space**, held | Peek at the other side; release to return | Helper binding, or a custom core binding |
| **H** / **V** | Attach a marked app beside / below the focused pane | Container bindings |
| **E** | Release the focused pane | Container bindings |

Optional [navigation bindings](docs/INSTALL.md#move-cards-with-normal-shortcuts):

| Shortcut | Action |
| --- | --- |
| **Super+Shift+1…0** | Move the whole card to workspace 1…10 and follow it |
| **Super+Shift+Alt+1…0** | Move the card while staying on the source workspace |
| **Super+Shift+arrows** | Reorder the whole card toward a neighboring tile |

Without that module, ordinary window-move shortcuts may move only the focused
pane. Card workspace moves require a numbered hy3 destination.

## Transitions

Choose **C → Transition → mode → Preview** or **Use**. Preview turns over and
back; Use remembers the mode across reloads and restarts.

| Mode | Motion |
| --- | --- |
| **Flip** | Default horizontal perspective turn with live app surfaces |
| **Vertical flip** | A vertical perspective turn with live app surfaces |
| **Slide** | Slide between snapshots of the faces |
| **Fade** | Fade between face snapshots |
| **Dissolve** | Experimental patterned dissolve |
| **Portal** | Experimental portal-style reveal |
| **Instant** | Switch without an animation |

Snapshot effects hold app pixels only during the turn, then return to live
windows. Keep Flip or Vertical flip for live video during the motion.
All modes respect Hyprland's disabled animations and settle before new app input.

For custom Lua configurations:

```lua
hl.config({ plugin = { hyprflip = {
    duration_ms = 420,    -- 0–2000; 0 switches instantly
    transition = "flip", -- flip, vertical, slide, fade, dissolve, portal, instant
    enabled = true,
    notifications = true,
    perspective = 5.0,   -- 2–8; higher means less perspective
    retreat = 0.02,      -- 0–0.2
} } })
```

See [transition behavior and Omachill integration](docs/TRANSITIONS.md).
The transition preference saved by the optional menu is reapplied on reload.

## Compatibility and limits

- **Version pin:** Hyprland 0.56.2 only. Rebuild after compositor or ABI changes;
  other versions need adaptation and testing.
- **Containers:** one workspace, two faces, at most three apps in a row or
  column per face. Nested flip cards, arbitrary pane trees and floating
  containers are not implemented. Application minimum sizes can prevent a split
  or unfold; the existing card is kept when a change is refused.
- **Fullscreen and movement:** native pairs use native group behavior. Leave
  fullscreen before flipping, unfolding or moving an experimental container.
  Whole-card dragging and named/special-workspace moves are not implemented.
- **Saved setups:** live card identities do not survive a compositor restart.
  The optional saved-card launcher recreates named arrangements when requested.
- **Omachill:** integration is optional and targets Omachill 1.2.0. Install the
  [adapter](docs/TRANSITIONS.md#chill-mode) before using Auto Chill with cards.
- **Hyprglass:** tested with the documented builds; its extra background pass
  is temporarily suppressed during a turn and restored afterward. Keep it
  loaded while the container updater replaces Hyprflip and hy3.
- **Rendering:** popups do not rotate. Unsupported geometry or surface conditions
  fall back to an instant switch. HDR, individual-window capture, other layouts
  and arbitrary plugin combinations need further testing.

For troubleshooting, run:

```sh
hyprctl hyprflip status
hyprctl configerrors
```

`status` lists native `pairs` and experimental `containers` separately, reports
`container_provider`, and includes `last_fallback` for instant-switch reasons.
See [installation and recovery](docs/INSTALL.md#troubleshooting) and the
[recorded validation](TESTING.md). Desktop tests cover real apps, fractional
scaling, rotated outputs, card editing, saved-card launching and plugin upgrades;
CI alone does not establish compositor or GPU compatibility.

## Documentation

- [Install, update, troubleshoot and remove](docs/INSTALL.md)
- [Container behavior, direct commands and Lua API](docs/CONTAINERS.md)
- [Saved cards, launchers and hold to peek](docs/SAVED_CARDS.md)
- [Transitions and Chill compatibility](docs/TRANSITIONS.md)
- [Validation and test commands](TESTING.md)
- [Roadmap](docs/ROADMAP.md) — gestures and other future ideas
- [Architecture and prior art](docs/DESIGN.md) — Compiz, Project Looking Glass
  and Apple Dashboard
- [Contributing](CONTRIBUTING.md) · [Issues](https://github.com/nocstah/hyprflip/issues)

The core is [MIT licensed](LICENSE). The optional hy3 bridge is
[GPL-3.0-only](integrations/hy3/LICENSE), built with a separately fetched, pinned
hy3 source tree. See [integration licensing](integrations/hy3/README.md).
