# Changelog

## 0.3.0-rc.14 — 2026-11-09

- hy3 is retired. Cards are built by the core alone, tiled on Omarchy's
  default dwindle layout or floating; the hy3 integration, its provider
  build, updater and container trial are gone, and `status` no longer reports
  `hy3_provider`. Cards from the hy3 provider must be ungrouped
  (Super+Ctrl+Alt+U) before updating; [the install guide](docs/INSTALL.md)
  explains the switch.
- Attaching and releasing apps have default keys again: Super+Ctrl+Alt+H adds
  the marked app beside the focused pane, V below it, and E takes the focused
  app out of its card. They are set by the guided setup module and can be
  changed in OmaCards like the other shortcuts.
- Releasing a pane keeps the focus where it was, instead of moving it to the
  card's first app.
- Moving a pane to the other face keeps the proportions of the panes it leaves
  and joins, gives the moved app an even share, and turns the card to show it.
- Replacing an app in a tiled card trades the two apps' tiles, so the incoming
  app takes the outgoing one's place at the same size, and the outgoing app
  gets the incoming one's old tile. A replacement whose outgoing app cannot fit
  the incoming tile is refused before anything moves.
- Reopening a card's missing apps tries the card's present box first, keeping
  its id, and rebuilds the whole card only when the apps do not fit.
- Every nested test suite runs on dwindle with the core alone.

## 0.3.0-rc.13 — 2026-11-09

- Opening a saved card that is already open on another workspace brings it to
  the workspace you are on, instead of sending you to it. A card saved for a
  workspace of its own still goes there. Saved-card rows say so: “Bring here
  from workspace 1”, or “Open on this workspace”.
- Opening a saved card that was saved floating, and is open as a tile, floats
  it again at a size that fits its apps. A tile in half a 14" screen is too
  narrow for ChatGPT beside Claude Desktop.
- Reopening a card's missing apps rebuilds the whole card in one quiet
  `restore`, as opening a saved card does since 0.3.0-rc.12, instead of
  attaching each app inside the card's present box. That failed with “This
  split is too small for the applications” whenever the box was too small for
  the apps it should hold. Needs a core with `card_ungroup`; older cores keep
  the earlier path.
- Bridge ABI 7 and helper protocol 1 are unchanged.

## 0.3.0-rc.12 — 2026-11-08

- Saved cards open in one step at a size that fits their apps. Opening one
  from the panel, the menus or `control.py` used to build it pane by pane
  inside the front app's tile, so a floating card failed whenever that tile
  was narrower than one app's minimum size, however big the finished card
  would be: a terminal in a third of a 14" screen could not take ChatGPT,
  which needs 480 px. The helper now sends the whole card in one quiet
  `restore`, as unattended opening already did, when the core has
  `card_ungroup`.
- A floating card that has to grow to fit its apps grows on its screen: it is
  moved back from an edge it would cross, along the side it grew. A card that
  fits as given stays exactly where it was asked to be, as an update puts it
  back, on whichever monitor that is.
- Refusals name the app and the sizes. A restore that cannot fit says, for
  example, “Claude needs at least 600 px, so this card would have to be
  1818 px wide, and the screen has 1512. Put fewer apps side by side, or give
  Claude a bigger share.”; mark and pair say which window's place is too small.
  Messages use the app's name from its class, never a window title. A refusal
  for any other limit keeps the general wording. A card that cannot be made
  leaves its apps open where they were.
- Bridge ABI 7 and helper protocol 1 are unchanged.

## 0.3.0-rc.11 — 2026-11-03

