# Saved cards and hold to peek

The optional Omarchy card menu now saves arrangements for later reuse. A card
still has two faces, with one to three apps in a row or column on each face.

## Save and open

1. Focus any app in your card and press **Super+Ctrl+Alt+C**.
2. Choose **Save card…** and enter a name, such as **Communications**.
3. On the destination workspace, press **Super+Ctrl+Alt+L**.
4. Type part of the saved name, select it and press Enter. It opens directly.

The launcher shows **Open · Workspace X** for a running card; selecting that
entry switches to it. A saved workspace assignment also moves the running card
to that workspace. Otherwise **Open here**
reuses matching apps and launches missing ones. The row indicates when apps will
be brought from other workspaces or tiled. There is no second confirmation.
An empty library offers **Save this card…** when a card is focused.

Open reuses available apps, including those on other workspaces, and launches
missing ones using installed desktop entries. If a launcher cannot be identified,
choose it from the installed app list. Ambiguous window matches still need an
explicit choice. Successful launcher choices are remembered. Matching floating
apps, including Chill windows, are fitted into the saved arrangement. Cards
saved as floating reopen as one movable, resizable card; other cards are tiled.

For manual control, choose **Manage saved cards…**, select a name, then use
**Review apps and launchers…** before opening it. Select a missing app's review
row to change its launcher. **Restore from open apps…** retains the manual
workflow: pick replacements for missing apps, review windows, then **Restore
card here**. It never launches apps. These options appear when the complete card
is not already open.

C also works on an ungrouped app or an empty workspace. It offers saved cards
there; an ungrouped app also has **Create a card**. O retains its immediate
unfold/fold and guided-creation behavior. **Open saved card…** in C opens the
same launcher as L.

## Update and manage

Focus your card, press **Super+Ctrl+Alt+C**, and choose **Manage card…**:

- **Update saved card** remembers the current apps, split directions, proportions,
  focused panes, visible face and floating mode. It preserves remembered
  launchers and the assigned workspace. A unique
  matching saved setup is selected automatically, including after moving a pane
  between faces. If multiple saved variants match, or you added/removed apps,
  choose which saved name to update. There is no naming or replacement prompt.
- **Rename…** changes the saved name; an existing name is never overwritten.
- **Duplicate…** copies the saved definition under a new name. It does not launch
  another set of app windows or capture unsaved layout changes.
- **Workspace…** chooses where the card opens. Select **Current workspace** to
  open wherever you are, or **Always use a workspace…** and enter its number.
  For example, assign **Comms** to **3** to open it on workspace 3 from anywhere.
  The library shows this destination. An already open card moves there instead
  of creating a duplicate. The destination needs the hy3 layout.
- **Delete saved card** removes the definition after confirmation and keeps
  running apps and cards open.

Rename, Duplicate, Workspace and Delete are also available through **L → Manage saved
cards…** while a card is closed. Updates are explicit; editing a live layout does
not silently change its saved definition. Ordinary **Save card…** still asks
before replacing an existing name.
This includes swapping/reordering panes and replacing an app. After a
replacement, **Manage card…** may ask which saved name to update because the
apps no longer match the old setup. Until you update it, opening that saved
card still uses its original apps and layout.

## Reopen missing apps

If an app closes while both sides of a saved card still have at least one app,
focus the surviving card and choose **C → Reopen missing apps**. For example,
close Telegram from Gmail ↔ WhatsApp + Telegram, then reopen it beside WhatsApp.
The card stays in place; its identity, visible face, remembered focus on each
side and unfolded state remain intact. No additional confirmation is needed.

A uniquely matching saved setup is selected automatically. If several match,
choose a name. Surviving apps must still be in their original face and order;
indistinguishable browser windows with changed titles are not guessed. Save the
complete arrangement before closing apps. The feature needs matching ABI 5 or later
core/provider builds; older providers keep their existing menu.

The helper reuses eligible open apps, including floating apps on other
workspaces, and launches only missing apps. It never takes an app from another
card or native group. Apps return to their saved positions. Existing multi-app
faces keep their current split direction and the relative sizes of surviving
panes. Each missing pane gets its saved share of the face; the remaining space
is divided proportionally among survivors. A side reduced to one app regains
its saved split direction. Unaffected faces retain their layout.

Cancellation, stale-window checks, workspace protection and launch timeouts
are shared with ordinary opening. The card and layout are checked again before
attachment. A failed repair removes only panes it added, restores the affected
splits, and returns imported/floating apps when those windows remain available.
Launched apps stay open after failure or cancellation.

If closing an app empties an entire side, Hyprflip dissolves the card as before.
Use **Super+Ctrl+Alt+L** to open the saved setup again in that case. Reopen does
not restore browser tabs, documents, or application-internal session state.

## Opening behavior

Saved arrangements remember both faces, their split directions and relative
pane sizes, the last focused pane on each face, the visible face and whether the
card floats. Restoration finishes folded. By default it opens on the current
workspace; an explicit assignment uses that workspace instead. Tiled cards use
the available tile, and application size limits still apply. Saved definitions
do not restore an old monitor or absolute screen coordinates.

App classes and window titles help match open windows. A unique exact title
match is preferred; a unique app class can still match after its title changes.
Ambiguous matches open an app chooser. The review shows reused windows and
missing apps' launchers; select a row to change the choice. Windows already in
another card or group are unavailable. Open does not launch a duplicate to bypass
that restriction.

All choices happen before apps launch, move or tile. While waiting for missing
apps, click the native **Opening…** notification to cancel. Opening C or L again
also cancels the pending request. The wait lasts up to 20 seconds; a successful
launcher exit alone does not count as an open window. Unrelated focus/workspace
navigation cancels setup. Apps opened so far remain open after cancellation or
failure. No windows move or tile until every required app is identified.

A failed restore dissolves only its newly created card,
returns imported apps to their original workspaces, and restores selected
floating apps' positions and Chill tags when those windows are still available.

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
other saved cards. Rename checks both names and changes them in one atomic
write. An unreadable or unsupported file is not overwritten.

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

Unlock the desktop, build the matching libraries with `./scripts/build-containers`, then run
`python scripts/update-containers.py` and `python scripts/install-setup.py`.
The updater retains existing cards and the setup installer retains user
configuration and saved definitions, backing up replaced files. See
[the container installation guide](CONTAINERS.md) for prerequisites and recovery.
