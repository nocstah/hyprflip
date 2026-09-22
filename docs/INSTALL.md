# Install and update Hyprflip

Hyprflip currently targets **Hyprland 0.56.2**. Choose native two-window pairs,
or add the experimental hy3 provider for multi-app cards. **Omarchy is optional.**
Guided menus and saved cards prefer its running shell and automatically use
Fuzzel, Rofi or Wofi when it is unavailable. The core and provider also expose
commands for custom configurations.

These instructions describe the repository's current implementation. The
multi-app provider is experimental and has a separate update path. Build and
load matching core/provider versions together.

## Requirements

The optional [OmaCards companion](https://github.com/nocstah/omacards) uses the
shared helper installed by `scripts/install-setup.py` and provides a native bar panel.
For native pairs without the container provider, use `--backend-only` to install
that helper and motion preferences without adding container shortcuts.
See [the panel interface](PANEL_API.md) for its behavior and compatibility.

| Component | Requirements |
| --- | --- |
| Core | Hyprland 0.56.2 and matching development headers; matching C++26-capable compiler; CMake 3.25+; Ninja; pkg-config; Lua 5.4; GLESv2 |
| Supplied installer | Python 3, `hyprctl`, a running Hyprland session and an existing `~/.config/hypr/hyprland.lua` |
| Experimental provider | Git, Python 3, and the pinned hy3 dependencies: pixman, libdrm, Pango/PangoCairo, libinput, Wayland client and xkbcommon development files |
| Guided menus and saved cards | Python 3, `hyprctl`, `notify-send` (libnotify), `gio`/`gdbus` (GLib), and either a responding Omarchy 4 shell or Fuzzel / Rofi with Wayland support / Wofi |
| Launch progress and Cancel | A desktop notification service supporting actions, such as Omarchy shell, Mako or Dunst |
| Disposable interactive demo | A running Wayland session and `foot` |

Check the compositor and headers before building:

```sh
hyprctl version
pkg-config --modversion hyprland lua5.4 glesv2
```

The Hyprland package version alone is insufficient if its commit, dependencies
or compiler ABI differ from the running compositor. The project keeps build-time
and runtime compatibility checks enabled. Rebuild against the matching headers;
do not disable ABI checks to make another version load.

Clone once, then run the remaining build commands from the checkout:

```sh
git clone https://github.com/nocstah/hyprflip.git
cd hyprflip
```

## Native pairs with the supplied installer

This is also the core-installation step for a **first-time** container setup.
Use a terminal inside the intended Hyprland session:

```sh
make test
python3 scripts/install.py --dry-run
python3 scripts/install.py
hyprctl hyprflip status
hyprctl configerrors
```

`make test` builds the core and runs its C++ test. The dry run checks the built
library, current configuration and shortcut conflicts without changing files.
The installer writes:

| Path | Purpose |
| --- | --- |
| `~/.local/lib/hyprflip/hyprflip.so` | Core plugin |
| `~/.config/hypr/hyprflip.lua` | Plugin declaration, motion settings and M/P/F/U/Escape bindings |
| `~/.config/hypr/hyprland.lua` | Adds `require("hypr.hyprflip")` |

It adds the Hyprflip module search path before importing modules, so a plain
Hyprland Lua configuration does not need Omarchy’s Lua bootstrap.
It respects `XDG_CONFIG_HOME` for the configuration directory, backs up replaced
files, preserves customized core settings and native pairs, and validates the
reload. A failed installation restores the previous files. An existing
container installation must use the [container updater](#container-updates).

Hold **Super+Ctrl+Alt**: M marks the front, P pairs the focused app as the back,
F flips and U ungroups. Both windows must share a workspace and both be tiled or
both floating. Leave fullscreen while creating the pair.

## hyprpm

This alternative installs the core for **native pairs**. Its manifest maps the
supported Hyprland commit to a matching implementation commit.

```sh
hyprpm add https://github.com/nocstah/hyprflip
hyprpm enable hyprflip
hyprpm reload
```

Add the settings and bindings from [examples/hyprflip.lua](../examples/hyprflip.lua)
to your Lua configuration, **omitting its `hl.plugin.load(...)` line**: hyprpm
owns the library load. Run `hyprpm reload` at session startup, following the
[Hyprland plugin documentation](https://wiki.hypr.land/Plugins/Using-Plugins/).
Do not also run the supplied core installer against a hyprpm-managed instance.

The build command and pin are supplied; end-to-end hyprpm installation is not
part of the recorded desktop validation. The first-time container procedure
below uses the supplied installer and its documented library paths. A stock hy3
installation through hyprpm does not contain Hyprflip's bridge.

## Manual core loading

For custom configuration layouts:

```sh
make
hyprctl plugin load "$PWD/build/hyprflip.so"
hyprctl hyprflip status
```

Adapt [examples/hyprflip.lua](../examples/hyprflip.lua) to your permanent library
path and load that module after your other desktop configuration. This explicit
IPC load lasts for the current session unless the configuration also declares
it. Copy a plugin to its permanent location **before** loading it; do not rebuild
or overwrite a library file while that same file is mapped into Hyprland.

## Experimental multi-app cards

The current bridge uses ABI **6** and hy3 **hl0.56.0.1**, commit
`42b7ed8fd9aefd3f36e5f617afd5071245c67853`. `scripts/build-containers` fetches and
checks that revision, then builds the provider and the matching Hyprflip core.
It does not install libraries or modify the desktop.

```sh
./scripts/build-containers
```

The outputs are:

- `build/containers/core/hyprflip.so`
- `build/containers/provider/upstream/libhy3.so`

### Try the disposable demo

```sh
python3 tests/nested_session.py --directory /tmp/hf-demo --containers
```

Use a fresh short directory for each session. Click inside the nested desktop,
then press **F8** to flip between its real terminal apps. Its front face lists
the other demo bindings. These F-key bindings belong only to this test session.
Stop the launcher with **Ctrl+C**; closing only its output window can leave the
nested compositor running. The launcher does not install anything on the parent
desktop. See [container acceptance checks](CONTAINERS.md#build-and-try-in-isolation)
for automated workflows.

### First-time activation

This procedure starts with the **current core installed through the supplied
installer above**, built from this same checkout. That core already includes
the provider API; it gains containers when the matching provider is loaded.
For an existing container installation, skip to [updates](#container-updates).

Start with an empty **workspace 8**, which the example reserves for hy3. Existing
workspaces retain their current layouts. Check H/V/E/O with Super+Ctrl+Alt for
conflicts using `hyprctl -j binds` and adjust the example if necessary. Separate
any native tiled groups on workspace 8 while it still uses its original layout.

There must not be another stock or experimental hy3 loaded, and the destination
provider file must not be a currently loaded library. If hy3 is already managed
by another setup, migrate that setup explicitly instead of loading a second copy.
The workspace example and core paths below assume the supplied installer.

Back up the main configuration and install the new provider and trial module:

```sh
hyprflip_config_root="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
hyprflip_state_root="${XDG_STATE_HOME:-$HOME/.local/state}/hyprflip"
mkdir -p "$hyprflip_state_root"
hyprflip_backup="$(mktemp -d "$hyprflip_state_root/first-container-XXXXXX")"
cp "$hyprflip_config_root/hyprland.lua" "$hyprflip_backup/hyprland.lua"
install -Dm755 build/containers/provider/upstream/libhy3.so \
  "$HOME/.local/lib/hyprflip/containers/libhy3.so"
install -m644 examples/containers-trial.lua \
  "$hyprflip_config_root/hyprflip-containers.lua"
```

At the end of your main `hyprland.lua`, after other layout and keybinding modules,
keep each of these lines **once**, in this order:

```lua
require("hypr.hyprflip")
require("hypr.hyprflip-containers")
```

The first line was added by the core installer. Reload and check:

```sh
hyprctl reload
hyprctl configerrors
hyprctl hyprflip status
```

Configuration errors should be empty. Status should report
`"container_provider": true` and `"container_max_panes": 3`.
Both `hyprflip` and `hy3` should appear in `hyprctl -j plugin list`.
The example enables hy3 on workspace 8 and adds H/V/E/O to the core bindings.
On that workspace, M/P now create container cards for tiled apps.

<a id="add-the-omarchy-menus"></a>
### Add the guided menus

The default is `HYPRFLIP_MENU=auto`. Each invocation checks for a responding
Omarchy shell, then installed **Fuzzel → Rofi → Wofi**, in that order. An
installed but stopped Omarchy shell does not prevent fallback. If the native
menu becomes unavailable while opening, the helper tries the portable picker;
pressing Escape cancels instead of opening another menu.

On a desktop without Omarchy, install one picker along with Python, libnotify
and GLib. For example, on Arch Linux:

```sh
sudo pacman -S fuzzel python libnotify glib2
```

Rofi must include Wayland support. Pickers retain their own theme configuration;
Hyprflip supplies plain app labels and handles selections by row identity.
A notification daemon provides launch progress and its Cancel action. Missing
notification support does not undo a completed card operation; feedback can
fall back to a Hyprland notification.

After the provider check succeeds, install the guided helper:

```sh
python3 scripts/install-setup.py --dry-run
python3 scripts/install-setup.py
```

It installs `setup.py`, `workflow.py`, `control.py` and `shortcuts.py` in
`~/.local/lib/hyprflip/`, plus `hyprflip-setup.lua` and
`hyprflip-preferences.lua` and `hyprflip-shortcuts.lua` in `~/.config/hypr/`.
It adds the setup `require` after the other bindings,
checks O/C/L/K/Space for conflicts, backs up changed files and validates reload.
It does not replace or unload compositor libraries.

- **Super+Ctrl+Alt+O:** create a card from an ungrouped app, or unfold/fold one.
- **Super+Ctrl+Alt+C:** edit a side, choose a transition or manage saved cards.
- **Super+Ctrl+Alt+L:** search and open a saved card.
- **Super+Ctrl+Alt+K:** find and reveal an app across open cards.
- **Super+Ctrl+Alt+Space:** hold to peek; release to return.

Move your separate app windows to workspace 8, focus the desired front and use O
for the [Gmail / WhatsApp + Telegram walkthrough](../README.md#make-your-first-card).
The picker can also bring apps from other normal workspaces. Custom desktops can
use the [direct commands and Lua API](CONTAINERS.md#interaction) without this helper.

Check detection or choose a picker explicitly:

```sh
python3 ~/.local/lib/hyprflip/setup.py --check-menu
HYPRFLIP_MENU=wofi python3 ~/.local/lib/hyprflip/setup.py --cards
```

Allowed values are `auto`, `omarchy`, `fuzzel`, `rofi` and `wofi`. A forced
backend reports an error when missing instead of silently choosing another.
To make a preference persistent, add `hl.env("HYPRFLIP_MENU", "rofi")` to your
Hyprland Lua configuration and reload. With `auto`, C/L prefer OmaCards when
its panel is available, then the native Omarchy menu, then a portable picker.
`--legacy` bypasses the OmaCards panel while retaining automatic menu detection.
`--backend-only` needs no shell or picker; install one to use its menu commands.

Add `--mouse-flip` to both installer commands to opt into
**Super+Ctrl+Alt+middle-click**. It checks the chord, installs
`hyprflip-mouse.lua`, and preserves that choice on later helper updates.
See [finding apps and mouse controls](FIND_APPS.md).

If Omachill is in use, install its
[Hyprflip adapter](TRANSITIONS.md#chill-mode) before using cards with Auto Chill.
The adapter targets Omachill 1.2.0 and is applied separately; the helper installer
does not patch it. The supplied workflow does not require Hyprglass or a shader
plugin.

### Add the OmaCards panel

After installing the guided helper, install the companion from its public repository:

```sh
omarchy plugin add https://github.com/nocstah/omacards.git --enable --yes
```

Click the cards icon in the bar. **Settings** contains Motion and Keyboard
shortcuts; **Float card / Tile card** changes the whole card's mode. Under a saved
card, **Manage → Workspace…** chooses a fixed destination or the current workspace.
Saving a card remembers its floating mode, apps and pane arrangement.

The `--yes` option accepts Omarchy's plugin-installation prompt. The panel uses
the same helper and saved library as the native menus. It does not install or
replace compositor libraries. See [OmaCards](https://github.com/nocstah/omacards)
for the panel's requirements, controls and removal instructions.

### Enable all normal workspaces

In your installed `hyprflip-containers.lua`, change:

```lua
local trial_workspace = nil
```

Keep the container module after saved layout overrides, then reload. It selects
hy3 for existing and future normal workspaces; special scratchpads retain
dwindle. **Before switching**, unpair any tiled native pairs while those
workspaces still use dwindle. Recreate them as containers afterward. Existing
hy3 cards can stay in place. Existing floating pairs keep their native grouping;
new floating cards can contain multiple apps per face.

### Move cards with normal shortcuts

The optional navigation module replaces the corresponding Omarchy movement
bindings so an entire card moves together:

```sh
install -m644 examples/containers-navigation.lua \
  "${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprflip-navigation.lua"
```

Load it after your normal keybindings and the container module:

```lua
require("hypr.hyprflip-navigation")
```

Reload once. Super+Shift+1…0 moves and follows the card;
Super+Shift+Alt+1…0 moves silently; Super+Shift+arrows reorders the card.
Destinations must be numbered hy3 workspaces, so all-workspace mode is useful
here. Ordinary windows retain ordinary workspace movement. This module does not
add drag bindings or special-workspace movement. Floating cards already move
and resize as a unit using the desktop's ordinary mouse bindings.

## Update

### Native updates

From a supplied-installer checkout with native pairs only:

Ungroup floating cards first with **Super+Ctrl+Alt+U**; their apps stay open.
The core-only installer preserves native pairs, while rebuilding floating or
tiled multi-app cards requires the matching core/provider updater below.

```sh
git pull --ff-only
make test
python3 scripts/install.py --dry-run
python3 scripts/install.py
```

Customized core settings and native pairs are preserved. For hyprpm, use
`hyprpm update` followed by `hyprpm reload` instead of the supplied installer.

### Container updates

Use the dedicated updater for an already-enabled container setup using the
paths above. Unlock the desktop first; restoring the arrangement requires focus:

```sh
git pull --ff-only
./scripts/build-containers
python3 scripts/update-containers.py --dry-run
python3 scripts/update-containers.py
python3 scripts/install-setup.py --dry-run
python3 scripts/install-setup.py
```

The updater backs up both libraries, settles turns, unloads the core before the
provider, updates both and reconstructs cards. It preserves membership, pane
order, split proportions, remembered focus, visible face and folded state.
Floating cards also retain their mode and outer frame.
The surrounding tiling layout can reflow. No applications are launched or closed.
A failed load attempts to restore the previous libraries and arrangements.

Keep Hyprglass loaded during this sequence; do not replace other compositor
plugins concurrently. Leave fullscreen and dismiss screensavers covering card
workspaces first. With active Chill-managed cards, the Omachill adapter must be
installed. The dry run checks these preconditions.

Backups are under `~/.local/state/hyprflip/container-update-*`. Same-session
recovery records use live window addresses and cannot recreate a card after a
compositor restart; use the [saved-card library](SAVED_CARDS.md) for that.
The guided helper's backups live under `guided-setup-*` in the state directory.

Update an installed public OmaCards checkout separately:

```sh
omarchy plugin update io.github.nocstah.omacards
```

If Omarchy keeps showing old controls after a plugin update, close the panel
and run `omarchy restart shell` while the desktop is unlocked. This reloads the
shell interface; app windows and Hyprflip cards remain in Hyprland.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Plugin reports an ABI/version mismatch | Compare `hyprctl version` with the headers and compiler used to build. Rebuild both experimental libraries together. |
| `Unknown request` from `hyprctl hyprflip status` | The core is not loaded. Check `hyprctl -j plugin list` and the library path; use `hyprpm reload` for a hyprpm installation. |
| O asks for a card or does nothing on an ordinary window | Install the guided helper after enabling the provider, and confirm that workspace uses hy3. F6/F7/F8 are only for the nested demo. |
| C/L/K/Space do not work | Check helper installation, `hyprctl -j binds`, `hyprctl configerrors`, and `python3 ~/.local/lib/hyprflip/setup.py --check-menu`. Install one supported picker if no shell is running. |
| An additional pane or unfold is refused | Check the three-app-per-face limit and application minimum sizes. Enlarge the card or change the split direction. |
| A saved app does not launch into the expected window | Use **Manage saved cards → Review apps and launchers**. Web apps need a matching installed desktop entry; a general browser launcher may open a different window. |
| A card vanished after closing an app | Closing the only app on a face dissolves the card. L can reopen its saved definition. |
| A flip switches instantly | Read `last_fallback` in status; check disabled animations, popups, fullscreen, geometry changes or unavailable surface buffers. |
| A manual unload followed by reload does not reload the core | Hyprland 0.56.2 caches configured plugin declarations. Use an explicit load of the installed path. |

An existing native group can be reattached without rearranging it:

```sh
hyprctl hyprflip adopt 0xFRONT_ADDRESS 0xBACK_ADDRESS
```

Use current addresses from `hyprctl -j clients`. Only a valid two-member native
group can be adopted; old addresses from another session are not valid.

For a bug report, include the Hyprland version, plugin/provider build, layout,
other loaded plugins and reproduction steps. See [Contributing](../CONTRIBUTING.md)
and [validation limits](../TESTING.md).

## Remove or disable

### Native pairs

Remove `require("hypr.hyprflip")` from the main configuration and reload. If the
core remains loaded, unload its installed path explicitly:

```sh
hyprctl plugin unload "$HOME/.local/lib/hyprflip/hyprflip.so"
```

Native windows remain in ordinary groups. For a hyprpm installation, use
`hyprpm disable hyprflip` and `hyprpm reload` instead.

### Experimental containers

Ungroup cards with **Super+Ctrl+Alt+U** first, leaving their apps open. Remove the
setup/navigation/trial/mouse `require` lines from the main configuration and restore
your ordinary workspace layouts and movement bindings. Keep the core declaration
if you want to return to native pairs. Keep unrelated plugins, including
Hyprglass, loaded during this change.

To disable both experimental libraries, remove their declarations, then unload
the core **before** the provider if they are still loaded:

```sh
hyprctl plugin unload "$HOME/.local/lib/hyprflip/hyprflip.so"
hyprctl plugin unload "$HOME/.local/lib/hyprflip/containers/libhy3.so"
hyprctl reload
```

Check `hyprctl configerrors` and `hyprctl -j plugin list`. Unload alone is not
persistent while the configuration still declares the libraries. Saved
arrangements remain in `~/.local/state/hyprflip/cards.json` until you remove them.

### OmaCards settings

Rerun `python3 scripts/install-setup.py` after updating this checkout to install
`shortcuts.py` and the Lua shortcut registry. The installer preserves existing
Hyprflip configuration values and saved shortcut preferences, backs up changed
files, reloads the configuration and verifies card membership. It does not
replace compositor libraries. OmaCards exposes motion and keybindings under
Settings; saved-card workspace preferences are under Manage → Workspace.