- Swap a window or card into a tile with the real open animation.
  `card <id or address> hold` keeps a still picture of what is leaving under
  every window, `card <id or address> reveal [speed]` gives what arrives the
  user's open animation, faster or slower by `speed`, and `card <id or address>
  leave` plays the close animation. All three go in one `hyprctl --batch` with
  the moves, and nothing else moves, takes the focus or moves the pointer.
  `status` carries `"reveal": true`. See
  [swap with an animation](docs/SCRIPTING.md#swap-with-an-animation).
- Take a card or pair apart by its id, shown or parked: `card <id> ungroup`.
  It refuses while one of the card's windows is fullscreen, and `status`
  carries `"card_ungroup": true`. A card ungrouped on screen re-tiles its
  place, so a program that wants the layout kept parks the card first and
  ungroups it there.
- Scripted calls no longer refuse for input elsewhere. `card <id> workspace …
  silent`, `card <id> ungroup` and `restore quiet …` go ahead while the screen
  is locked or a button is held on another window (`card <id> ungroup` does so
  from the start). They still refuse for a grab, a drag-and-drop, a locked or
  confined pointer, a button pressed on one of the card's windows, or while one
  of those windows is moved or resized, a move the app asks for included
  (dragging a GTK header bar). Their busy refusals still start with
  `Finish the active grab or drag`.
- `card …` and `restore quiet …` sent with hyprctl no longer show a
  notification, desktop or Hyprland's own, a bare `restore quiet` included: the
  program that sent them reads the reply. A refused plain restore or Lua call
  still notifies.
- `control.py unattended` opens a saved definition as a card, and saves a live
  card by its id, for programs that build cards while the user works
  elsewhere. It asks nothing, notifies nothing and prints one JSON line. It
  never switches the workspace or moves the pointer, and when one of its apps
  takes the keyboard, it gives the keyboard back to the caller's `focus` where
  it can. Its store is the caller's own and never keeps a window title. See
  [open and save cards unattended](docs/SCRIPTING.md#open-and-save-cards-unattended).
- Saved cards leave hidden cards alone. A card another program parked on a
  special workspace is no longer shown as open, gone to, revealed or filled in
  with missing apps. An app it holds is never offered, and opening names it
  (“… is held by a hidden card”) instead of taking it.
- Updating the core leaves hidden cards as separate windows on their special
  workspace and says how many; the program that parked them rebuilds them.
  When the new core refuses to rebuild one card, its apps stay as separate
  windows and the other cards are still kept. Before, that refusal aborted the
  whole update, since Hyprland 0.56's hyprctl exits 7 on it. When Hyprland
  cannot be reached, the update is still rolled back and the recovery file
  kept.
- An update leaves the keyboard, the pointer and what each monitor shows as
  they were. It rebuilds cards quietly, so the last one no longer takes the
  keyboard and shows its workspace. Unloading the core takes the keyboard from
  most apps of a multi-app face, and it now goes back to that app once the cards
  are rebuilt, before any tile is corrected; on an app the card no longer shows,
  it stays on the shown side. If it ends up otherwise, or Hyprland did not say,
  the installer prints a line saying so.
- Every card is rebuilt before any tile is corrected, so two tiled cards alone on
  a workspace, with `dwindle:default_split_ratio` unset, no longer end up with one
  squeezed to a sliver. Putting a tiled card
  back in its tile no longer warps the pointer. It shows the card's workspace and
  moves the focus to its monitor only for those steps: the workspace each monitor
  showed, an open special workspace, the focused monitor and the keyboard come
  back afterwards, also with the keyboard on another monitor, on nothing or in a
  special workspace. The steps act only while the card has the keyboard, so a focus
  that moves meanwhile stops them and keeps the keyboard, and the card's size comes
  back only once it is in its corner, as a resize from elsewhere squeezes another
  tile.
- A tiled card stays where the reload left it, no other tile is rearranged and the
  installer prints a line saying so, if it does not take the keyboard, while any
  monitor shows a named workspace, which a focus could not show again, or with the
  keyboard in a special workspace open over it and `input:special_fallthrough` on.
  While a window on its workspace is fullscreen or maximized, that window stays so
  and the tile is left as the rebuild made it, also after that ends. A rollback
  still restores plainly and corrects no tile, since an older core refuses quiet
  restores, so the last card rebuilt gets the keyboard and shows its workspace,
  and a tile the reload moved stays moved. With two more tiles on a workspace,
  tiles can still end up elsewhere and at other sizes: see `TESTING.md`.
- A card the new core refuses to rebuild no longer shows a notification: the
  installer prints why, and `bootstrap.py` reports how many it could not keep,
  how many hidden cards it left, how many tiles it could not check or return and
  whether the keyboard or what a monitor shows is not as it was.

## 0.3.0-rc.10 — 2026-11-01

- Drive a card by its id without taking the focus: `card <id> show
  <front|back>`, `card <id> flip` and `card <id> workspace <workspace>
  [silent]`. A native card can now move to named and special workspaces, so a
  program can park it out of sight; Find and drag-to-add already leave such
  cards out. `restore quiet` builds a card and leaves the focus where it is,
  and `status` names each card's workspace. See
  [driving cards from other programs](docs/SCRIPTING.md).
- A card turned while the focus is elsewhere gets its resting opacity and dim
  back when the turn ends.

## 0.3.0-rc.9 — 2026-10-17

- Keep window titles off command lines. The Omarchy menu receives its rows
  as a command-line argument, which other local users can read from `/proc`,
  so app pickers there no longer include window titles: every candidate
  window's title was exposed, not just the chosen one's. Rows show the app,
  workspace and status, and two windows of the same app are numbered.
  Fuzzel, Rofi and Wofi read rows on stdin and still show titles. Set
  `HYPRFLIP_MENU_TITLES=1` to show titles in the Omarchy menu on a computer
  only you use.
- Opening a saved card now completes an open card that still holds part of
  it, instead of failing with “… is already open but unavailable”. With Gmail
  and Telegram open as a card and WhatsApp closed, opening the saved card
  goes to that card and reopens WhatsApp in its slot, as Reopen missing apps
  does. Apps must still be on their saved sides; a fullscreen card, or an app
  held by a different card, is left alone as before.

## 0.3.0-rc.8 — 2026-10-15

- Fix Hyprland aborting after Super+G on a floating card. Toggling the group
  could empty the card's group while the card still held it, and the next
  focus read its missing current window (`out_of_range`).
- Fix a face with several apps losing all but one of them during a flip. The
  glass backdrop a pane turns over covered the whole card, so the last pane
  drawn frosted over the others: they vanished into a stationary blur and
  popped back when the turn ended. The backdrop now stays inside each pane's
  own area. It is also only applied to windows Hyprglass actually frosts
  (tagged `hyprglass_enabled`, or its global `enabled`); Hyprglass decorates
  every window, so plain translucent apps had been getting it too.

## 0.3.0-rc.7 — 2026-10-09

- Keep `gaps_in` around tiled cards on dwindle. Hyprland only adds inner gaps
  when a tiled window receives an empty visual slot, and card panes always pass
  one, so a card touched a neighbouring card and sat 5 px from a normal window
  with `gaps_in = 5`. Panes now inset a tiled card's slot by `gaps_in` (including
  workspace rules) on every edge away from the work area, as Hyprland does.
- Turn every face at its focused opacity, undimmed. Focus moves to the other
  face only when a turn ends, so with `inactive_opacity` below 1 or
  `dim_inactive` the incoming face turned translucent and dimmed, then faded
  up afterwards.
- Keep glass faces frosted while they flip. Hyprflip suspends Hyprglass during
  a turn, so a translucent glass face showed the sharp wallpaper through it.
  In the flip transitions, faces that had Hyprglass now turn over Hyprland's
  cached xray blur: one texture lookup per covered pixel, with no extra blur
  pass or buffer. Other windows and the snapshot transitions are unchanged.
## 0.3.0-rc.6 — 2026-10-07

- Keep a tiled card in its tile through an update. While a card is briefly
  separate tiles, dwindle (notably with `smart_split`) can reflow the
  workspace, so a card beside a neighbour came back stacked under it. The
  installer now corrects a restored tiled card with dwindle's own
  `togglesplit`, `swapsplit` and a resize, keeping only steps that bring it
  back. The card description and correction live in `scripts/card_restore.py`.
## 0.3.0-rc.5 — 2026-10-06

- Find app reveals apps in a fullscreen card instead of refusing. Native cards
  and pairs turn while fullscreen; hy3 cards, which cannot, leave fullscreen
  first. An unrelated fullscreen app on the workspace still asks you to leave
  it, since focusing past it would end it anyway.
- `bootstrap.py` records the installed source commit in
  `$XDG_STATE_HOME/hyprflip/installed-commit`, and the helper snapshot reports
  it as `installed_commit`, so OmaCards can offer updates.
- Updating no longer means ungrouping cards. `scripts/install.py` records open
  dwindle and floating cards, reloads the core and rebuilds them with the same
  apps, sides, proportions, focus and floating frame, through a new core
  `restore` action. hy3 cards keep their dedicated updater.
- `scripts/bootstrap.py` checks prerequisites (Hyprland 0.56.2 and matching
  headers, a supported Hyprland commit, CMake, Ninja, pkg-config, C++, Lua 5.4,
  GLES), naming the `pacman` packages for anything missing, then builds,
  self-tests and runs both installers. `--json` streams one event per step for
  panels.
## 0.3.0-rc.4 — 2026-10-05

- Super+J on a native card face with several apps flips them between beside
  and stacked, as it did for hy3 cards; elsewhere it is still Omarchy's
  split toggle. New `layout toggle` action and Lua `face_size()`; guided
  setup installs the binding.
- Keep the background blurred behind translucent cards during slide, fade,
  dissolve and portal. Those transitions draw a snapshot of the card, which
  had turned blur off for every pane; the snapshot's leader now keeps its
  blur and gives Hyprland a matte shaped like the turning card.
- Fix a floating card turning behind another floating window. Focusing a card
  raised only the focused pane's own target, so a card could stay under other
  windows, and a flip passed behind them. Focus and face changes now raise
  every app of the card together, focused app last.
- A native card moved onto a chilled workspace joins Chill like a newly opened
  app instead of being refused, through Omachill's `chillmode.join` (1.5.0, or
  adapter v4). hy3 cards and engines without `join` keep the refusal.
- Omachill 1.4.0 includes the card integration (adapter v1–v3), so updating
  Omachill no longer drops it; `prepare-source.py` is only needed for older
  engines.
## 0.3.0-rc.3 — 2026-10-02

- Show Hyprflip's messages as desktop notifications through `notify-send`
  (mako on Omarchy), with a newer message replacing an older one, instead of
  Hyprland's notification bar. `desktop_notifications = false` restores the
  bar, which is also the fallback when `notify-send` is missing.
- Omachill adapter v3: toggling Chill on a workspace with a fullscreen native
  card leaves fullscreen and chills the card instead of refusing. An hy3 card
  keeps its fullscreen and Chill explains why. v3 upgrades v1 and v2 engines.
- Fullscreen a whole card on dwindle and floating cards. Fullscreening any
  app (or maximizing it) fills the screen with every app on the visible face,
  meeting at a thin divider in the accent color (`accent_color`, else the
  active border color) with no gaps, borders or rounding between them; the
  card frame hides until you leave. The pointer focuses whichever app it is
  over. Flip, peek, unfold and
  face layout changes keep working, and moving focus between the card's apps
  keeps the card fullscreen under every `misc:on_focus_under_fullscreen`
  setting. Leaving fullscreen restores the card's tile or floating frame.
  hy3 cards keep the previous single-app fullscreen. Status reports
  `fullscreen_focus` and `card_dividers`.
- Add, replace, release and drag apps into a fullscreen native card without
  leaving fullscreen. `hyprflip mark 0x<address>` marks an app without
  focusing it, since focusing an outside app would end fullscreen.
- `fullscreen_divider` (0–16 px, default 2; 0 lets apps touch) and
  `divider_color` (`#RRGGBB`; empty follows `accent_color`, then the active
  border) style the line between fullscreen apps.
