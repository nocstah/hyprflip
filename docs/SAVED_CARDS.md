# Saved cards and hold to peek

The optional Omarchy card menu now saves arrangements for later reuse. A card
still has two faces, with one to three apps in a row or column on each face.

## Save and open

1. Focus any app in your card and press **Super+Ctrl+Alt+C**.
2. Choose **Save card…** and enter a name, such as **Communications**.
3. On the destination workspace, press **Super+Ctrl+Alt+C**, choose
   **Open saved card…**, then choose your saved card.
4. Choose **Open on this workspace**, review the apps and launchers, then
   **Open card here**. Choose **Tile and open card** if selected open apps are
   floating or in Chill mode.

Open reuses available apps, including those on other workspaces, and launches
missing ones using installed desktop entries. If a launcher cannot be identified,
choose it from the installed app list. Select a missing app's review row to change
its launcher. Successful choices are remembered. If the complete card is already
running, **Go to open card** takes you to its current workspace without rebuilding it.

**Restore from open apps…** retains the manual workflow: pick replacements for
missing apps, review windows, then **Restore card here**. It never launches apps.

C also works on an ungrouped app or an empty workspace. It offers saved cards
there; an ungrouped app also has **Create a card**. O retains its immediate
unfold/fold and guided-creation behavior.

Saved arrangements remember both faces, their split directions and relative
pane sizes, the last focused pane on each face, and the visible face. Restoration
finishes folded. It uses the available tile on the destination workspace;
application size limits still apply. It does not restore the old monitor,
workspace number, or absolute screen coordinates.

App classes and window titles help match open windows. A unique exact title
match is preferred; a unique app class can still match after its title changes.
Ambiguous matches open an app chooser. The review shows reused windows and
missing apps' launchers; select a row to change the choice. Windows already in
another card or group are unavailable. Open does not launch a duplicate to bypass
that restriction.

All choices happen before apps launch, move or tile. While waiting for missing
apps, click the native **Opening…** notification to cancel. Opening C again
also cancels the pending request. The wait lasts up to 20 seconds; a successful
launcher exit alone does not count as an open window. Unrelated focus/workspace
navigation cancels setup. Apps opened so far remain open after cancellation or
failure. No windows move or tile until every required app is identified.

A failed restore dissolves only its newly created card,
returns imported apps to their original workspaces, and restores selected
floating apps' positions and Chill tags when those windows are still available.

Saving an existing name asks before replacing it. The saved-card submenu also
has **Delete saved card**, with confirmation. Deleting the saved definition
keeps running apps and cards open.

Saved cards open only when requested. They do not reconstruct a session at login,
restore browser tabs or documents, or save custom shell commands. A web app needs
an installed launcher that opens that web app. Multiple new windows with the same
class and changed titles may need **Restore from open apps…** to distinguish them.

### Storage

Definitions live in `$XDG_STATE_HOME/hyprflip/cards.json`, normally
`~/.local/state/hyprflip/cards.json`. It is versioned JSON written atomically
with mode `0600`. It contains app classes, titles, optional installed desktop-entry
IDs and layout preferences, without
window addresses, PIDs, screenshots or executable commands. Names are data,
never filenames. Concurrent updates check the selected definition and preserve
other saved cards. An unreadable or unsupported file is not overwritten.

The first schema supports 100 definitions and names up to 64 characters. Back
up the JSON file to keep your arrangements across machines or reinstalls.
Existing version-1 definitions remain readable; their launchers are inferred or
chosen on first use. The helper follows XDG desktop-entry precedence and hidden
overrides, rechecks launcher contents before starting, and delegates execution
to `gio launch`. It does not parse `Exec` as a shell command. See the
[desktop-entry specification](https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html)
and [GIO launch semantics](https://docs.gtk.org/gio/method.AppInfo.launch.html).

## Hold to peek

Hold **Super+Ctrl+Alt+Space** to reveal the opposite face. Release **Space**
to return. The modifiers can be released first. Peek uses the chosen transition;
releasing early reverses the same motion smoothly. Instant and disabled
animations switch immediately in both directions.

Clicking, scrolling, touching or typing commits to the side you are using.
An explicit focus change wins. Workspace changes, configuration reloads,
fullscreen, popups, closing a member and monitor removal cancel the pending
return. A stalled output settles the animation. Releasing Space afterward never
undoes one of those actions. An unfolded card explains that both faces are
already visible.

The binding is installed by `scripts/install-setup.py`, which checks for
conflicts before changing files. There is one press binding: the core observes
the physical key release so it works even if the modifier chord has changed.
Callbacks resolve the current plugin at invocation time, making unload safe.

For custom bindings, call `hl.plugin.hyprflip.peek()`. External tools can use
`hyprctl hyprflip peek` followed by `hyprctl hyprflip 'peek end'`, or the Lua
`end_peek()` function. IPC callers must send the explicit end action because
they have no physical trigger key. Status exposes `peek_available` and `peeking`.
Peek also works with native two-window pairs; saved multi-app arrangements use
the optional hy3 container provider.

## Update an existing container installation

Build the matching libraries with `./scripts/build-containers`, then run
`python scripts/update-containers.py` and `python scripts/install-setup.py`.
The updater retains existing cards and the setup installer retains user
configuration and saved definitions, backing up replaced files. See
[the container installation guide](CONTAINERS.md) for prerequisites and recovery.
