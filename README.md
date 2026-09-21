# Hyprflip

**Give your windows a back side.**

Pair two real applications into one window that turns over to reveal the other. Keep a browser on the front and a chat window on the back, or a terminal and its documentation. Each side keeps its own application state.

Hyprflip is a native C++/GLES plugin for **Hyprland 0.56.2**. It combines native two-member window groups with a reversible perspective animation, synchronized to the output's render cycle.

## What it does

- Mark two existing windows as the front and back of one card.
- Flip in place with a configurable 420 ms turn, gentle easing and filtered edges.
- Move, resize and fullscreen the pair through Hyprland's native group behavior.
- Reverse an unfinished turn by pressing flip again; the card brakes smoothly
  before returning, preserving its momentum.
- Unpair into two ordinary windows whenever you want.
- Respect disabled animations and settle safely on input, focus or workspace changes.

**Early release:** tested with Hyprland 0.56.2, dwindle, Wayland/XWayland applications, fractional scaling, rotated outputs and Hyprglass 1.0. Pairs are held in memory and must be recreated after a compositor restart. See [validation and limits](TESTING.md).

## Install

Use one installation method. You need a compiler matching the running Hyprland build, C++26, CMake, Ninja, pkg-config, Lua 5.4 and GLES development libraries. The plugin checks the Hyprland version at build time and the commit/dependency ABI when loaded.

### Build and install with the supplied Lua setup

```sh
git clone https://github.com/nocstah/hyprflip.git
cd hyprflip
make test
python scripts/install.py --dry-run
python scripts/install.py
```

This installer expects an existing `~/.config/hypr/hyprland.lua`. It installs the library in `~/.local/lib/hyprflip/`, adds the [Lua configuration](examples/hyprflip.lua), checks shortcut conflicts, backs up affected files, reloads and validates configuration. Upgrades preserve existing pairs and customized settings. A failed update restores the old files and retains pair-recovery metadata for the same session.

For a custom configuration layout, build with `make` and load manually:

```sh
hyprctl plugin load "$PWD/build/hyprflip.so"
hyprctl hyprflip status
```

Adapt the library path in `examples/hyprflip.lua` and load that module from your configuration if you want it enabled on login.

### hyprpm

The manifest includes a commit pin for the supported Hyprland build:

```sh
hyprpm add https://github.com/nocstah/hyprflip
hyprpm enable hyprflip
hyprpm reload
```