- A `fullscreen` action (Lua `hyprflip.fullscreen()`) fills the screen with
  the whole card without telling the apps they are fullscreen, so browsers
  keep their toolbars. It follows flips and focus; the action or the normal
  fullscreen toggle leaves. Status reports each card's `fullscreen`.
- Chill mode can take a workspace that holds native dwindle cards. The card
  floats in place as one chilled window at the chilled size, both faces
  sharing that frame, and tiles back into its slot. New `chill_blocked`,
  `card_box` and `card_place` Lua functions support Omachill adapter v2
  (`integrations/omachill/prepare-source.py`, which also upgrades a v1
  engine). `protects_workspace` is unchanged, so engines with only the v1
  guard still keep card workspaces tiled. hy3 cards and fullscreen cards stay
  out of Chill.
- Helper and panel: add a `fullscreen` panel action (targeted like `floating`,
  native dwindle/floating cards only) and a `divider` action (`width` 0–16,
  optional `color` `#RRGGBB` or empty to follow the accent). Snapshots report
  `capabilities.fullscreen`/`capabilities.divider`, `fullscreen_divider`,
  `divider_color`, and per-card `fullscreen` and `native`. The divider width
  and color persist in `$XDG_STATE_HOME/hyprflip` with rollback on failure and
  are reapplied at login by `preferences.lua`.
