# Hyprflip

**Give your windows a back side.**

Pair two real applications into one window that turns over to reveal the other. Keep a browser on the front and a chat window on the back, or a terminal and its documentation. Each side keeps its own application state.

Hyprflip is a native C++/GLES plugin for **Hyprland 0.56.2**. It combines native two-member window groups with a reversible perspective animation, synchronized to the output's render cycle.

## What it does

- Mark two existing windows as the front and back of one card.
- Flip in place with a configurable 420 ms turn, gentle easing and filtered edges.
- Move, resize and fullscreen the pair through Hyprland's native group behavior.
- Reverse an unfinished turn by pressing flip again.
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
    enabled = true,     -- false keeps pairing without motion
    notifications = true,
    perspective = 5.0,  -- 2–8; higher means less perspective
    retreat = 0.02,     -- 0–0.2; depth retreat during the turn
} } })
```

Hyprland's global `animations.enabled = false` also disables flip motion. Popups, pending geometry changes or unavailable surface buffers use an instant native switch. Active grabs, drag-and-drop and pointer constraints defer flipping. Incompatible application size limits reject pairing or flipping.

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

Automatic companion launching, saved pair recipes, gesture-driven turns and a window picker are possible future additions. The current release focuses on explicitly pairing two existing windows.

Licensed under the [MIT license](LICENSE).
