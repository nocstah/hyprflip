# Install and update Hyprflip

Hyprflip currently targets **Hyprland 0.56.2**. The core plugin builds
multi-app cards itself on **dwindle**, Omarchy's default layout, and as floating
cards; no other layout plugin is needed. **Omarchy is optional.**
Guided menus and saved cards prefer its running shell and automatically use
Fuzzel, Rofi or Wofi when it is unavailable. The core also exposes commands for
custom configurations.

These instructions describe the repository's current implementation. The
quickest path is `python3 scripts/bootstrap.py`, which checks prerequisites,
builds, and runs both installers ([updates](#update) use the same command).
The sections below describe each step.

## Requirements

The optional [OmaCards companion](https://github.com/nocstah/omacards) uses the
shared helper installed by `scripts/install-setup.py` and provides a native bar panel.
For two-window pairs without guided card creation, use `--backend-only` to install
that helper and motion preferences without adding the guided card shortcuts.
See [the panel interface](PANEL_API.md) for its behavior and compatibility.

| Component | Requirements |
| --- | --- |
| Core | Hyprland 0.56.2 and matching development headers; matching C++26-capable compiler; CMake 3.25+; Ninja; pkg-config; Lua 5.4; GLESv2 |
| Supplied installer | Python 3, `hyprctl`, a running Hyprland session and an existing `~/.config/hypr/hyprland.lua` |
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

## Core installation with the supplied installer

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
reload. A failed installation restores the previous files.
Open dwindle and floating cards stay open through a core update: the installer
records each card, reloads the core and rebuilds it with the same apps, sides,
proportions, focus and floating frame. The keyboard, the pointer and what each
monitor shows stay as they were. A keyboard that was on a card's app goes back
to that app; on an app the rebuilt card does not show, it stays on the card's
shown side. If you move to another workspace or monitor during the update, the
keyboard stays with you. If the keyboard or what a monitor shows is not as it
was at the end, or Hyprland did not say, the installer prints a line saying so.

Once every card is rebuilt, a tiled card that the reload moved goes back to its
tile where dwindle's split controls can put it there. It holds the keyboard,
shows its workspace if that was hidden and moves the focus to its monitor, only
for those steps; you may see that workspace for a moment. Afterwards the
workspace each monitor showed, an open special workspace, the focused monitor and
the keyboard come back. The steps act only while the card has the keyboard: if
you move the focus to another window meanwhile they stop, the keyboard stays with
you, and the card stays out of its tile. A move to an empty workspace during those
steps is undone, with the card still out.

A card stays where the reload left it, and the installer prints a line saying so,
if it does not take the keyboard, while any monitor shows a named workspace,
which a focus could not show again, or with the keyboard in a special workspace
open over it and `input:special_fallthrough` on. While a window on its workspace
is fullscreen or maximized, that window stays so, the tile is left alone and the
installer says so. The tile stays as the rebuild made it after that ends, which
can be another place. Run again before it ends, the update has no saved tile to
compare and says nothing.

Two tiled cards alone on a workspace come back in their tiles, with
`dwindle:default_split_ratio` unset. At another ratio one can still be squeezed,
with the printed line. A card second in its split, beside one neighbour, whose
split was moved by hand comes back at half the split, with the line. With two more
tiles on the workspace, tiles can end up in other places and at other sizes, one of
them very small, and the update prints the line for a card that is not back. If
the pointer rests on another monitor than the keyboard, the focus can end on the
keyboard's monitor until the pointer moves. If its workspace was hidden or on
another monitor and `cursor:warp_on_change_workspace` is 2, Hyprland warps the
pointer as those steps visit it. Hyprland's `previous` workspace afterwards is
the one those steps visited last.

A card the new core refuses to rebuild, for example because its apps closed
meanwhile, is left as separate open windows, the installer prints why, and the
other cards are still kept. A card that another program parked on a special
workspace is left there as separate windows too; the installer says how many,
and the program that parked it rebuilds it. If `hyprctl` cannot reach Hyprland,
the installer rolls the update back and keeps its recovery file,
`~/.local/lib/hyprflip/hyprflip.upgrade.json`; the next update in the same
Hyprland session rebuilds the pairs and cards from it when no card or pair is
open. A rollback rebuilds cards plainly and corrects no tile, so the last one
gets the keyboard and shows its workspace, and a tile the reload moved stays
moved. Leave fullscreen first: the installer refuses a fullscreen card. It also
refuses to run while cards from the retired hy3 provider are open, before
changing files or unloading the core; see
[leaving the hy3 provider](#leaving-the-retired-hy3-provider).

Hold **Super+Ctrl+Alt**: M marks the front, P pairs the focused app as the back,
F flips and U ungroups. Both windows must share a workspace and both be tiled or
both floating. Leave fullscreen while creating the pair.

## Dwindle multi-app cards

Build and install the current core as above, then add the guided helper:

```sh
python3 scripts/install-setup.py --dry-run
python3 scripts/install-setup.py
```

Keep `general.layout` and your workspace layout on **dwindle**. Focus an
ungrouped app, press **Super+Ctrl+Alt+O**, and choose apps for the back.
**C** edits the card, **L** opens saved cards, and **O** unfolds or folds it.
All these keys use Super+Ctrl+Alt. Up to five apps fit on each face, subject
to application size limits. The same helper also serves OmaCards.

Unfolding keeps the two faces balanced when possible, but gives a face more
room when its apps require it. This preserves your layouts within each face.
If neither side-by-side nor stacked faces fit, the card stays folded.
See the [beta checklist](BETA.md) for a short default-Omarchy trial.

The core manages one native outer group, while dwindle places that group as
one tile. No layout plugin or workspace-layout change is needed. Existing
two-window M/P pairs remain available; ungroup one before creating its editable
replacement with O. [Multi-app cards](CONTAINERS.md) describes the card model,
editing and direct commands.

### Try it in a disposable desktop

Try it without changing your desktop configuration:

```sh
make test
python3 tests/nested_session.py --directory /tmp/hf-demo --native-cards
```

Click inside the demo and press F8. Stop its launcher with Ctrl+C;
closing only its output window can leave the nested compositor running. The
launcher does not install anything on the parent desktop. Use a fresh short
directory for each session.

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

`scripts/install-setup.py`, run after the core as shown above, installs the
helper. It installs `setup.py`, `workflow.py`, `control.py` and `shortcuts.py` in
`~/.local/lib/hyprflip/`, plus `hyprflip-setup.lua` and
`hyprflip-preferences.lua` and `hyprflip-shortcuts.lua` in `~/.config/hypr/`.
It adds the setup `require` after the other bindings,
checks O/C/L/K/Space (and Return on cores with card fullscreen) for conflicts, backs up changed files and validates reload.
It does not replace or unload compositor libraries.

- **Super+Ctrl+Alt+O:** create a card from an ungrouped app, or unfold/fold one.
- **Super+Ctrl+Alt+C:** edit a side, choose a transition or manage saved cards.
- **Super+Ctrl+Alt+L:** search and open a saved card.
- **Super+Ctrl+Alt+K:** find and reveal an app across open cards.
- **Super+Ctrl+Alt+Space:** hold to peek; release to return.
- **Super+Ctrl+Alt+Return:** fullscreen the whole dwindle or floating card; press
  again to leave. Installed and conflict-checked only with a core that supports it.

Use a normal dwindle workspace, focus the desired front and use O
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

App pickers in the Omarchy menu list apps by name, workspace and status, and
number two windows of the same app, without their window titles. The menu
receives its rows as a command-line argument, which other users on the same
computer can read while it opens. Fuzzel, Rofi and Wofi read rows privately
and show titles. On a computer only you use, add
`hl.env("HYPRFLIP_MENU_TITLES", "1")` to show titles in the Omarchy menu too.
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

### Move cards with normal shortcuts

The optional navigation module replaces the corresponding Omarchy movement
bindings so an entire card moves together:

```sh
install -m644 examples/containers-navigation.lua \
  "${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprflip-navigation.lua"
```

Load it after your normal keybindings and Hyprflip modules:

```lua
require("hypr.hyprflip-navigation")
```

Reload once. Super+Shift+1…0 moves and follows the card;
Super+Shift+Alt+1…0 moves silently; Super+Shift+arrows reorders the card.
Destinations must be numbered normal workspaces; the card moves as one group.
Ordinary windows retain ordinary workspace movement. This module does not
add drag bindings or special-workspace movement. Floating cards already move
and resize as a unit using the desktop's ordinary mouse bindings.

## hyprpm

This alternative installs the core for **native pairs and dwindle multi-app
cards**. Its manifest maps the supported Hyprland commit to the matching
0.3.0 preview implementation.

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
For guided creation, editing and saved cards, install the helper from the
matching source revision using `python3 scripts/install-setup.py` after the
core is loaded. The helper does not replace or unload compositor libraries.

The build command and pin are supplied; end-to-end hyprpm installation is not
part of the recorded desktop validation.

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

## Update

From a supplied-installer checkout:

```sh
git pull --ff-only
python3 scripts/bootstrap.py
```

`bootstrap.py` checks the prerequisites (naming the packages to install if any
are missing), builds and self-tests, then runs `scripts/install.py` and
`scripts/install-setup.py`. `--check` only checks; `--json` reports each step as
one JSON line for panels such as OmaCards. The installers can also be run by
hand as before.

Open dwindle and floating cards, native pairs and customized core settings are
kept. A card parked on a special workspace stays there as separate windows for
the program that parked it, and a card the new core refuses to rebuild stays
as separate windows; the step's detail says how many of each, how many tiles it
could not check or return and whether the keyboard or what a monitor shows is not
as it was ([core installation](#core-installation-with-the-supplied-installer)
has the details). Leave fullscreen first. For hyprpm, use
`hyprpm update` followed by `hyprpm reload` instead of the supplied installer.

### OmaCards

Update an installed public OmaCards checkout separately:

```sh
omarchy plugin update io.github.nocstah.omacards
```

If Omarchy keeps showing old controls after a plugin update, close the panel
and run `omarchy restart shell` while the desktop is unlocked. This reloads the
shell interface; app windows and Hyprflip cards remain in Hyprland.

<a id="container-updates"></a>
### Leaving the retired hy3 provider

Earlier previews could build cards through an optional hy3 provider
(`~/.local/lib/hyprflip/containers/libhy3.so`, loaded by
`hyprflip-containers.lua`). That provider has been removed and the current core
does not use it. If your desktop still has it:

1. Save any card you want to keep with **C → Save card…** (or update its saved
   definition), then focus each open hy3 card and press **Super+Ctrl+Alt+U**.
   Its apps stay open. The installer refuses to update while such cards are open.
2. Update as above with `python3 scripts/bootstrap.py`. This replaces the old
   core, which knew about hy3, before hy3 itself goes away.
3. Remove `require("hypr.hyprflip-containers")` from your main `hyprland.lua`,
   and any hy3 `layout` setting or workspace rule of your own, so the workspaces
   return to dwindle. Keep the `hypr.hyprflip` line and any setup, navigation
   or mouse modules.
4. Reload with `hyprctl reload`. If `hyprctl -j plugin list` still shows `hy3`,
   unload it explicitly:
   `hyprctl plugin unload "$HOME/.local/lib/hyprflip/containers/libhy3.so"`.
   Keep Hyprglass loaded while hy3 unloads.
5. Recreate cards with **Super+Ctrl+Alt+O**, or open saved ones with
   **Super+Ctrl+Alt+L**; they now open as dwindle cards.

Afterwards you can delete `~/.config/hypr/hyprflip-containers.lua`,
`~/.local/lib/hyprflip/containers/` and old `container-update-*` backups under
`~/.local/state/hyprflip/`. Saved cards in `cards.json` are kept.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Plugin reports an ABI/version mismatch | Compare `hyprctl version` with the headers and compiler used to build. Rebuild the core against the matching headers. |
| `Unknown request` from `hyprctl hyprflip status` | The core is not loaded. Check `hyprctl -j plugin list` and the library path; use `hyprpm reload` for a hyprpm installation. |
| O asks for a card or does nothing on an ordinary window | Install the guided helper after the current core, and keep the workspace on dwindle. F8 is only for the nested demo. |
| C/L/K/Space do not work | Check helper installation, `hyprctl -j binds`, `hyprctl configerrors`, and `python3 ~/.local/lib/hyprflip/setup.py --check-menu`. Install one supported picker if no shell is running. |
| An additional pane or unfold is refused | Check the five-app-per-face limit and application minimum sizes. Enlarge the card or change the split direction. |
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

For a bug report, include the Hyprland version, plugin build, layout,
other loaded plugins and reproduction steps. See [Contributing](../CONTRIBUTING.md)
and [validation limits](../TESTING.md).

## Remove or disable

### Everything

From the checkout you installed from, inside the Hyprland session:

```sh
python3 scripts/uninstall.py --dry-run   # what it would remove
python3 scripts/uninstall.py             # asks first; --yes does not
```

It removes what `scripts/bootstrap.py`, `install.py` and `install-setup.py` put
in place:
- **hyprland.lua.** The installers' `require` lines and the comments they wrote
  above them come out. So does the module search path block, unless another
  module still needs it.
- **The plugin.** Hyprland reloads without it, and open cards come apart into
  ordinary windows with their apps still open. A card parked on a special
  workspace stops it first: the program that parked it has to bring it back.
- **Files.** `~/.local/lib/hyprflip` goes. The Lua modules and the installers'
  backups move to `~/.local/state/hyprflip/uninstalled-<time>/`.

If Hyprland reports a new configuration error, everything is put back as it
was. Saved cards and preferences stay in `~/.local/state/hyprflip`; `--purge`
removes that folder too. Lines you added yourself, such as a `require` of your
own module, stay. For a hyprpm installation, use `hyprpm disable hyprflip`
instead.

The sections below remove one part by hand.

### Core

Remove `require("hypr.hyprflip")` from the main configuration and reload. If the
core remains loaded, unload its installed path explicitly:

```sh
hyprctl plugin unload "$HOME/.local/lib/hyprflip/hyprflip.so"
```

Native windows remain in ordinary groups. For a hyprpm installation, use
`hyprpm disable hyprflip` and `hyprpm reload` instead.

### Cards and guided helper

Ungroup cards with **Super+Ctrl+Alt+U** first, leaving their apps open. Remove the
setup/navigation/mouse `require` lines from the main configuration, reload, and
restore your ordinary movement bindings if you replaced them. Keep the core
declaration if you want to keep native pairs. Unloading the core with cards
still open dissolves them into ordinary windows.

Check `hyprctl configerrors` and `hyprctl -j plugin list`. Unload alone is not
persistent while the configuration still declares the library. Saved
arrangements remain in `~/.local/state/hyprflip/cards.json` until you remove them.

### OmaCards settings

Rerun `python3 scripts/install-setup.py` after updating this checkout to install
`shortcuts.py` and the Lua shortcut registry. The installer preserves existing
Hyprflip configuration values and saved shortcut preferences, backs up changed
files, reloads the configuration and verifies card membership. It does not
replace compositor libraries. OmaCards exposes motion and keybindings under
Settings; saved-card workspace preferences are under Manage → Workspace.