Add the settings and shortcuts from [examples/hyprflip.lua](examples/hyprflip.lua) to your Lua configuration, **omitting its `hl.plugin.load(...)` line** because hyprpm owns loading. Run `hyprpm reload` from your session startup to load enabled plugins after login, as described in the [Hyprland plugin documentation](https://wiki.hypr.land/Plugins/Using-Plugins/).

The supplied installer and manual loading were exercised during development; the hyprpm build command is included and uses the same pinned source, but end-to-end hyprpm installation is not part of the recorded compositor tests. Rebuild after a Hyprland upgrade. Other Hyprland versions need adaptation and testing.

## Use

With the supplied shortcuts, hold **Super + Ctrl + Alt**:

| Key | Action |
| --- | --- |
| **M** | Mark the focused window as the front |
| **P** | Attach the focused window as the back |
| **F** | Flip the pair |
| **U** | Unpair into separate windows |
| **Escape** | Cancel the pending mark |

Focus your browser and press **M**. Focus a separate chat window and press **P**. Press **F** to turn between them. A browser tab must first be in its own window; a ChatGPT window works as an ordinary application, without an API integration.

Both windows must be on the same workspace and both tiled or both floating. Leave fullscreen before creating a pair. The marked window defines the initial visible side; the native groupbar shows both titles. Pairing and unpairing can rearrange tiles, while flips preserve the shared footprint. Closing either side leaves the other usable.

Commands are also available through IPC:

```sh
hyprctl hyprflip mark
hyprctl hyprflip pair
hyprctl hyprflip flip
hyprctl hyprflip unpair
hyprctl hyprflip cancel
hyprctl hyprflip finish
hyprctl hyprflip status
```

`status` returns JSON with pairs, current side, progress and the last instant-switch reason. Lua exposes the same actions under `hl.plugin.hyprflip`; actions return `success, message`, and `status()` returns JSON.

## Motion settings

```lua
hl.config({ plugin = { hyprflip = {
    duration_ms = 420,   -- 0–2000; 0 switches instantly
    transition = "flip", -- flip, vertical, slide, fade, dissolve, portal, instant
    enabled = true,     -- false keeps pairing without motion
    notifications = true,
    perspective = 5.0,  -- 2–8; higher means less perspective
    retreat = 0.02,     -- 0–0.2; depth retreat during the turn
} } })
```

Hyprland's global `animations.enabled = false` also disables flip motion. Popups, pending geometry changes or unavailable surface buffers use an instant native switch. Active grabs, drag-and-drop and pointer constraints defer flipping. Incompatible application size limits reject pairing or flipping.

On Omarchy, the container picker offers **Super+Ctrl+Alt+C → Transition**,
with **Preview** and **Use** actions. Previews turn over and back without
changing the saved preference. Dissolve and Portal are experimental effects.
The picker saves the mode for all cards across config reloads and restarts.
See [transitions and Chill compatibility](docs/TRANSITIONS.md) for rendering
details, limits and the optional Omachill integration.

New application input settles an unfinished turn before normal delivery. Changing focus does not pull it back. One pair animates at a time; starting a turn on another pair settles the previous one.

## Compatibility and troubleshooting

- **Nothing happens after restarting Hyprland:** check `hyprctl hyprflip status`. If `pairs` is empty, mark and pair your windows again.
- **Unknown request:** the plugin is not loaded. Use `hyprpm reload` for a hyprpm installation, or `hyprctl plugin load` with the installed library path.
- **ABI mismatch:** rebuild with the matching Hyprland headers, dependency versions and compiler.
- **Instant switch:** inspect `last_fallback` in `status`; native switching is used when animation cannot run safely.
- **Hyprglass 1.0:** its separate background pass is temporarily opted out during a turn and restored afterward. Existing opt-out tags are preserved.
- **Popups and capture:** popups are separate compositor passes and do not rotate with the card. Individual-window capture, HDR, other layouts and other plugins need further testing.

## Unload and recovery

For the supplied installer:

```sh
hyprctl plugin unload "$HOME/.local/lib/hyprflip/hyprflip.so"
```

Unload settles a turn and leaves the applications in an ordinary native group. Hyprland 0.56.2 can cache its configured plugin list, so an ordinary config reload after a manual unload may not reload the library. Use an explicit `hyprctl plugin load` to load it again.

To remove the installation persistently, remove `require("hypr.hyprflip")` from your main Lua configuration, reload, then unload the library. For hyprpm, use `hyprpm disable hyprflip` and `hyprpm reload` instead.

You can reattach Hyprflip to an existing two-member native group without changing focus or geometry:

```sh
hyprctl hyprflip adopt 0xFRONT_ADDRESS 0xBACK_ADDRESS
```

Use live addresses from `hyprctl -j clients`. Adoption rejects unrelated windows, stale addresses and groups with more than two members. Lua provides `hl.plugin.hyprflip.adopt(front_address, back_address)` too.

## Development and background

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development and bug reports, [TESTING.md](TESTING.md) for the nested compositor harness, and [docs/DESIGN.md](docs/DESIGN.md) for the architecture and prior art: Compiz window groups, Sun Project Looking Glass and Apple Dashboard flips.

Gesture-controlled turns are a possible future addition. The native backend
pairs two existing windows; the optional Omarchy container workflow includes
an app picker, layout controls and saved arrangements that can launch apps.

### Experimental containers

On Omarchy 4, the optional [guided setup](docs/CONTAINERS.md#guided-creation-from-o)
lets **Super+Ctrl+Alt+O** create a card from an ungrouped window: choose up to three
apps for its back in the native menu. The apps group automatically, showing the
front face. On an existing card, the same shortcut
unfolds or folds it. Cancelling any picker leaves the windows unchanged.

**Super+Ctrl+Alt+C** opens [Edit card](docs/CONTAINERS.md#edit-an-existing-card):
add an open app to the focused side, or remove any app while keeping it
open. Local apps come first; **Add from workspace X** lists apps elsewhere and
moves the selected app here. A full side explains its three-app limit; removing a side's only app is
explicitly labeled **Ungroup card**.

Choose **Layout of this side…** for **Beside**, **Stacked** or **Equal sizes**.
It also offers **Swap app positions** for two apps, or **Reorder apps…** for
three. Move apps left/right or up/down while keeping the split sizes and focus.
Omarchy's **Super+J** continues to toggle between beside and stacked.
**Replace an app…** exchanges any app on this side with an open app, including
one from another workspace. Its position and share of the side are retained;
the previous app stays open separately. This also works on a full side or a
side containing only one app.
**Move an app to the other side…** can move any pane, including one that is not
focused. Both sides keep at least one app, with at most three on either side.

The same menu offers **Save card…** and **Open saved card…**. Save a named
arrangement, then open it again with both faces, split sizes and focus remembered.
Open apps are reused; missing apps use installed launchers. Review the choices
when needed under **Manage saved cards… → Review apps and launchers…**.
**Super+Ctrl+Alt+L** opens the searchable saved-card launcher directly. Select a
name and press Enter to open it immediately, or switch to its displayed workspace
if it is already running. C also works on an empty workspace.

After adjusting a card, use **C → Manage card… → Update saved card** to remember
its current layout without retyping its name. **Rename…** and **Duplicate…**
manage the saved setup without changing running apps.

Closed an app from a saved card? Use **C → Reopen missing apps** to put it back
in its original position. The surviving card keeps its visible side, focus,
split direction and relative pane sizes. Existing matching apps can be brought
from other workspaces. If several saved setups match, choose which one to use.

Hold **Super+Ctrl+Alt+Space** to **peek** at the opposite face; release Space to
return. Clicking or typing keeps the side you are using. See
[saved cards and peek](docs/SAVED_CARDS.md) for matching, storage and input behavior.

An opt-in [hy3 container experiment](docs/CONTAINERS.md) supports two faces with
up to three tiled panes on each face: for example, Gmail on the front and three
messaging apps on the back. Each side is one row or column; adding a third app
preserves its split direction and the existing panes' relative sizes. It adds
explicit attach/release, remembers the focused pane, and moves the whole card
between hy3 workspaces. All panes rotate around
one shared pivot. Optional movement bindings keep cards together with normal
workspace and arrow shortcuts. Temporary unfold shows both faces together;
three-app rows unfold above one another, and columns beside one another.
Folding restores the face you are using and retains inner split proportions.

Build it with `./scripts/build-containers`. This creates separate experimental
libraries; it does not install them or change your desktop. The regular installer
and hyprpm setup still use native two-window groups. Start with the disposable
session instructions in the [experiment guide](docs/CONTAINERS.md).
Already-enabled trials have a separate updater that preserves card definitions;
the native installer refuses to discard active containers. See the guide for
the update procedure and [roadmap](docs/ROADMAP.md) for remaining work.

The core is licensed under the [MIT license](LICENSE). The optional hy3 bridge
is [GPL-3.0-only](integrations/hy3/LICENSE) and is built into a separately fetched,
pinned hy3 library. See [integration licensing](integrations/hy3/README.md).