- Guided setup binds **Super+Ctrl+Alt+Return** to fullscreen the whole card
  (on cores that support it), checks it for conflicts, and lists it in the
  shortcut editor as **Fullscreen whole card**.
- Keep editing a fullscreen native card from the helper: flip, unfold, layout,
  add, replace, remove and Find app no longer ask you to leave fullscreen when
  the only fullscreen app on the workspace belongs to that card. Added apps are
  marked by address (`hyprflip mark 0x…`) so focus never leaves the card.
  hy3 cards, unrelated fullscreen apps, ungrouping and reopening missing apps
  still require leaving fullscreen first.
- Add an optional accent ring around every card, in Classic tabs and Card
  frame appearances. `accent_ring` turns it on; `accent_color` (`#RRGGBB`) sets
  its color. The focused card's ring is fully opaque and other cards' rings are
  quieter. The helper persists both, reapplies them at login, and adds an
  `accent` panel action plus `control.py accent-color` so a shell can follow
  its theme. Status reports `card_rings` for tests.
- Recognise Chromium web apps in saved cards after the default browser
  changes. A card saved with Brave's `brave-gmail.com__-Default` now reopens
  with Helium's or Chrome's `chrome-gmail.com__-Default` instead of waiting
  for a window that never appears. The site and browser profile must still
  match.

## 0.3.0-rc.2 — 2026-09-23

- Let native dwindle and floating cards allocate unequal space to unfolded
  faces according to application minimum and maximum sizes. Keep balanced
  faces when they fit, try both directions, and retain the saved pane layouts.
  Gmail / WhatsApp + Telegram now unfolds in the existing 1440×900 laptop tile.
- Add real GTK regressions at 1440×900 and 1280×800, with Classic and Card frame
  appearance, exact fold restoration and refusal when neither direction fits.
- Validate the published installers with a fresh home, stock Omarchy 4.0.4
  configuration and real shell menus: no hy3, no shortcut conflicts, and a
  saved three-app card cold-launches correctly. This uses existing host
  packages; a fresh OS install and independent-user beta remain outstanding.
- Add a reproducible isolated installer test, beta checklist and invitation
  draft for default-dwindle users.

## 0.3.0-rc.1 — 2026-09-23

Preview release for Hyprland 0.56.2, focused on Omarchy's default dwindle layout.

- Create, edit, unfold and reopen multi-app cards directly on dwindle using
  native Hyprland groups. The core alone supplies the card backend; the hy3
  provider remains optional for hy3 workspaces. Preserve the existing M/P
  two-window pairing path and use O for editable cards.
- Add a core-only dwindle demo with `tests/nested_session.py --native-cards`.
- Check tiled app size limits after the incoming tile releases its space.
  Saved cards can now group apps whose minimum sizes fit the completed card
  but exceed the smaller tile available during construction.
- Restore saved native-card pane proportions through the card layout API;
  ordinary dwindle resizing operates on the card's outer tile.
- Support up to five apps per face with the matching ABI 7 core and hy3 provider.
  Preserve pane proportions when adding or removing apps, and unfold large
  horizontal faces above one another to retain their width.
- Add temporary Front/Back drop targets for dragging outside windows into
  containers, with slot previews, Escape cancellation and size-limit rollback.
- Offer Classic tabs or an experimental shared card frame with Flip/Fold
  controls. OmaCards saves appearance and Desktop/Compact spacing preferences;
  compact gaps leave 12 logical pixels between card apps.
- Preserve application minimum sizes during upgrades by reconstructing cards
  on a temporary workspace, then restoring their original workspace and size.
  Failed or interrupted reconstruction rolls back with recovery metadata.
- Run guided creation, editing and saved-card workflows without Omarchy. Prefer
  its responding shell; otherwise detect Fuzzel, Rofi or Wofi, with an explicit
  override and clear feedback when no picker is installed.
- Make Lua module imports work in plain Hyprland and use portable notification
  flags for saved-card launch progress and cancellation.
- Find apps across open cards with Super+Ctrl+Alt+K: show the workspace and face,
  reveal hidden panes, and focus the exact app without changing membership.
- Offer an optional Super+Ctrl+Alt+middle-click flip binding through
  `install-setup.py --mouse-flip`; existing drag bindings remain available.

## 0.2.0 — 2026-09-22

Two-face workflows and the first public [OmaCards](https://github.com/nocstah/omacards)
companion. Hyprland remains pinned to 0.56.2; the optional hy3 bridge uses ABI 6.

- Tiled or floating cards with up to three live apps on each face. Floating cards
  move and resize as one unit and retain membership through edits and transitions.
- Unfold/fold, hold to peek, seven transitions, previews and saved motion preferences.
- Add, remove, replace, reorder or transfer any pane; import apps from other workspaces.
- Save named arrangements, launch missing apps, reuse existing windows, and repair
  missing panes. Assign a destination workspace and remember floating mode.
- OmaCards adds a native Omarchy bar library, two-face editor and Settings for
  motion and keyboard shortcuts. Shortcut recording temporarily inhibits desktop
  bindings; changes persist, check conflicts and roll back on failure.
- Share one guarded workflow backend between the panel and native menus.
- Preserve cards during matching core/provider upgrades. Refuse an update while
  the desktop is locked, before touching compositor libraries or arrangements.

Build from source against the running compositor's matching headers and compiler.
See [installation and upgrade paths](docs/INSTALL.md), [tested behavior](TESTING.md),
and [compatibility limits](README.md#compatibility-and-limits).

## 0.1.1 — 2026-09-20

First public release, for Hyprland 0.56.2.

- Pair two real windows as the front and back of a rotating card.
- Reuse native groups for layout, focus, movement, resizing and fullscreen.
- Synchronize the perspective turn to the pair's output render cycle.
- Use a reversible 420 ms turn with gentle departure and landing, restrained perspective and filtered texture detail.
- Provide Lua and IPC actions, optional shortcuts, reduced motion and clean unpairing.
- Handle window closure, external group changes, input interruption and plugin unloading.
- Support tested Wayland/XWayland pairs, fractional scaling, rotated outputs and Hyprglass 1.0 coexistence.
- Preserve native pairs through installer upgrades; retain recovery metadata until restoration succeeds.
- Include a nested compositor test harness and automated core/installer checks.

Pairs are not persisted across compositor restarts. See [TESTING.md](TESTING.md) for the tested configurations and limits.
