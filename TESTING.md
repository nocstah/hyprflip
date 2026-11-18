# Validation

## Card owners; release checks for 0.3.0-rc.27 (2026-11-18)

A program that keeps its own cards can now mark them: `card <id> owner
<name>`, or `owner <name>` in the restore that builds the card. `status`, the
helper's snapshot and `update-result.json` report the owner, and the helper's
`open` takes `owner`. OmaRelay asked for this so that OmaCards can say
"Managed by OmaRelay" and, before an edit, what OmaRelay does with it. The
mark is never a lock. `scripts/release.py` makes a release in one command.

Checked on feat/card-owner at 4918d99. The next commit (416d339) adds only
`scripts/release.py`, its tests and notes. All three CTest checks and all 518
Python unit tests pass (506 at rc.26). Twelve tests are new:
- `tests/unattended_test.py` (3): an open marks its card in the same restore;
  a core without marks opens it unmarked and says so; an invalid owner, and
  an owner with `tiles`, are refused;
- `tests/install_test.py` (3): an update keeps each card's owner; a core
  without marks keeps the card unmarked, through a rollback too; cards left
  apart name their owner in the result and the message;
- `tests/card_restore_test.py` (2): the owner comes after the faces and before
  the cover, and is read back or stripped;
- `tests/panel_control_test.py` (1): snapshot cards say which program manages
  them;
- `tests/release_test.py` (3): the release commit, its tag and the hyprpm pin;
  a dry run that changes nothing; and each refusal.

Each nested suite ran in its own fresh session (Hyprland 0.56.2, Aquamarine
0.15.1 with the render-node patch, `--notify-recorder`), and every launcher
exited cleanly:
- `tests/card_id_workflows.py`: all 15 checks pass. The two new ones cover
  `card <id> owner` (the mark stays through parking and turns, `-` clears it,
  and a malformed name or a plain pair is refused, all without taking the
  focus or moving the pointer) and a restore with `owner`, which marks the
  card it builds and refuses an owner before the faces, given twice, followed
  by a face, or malformed.
- `tests/install_cards.py`: all 66 checks pass. The parked card is marked
  `OmaRelay` before the update and is kept with that owner; the other cards
  stay unmarked.
- `tests/unattended_workflows.py`: all 14 pass. `capabilities` reports
  `card_owner`, and the open that binds parked apps passes
  `"owner": "OmaRelay"`; the card is marked in its one batch.
- `tests/restore_cover_workflows.py` 10, and 10 with `--hooks-off`;
  `tests/reveal_workflows.py` 19; `tests/cover_workflows.py` 15 with
  `--protocol`; `tests/uninstall_session.py` 3.
- `tests/key_suites.py` with Hyprglass: all seven suites pass (workflows 10,
  nearby 15, setup 7, edit 14, pane 12, switch 5, claim 5).
- Planted: a core whose restore drops the owner fails `card_id_workflows` at
  the restore check (`card(id)['owner'] == 'OmaRelay'`) after 6 passes; it
  passes 15 again once rebuilt from 4918d99. A helper that leaves the owner
  out of a card's description fails four unit tests.

OmaCards at its feat/owner-and-pin branch (88061f8), against this checkout:
`tests/render.py` passes with new checks on OmaRelay's card (Cards, Edit,
Ungroup's confirmation, Remove), another program's card (only "Managed by
Tiler", and "Tiler may build this card again"), and an unmarked one (nothing
said). Without the owner in the card's details, or without Ungroup's note,
it fails with that check's message. `tests/installer_test.py`,
`tests/pin_check.py`, `tests/release_tool_test.py` (5) and
`omarchy plugin validate .` pass. In a session started with
`--native-cards`, `tests/run-native.py --dwindle` passes 9 of 9 and
`tests/navigation-native.py` 5 of 5.

The release tools ran on throwaway clones of both repositories. Hyprflip's
made the release commit, the tag and the pin commit with the same files the
rc.25 and rc.26 releases changed by hand. OmaCards' `pin` then `release` did
the same against its rc.30 and rc.31 commits.

Not run: `tests/menu_workflows.py` and the other compositor suites, which
neither the mark nor the installer's handling of it reaches.

Released from a3cbd8a. The release commit changes only the changelog, the
README, the beta guide and this note.

## Parked cards through an update; release checks for 0.3.0-rc.26 (2026-11-18)

An update used to take every card OmaRelay had parked on a special workspace
apart. The core refused to build a card there, so the restore failed with
"Those apps no longer fit in one card". Now a quiet restore without a cover
builds such a card in place, unseen, and `scripts/install.py` keeps parked
cards. The installer also holds the card request lock for the update, marks it
in `updating`, writes `update-result.json`, and has the new core post
`hyprflip>>updated,<release>`. The snapshot gains `install_check` (from the
core's `loaded_file` and bootstrap's `installed-files.json`) and `has_cover`.

Checked on feat/park-updates at 5031715. All three CTest checks and all 506
Python unit tests pass (494 at rc.25). Twelve tests are new and three
rewritten:
- `tests/install_test.py`: the three tests that left parked cards out (restore
  and recovery, the dry run's count, a card parked while the update settles)
  now keep them. New: a parked fullscreen card stays separate windows, a
  parked card gets no tile correction, the marker, result and event (marker
  present and lock held at the unload, the result's `kept` and `apart`, one
  announcement, none after a refusal or a rollback), and an update that stops,
  changing nothing, while another program holds the request lock;
- `tests/install_check_test.py` (5): no record, the install as recorded, a
  helper copied over (a touch alone does not count), a file gone or added (a
  backup does not count), and a core loaded from elsewhere or from a copy
  since replaced;
- `tests/bootstrap_test.py` (1, and the parked summary cases): each installed
  file is recorded;
- `tests/panel_control_test.py` (2): `has_cover` while the card shows its own
  face, and `install_check` in the snapshot.

Each nested suite ran in its own fresh session (Hyprland 0.56.2, Aquamarine
0.15.1 with the render-node patch, `--notify-recorder`), and every launcher
exited cleanly:
- `tests/install_cards.py`: all 66 checks pass. Its parked check now has an
  update keep the card on `special:park` with the same faces and shown face,
  its apps grouped and unseen, no marker left, a result of `ok` with 3 kept
  and none apart, and exactly one `hyprflip>>updated,<release>` per update.
  A new check brings the kept card back to a workspace, finds it laid out as a
  card, and parks it again.
- Planted: with the old refusal put back (a parked card's apps not usable
  for a restore), the suite fails at the parked check after 59 passes. The
  installer prints "Keeping 3 open card(s) through this update, 1 of them
  parked out of sight", then "Could not keep a card; its apps stay open as
  separate windows: Those apps no longer fit in one card", the sentence that
  hid the cause before.
- `tests/restore_cover_workflows.py`: 10 checks, and 10 again with
  `--hooks-off` in a session started with `HYPRFLIP_CLOSE_HOOKS=0`.
- `tests/unattended_workflows.py` (14), `tests/card_id_workflows.py` (13),
  `tests/reveal_workflows.py` (19), `tests/cover_workflows.py` (15, with
  `--protocol`) and `tests/uninstall_session.py` (3, with its own home) all
  pass.
- `tests/key_suites.py` with Hyprglass: all seven suites pass (workflows 10,
  nearby 15, setup 7, edit 14, pane 12, switch 5, claim 5).

OmaCards at its feat/install-check branch (de320ae), against this checkout:
`tests/render.py` passes, with new checks for the Settings row (said only when
the core differs or files changed, naming them) and for **Add as new face…**
on a card of three faces and a cover. Each check fails when its condition is
removed. `tests/installer_test.py` and `omarchy plugin validate .` pass. In a
session started with `--native-cards`, `tests/run-native.py --dwindle`
passes 9 of 9 and `tests/navigation-native.py` 5 of 5.

OmaRelay's cards-nested at its main (ba851b3), run by the Agenttrail session
against its own build of 5031715 in a fresh nested session, passes 31 of 31
with cleanup complete. That includes its install case, which runs this
`scripts/install.py` with a covered card of one face and parked cards. After
the reload OmaRelay takes back each kept parked card by its members, under its
new id, instead of rebuilding it.

The OmaRelay session ran cards-nested from its cards/update-marker branch
(672424a, the helper half of the update hold) against its own clone of 5031715.
It passes 32 of 32. Its helper ticks every 200 ms while `scripts/install.py`
runs, logs that cards wait while the update runs and go on after it, and never
finds the core missing. The shown covered card of one face is kept, nothing is
rebuilt, and the result says `ok` with 2 kept and none apart. Before the
release tag, the result names the newest release the commit contains,
0.3.0-rc.25, as `installed-release` does.

Not run: the other compositor suites, which neither the core change (only
quiet restores of apps on one special workspace) nor the installer reaches.

Released from 725d907. No code changed after 5031715, the commit every check
above ran on; the release commit changes only the changelog, the README and
the beta guide.

## A covered card with one face of its own; release checks for 0.3.0-rc.25 (2026-11-18)

When a close would leave a card behind Herdr's window with one face of its
own, OmaRelay keeps that face under the cover. The core can now build that
shape in one `restore … cover <address>`, founded on the cover so that the
card takes the cover's tile. The helper keeps such definitions in a `one_face`
map of the caller's store, opens them under a cover or as tiles, and writes
them with `put`. An update keeps a covered card with one face of its own.

Checked on feat/one-face-cover at 1ca0ab4. All three CTest checks and all 494
Python unit tests pass (470 on 847e4b0). The 24 new ones are:
- `tests/saved_test.py` (10): the restore line with a cover, validate's
  fewest faces, the `one_face` map keeping the card of two faces as its
  fallback, the limit over both maps, a store without `one_face` written as
  before, an older helper's read and write, the flag view's token, a bad
  entry, the library, and the menu save's sentence;
- `tests/unattended_test.py` (9): an open under a cover in one batch from the
  cover's tile; the cover never bound or counted as open elsewhere, but counted
  as a face; `unavailable` without `restore_cover` or with a cover in use;
  `changed` under the lock; `needs_cover`; `tiles`; a save that needs the
  `one_face` view; `put`; the new request fields;
- `tests/install_test.py` (3 more): the old test that took such a card apart
  is replaced by four, in which an update keeps the cover and the face it
  showed, a recovery run builds it again, and a rollback to an older core
  leaves its apps open;
- `tests/edit_test.py` and `tests/panel_control_test.py` (1 each): no move to
  another face, and no Other side.

Each nested suite ran in its own fresh session (Hyprland 0.56.2, Aquamarine
0.15.1 with the render-node patch, `--notify-recorder`), and every launcher
exited cleanly:
- the new `tests/restore_cover_workflows.py`: all 10 checks pass, and again
  all 10 with `--hooks-off` in a session started with
  `HYPRFLIP_CLOSE_HOOKS=0`. They cover one face of its own built in one batch
  from a special workspace, with grim showing the cover's box unchanged and
  the keyboard and pointer where they were; flip and `card show 1`; the same
  beside a neighbour that has the keyboard; two faces of their own; each
  refusal's sentence; parking, which still takes the card apart, and a second
  restore that builds it again in the same tile; the face move refused with
  "This card has one face of its own."; key closes of the app and of the
  cover, both `dissolved`; and card frames on.
- Planted: with the card founded on face 0 instead of the cover, the suite
  fails at the neighbour check. The card took the neighbour's tile
  (`[12, 12, 628, 776]`) instead of the cover's (`[648, 14, 618, 772]`). The
  case with the cover alone on its workspace passes either way, so the
  neighbour case is the one that guards this. Rebuilt afterwards, the plugin
  was byte for byte the one tested above.
- `tests/install_cards.py`: all 65 checks pass. The covered-update check now
  also has a covered card with one face of its own keep its cover, on the face
  it showed.
- `tests/unattended_workflows.py`: 14 checks pass, one new. The helper puts
  a definition of one face, opens it under the working tile in one batch
  (the tile, the keyboard and the pointer stay), saves it only in the
  `one_face` view, and binds it as tiles without moving anything.
- `tests/cover_workflows.py` (15, with `--protocol`),
  `tests/close_reason_workflows.py` (15 with `--protocol`, all 72 status
  replies JSON; 4 with `--hooks-off`), `tests/multiface_workflows.py` (18),
  `tests/card_id_workflows.py` (13), `tests/dwindle_workflows.py` (7),
  `tests/floating_workflows.py` (10), `tests/switcher_workflows.py` (12),
  `tests/repair_workflows.py` (10), `tests/opening_workflows.py` (6) and
  `tests/uninstall_session.py` (3, with its own home) all pass.
- `tests/saved_workflows.py`: `--phase save` (1), then `--phase restore` (5)
  in a second session with the same `--state-dir`.
- `tests/key_suites.py` with Hyprglass: all seven suites pass (workflows 10,
  nearby 15, setup 7, edit 14, pane 12, switch 5, claim 5).

`tests/fullscreen_workflows.py` with `--protocol` passed 8 checks (the 7
recorded before, plus the pointer check that `--protocol` adds). It then failed
where it has failed since 79fdb37: at line 236, `KeyError: 'address'`, because
no window has the focus after an app leaves a fullscreen card.

OmaCards at its feat/one-face-cover branch (cf93694), against this checkout:
`tests/render.py` passes, with the new checks for a covered card's Showing
label and the Other side of a card with one face of its own.
`tests/installer_test.py` (6), `tests/pin_check.py` and
`omarchy plugin validate .` pass. In nested sessions started with
`--native-cards`, `tests/run-native.py --dwindle` passes 9 of 9,
`tests/navigation-native.py` 5 of 5 and `tests/shortcut-native.py` 1 of 1.

Not run: `tests/menu_workflows.py` (portable pickers; the Edit menu change is
covered by the unit tests) and the other compositor suites.


Rerun at cc2b719 for the release, each nested suite in its own fresh session
(Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch): `make test`
3/3, all 494 Python unit tests, `tests/restore_cover_workflows.py` 10/10 and
`tests/install_cards.py` 65/65. OmaCards' panel at its 0.2.0-rc.30 candidate
on this core: `tests/render.py` and `tests/installer_test.py` pass,
`tests/run-native.py --dwindle` 9 of 9 and `tests/navigation-native.py` 5 of 5.

## A module claims one of Hyprflip's keys; release checks for 0.3.0-rc.24 (2026-11-18)

Found on the pilot desktop: OmaRelay's card key module binds Super+Ctrl+Alt+O
itself. Every guided-setup install stopped there, first with "is assigned to
another action". With a `Hyprflip:` description it stopped instead at the check
after the reload ("The guided O shortcut did not register exactly once").

A module now claims the key in the global table `hyprflip_claimed_keys`.
Checked in a nested session (Hyprland 0.56.2) that `hyprctl repl` returns a
Lua string as it is, and that a global does not survive `hyprctl reload`. So a
claim lasts as long as its module is loaded.

All three CTest checks and all 470 Python unit tests pass. Eight of the tests
are new:
- `tests/shortcuts_test.py` (3): chords as `hl.bind` takes them, claims read
  only behind their header, and a claimed row with `owner` that the editor
  refuses to move or to put another action on.
- `tests/setup_install_test.py` (3): a claimed key installs and the summary
  names the owner. Hyprflip's key left beside the owner's after the reload puts
  everything back. An unclaimed foreign key still refuses.
- `tests/shortcuts_lua_test.py` (2): the shipped `examples/shortcuts.lua` in
  plain Lua, which leaves a claimed key unbound whatever its case and spacing,
  and refuses to configure an action onto it.

Taking out the pre-check's claim test, the after-check's owner test, or the
registry's claim test makes those tests fail.

In fresh nested sessions (Hyprland 0.56.2, Aquamarine 0.15.1 with the
render-node patch):
- The new `tests/claimed_key_workflows.py` passed all 5 checks, in a session
  with its own home. It covers a module that claims O after Hyprflip's modules,
  as OmaRelay's does, and one that claims it before them. It also covers the
  editor, an unclaimed key that still stops setup before it writes, and taking
  the module out. `tests/key_suites.py` runs it as `claim`.
- `tests/key_suites.py`: all seven suites pass (workflows 10, nearby 15,
  setup 7, edit 14, pane 12, switch 5, claim 5).
- `tests/uninstall_session.py`: all 3 checks pass.
- `scripts/install-setup.py --dry-run` against the pilot desktop, whose
  OmaRelay module now claims O on the 0.3.0-rc.23 registry, passes its checks
  and says "Super+Ctrl+Alt+O: left to OmaRelay, which claims it." It wrote
  nothing.
- OmaCards' panel at its 0.2.0-rc.29 candidate, on this guided setup:
  `tests/run-native.py --dwindle` passes 9 of 9 and `tests/navigation-native.py`
  5 of 5.

The plugin's code is unchanged from 0.3.0-rc.23, and so is CMakeLists.txt, so
the core's own nested suites were not rerun; see that release's checks below.

## Release checks for 0.3.0-rc.23 (2026-11-18)

0.3.0-rc.23 starts from feat/close-reason-six-faces (b77e29c: six faces,
close reasons and covers). It merges in the movement shortcuts (b563443) and
the check that a window opening beside a card stays outside it (8428c49). Only
CHANGELOG.md and TESTING.md overlapped. Each nested suite ran on the merge in a
fresh session, on Hyprland 0.56.2 with Aquamarine 0.15.1 and the render-node
patch:
- `make test`: all 3 CTest checks pass. All 462 Python unit tests pass.
- `tests/key_suites.py` with Hyprglass: all six suites pass. That is
  workflows 10, nearby 15, setup 7, edit 14, pane 12 and switch 5 checks.
- `tests/cover_workflows.py`, started with `--notify-recorder` and run with
  `--protocol`: all 15 of its checks pass, the drag check among them.
- `tests/close_reason_workflows.py` with `--protocol`: 15 checks pass, and all
  72 status replies parse as JSON.
- `tests/multiface_workflows.py`: 18 checks pass.
- `tests/outside_window_workflows.py`: 3 checks pass.
- `tests/install_cards.py`: all 65 checks pass.
- `tests/uninstall_session.py`: all 3 checks pass.
- Updating in place: a build directory configured and built at 0.3.0-rc.22,
  then reconfigured at the merge, builds against Lua 5.5.1, links
  `liblua.so.5.5` and passes all three CTest checks.
- OmaCards' panel at its 0.2.0-rc.28 candidate: `tests/run-native.py
  --dwindle` passes 9 of 9. `tests/navigation-native.py` passes 5 of 5,
  covering the offer, No thanks, Turn on and the Settings switch through this
  release's guided setup.

Not run on the merge: `tests/fullscreen_workflows.py`, which fails at line 236
(KeyError 'address') on 79fdb37 as well; the other compositor suites.

## Close reasons and six faces together (2026-11-17)

Both branches merged here. All three CTest checks and all 417 Python unit tests
pass. `close_reason_workflows.py` now reads `container_max_faces` 6, so its
last-face check closes an app on face 6 of a six-face card (face 5, faces 6),
and it gains two checks with both features together:
- closing by key the only app on face 5 of a six-face card reads face 4 of 6,
  `dissolved` true, since an uncovered card comes apart when a face empties;
- on a covered card at six faces (five of its own and the cover), the same close
  reads face 4 of 5, not dissolved, and the card keeps its other four faces and
  the cover.

Each nested suite ran in its own fresh session (Hyprland 0.56.2, Aquamarine with
the render-node patch, `--notify-recorder`) on the merged build:
- `close_reason_workflows.py` (15, with `--protocol`), 72 status replies all JSON;
- `close_reason_workflows.py --hooks-off` (4) in a session started with
  `HYPRFLIP_CLOSE_HOOKS=0`;
- `multiface_workflows.py` (18), `cover_workflows.py` (15, with `--protocol`),
  `card_id_workflows.py` (13), `switcher_workflows.py` (12),
  `unattended_workflows.py` (13), `dwindle_workflows.py` (7),
  `floating_workflows.py` (10);
- `saved_workflows.py`, `--phase save` (1) then `--phase restore` (5) in a
  second session with the same `--state-dir`;
- OmaRelay's `ovis.py cards-nested` (17, cleanup complete), run from its
  face-limit reader branch against this checkout.

`fullscreen_workflows.py` passed 7 checks and then failed where it fails on
79fdb37 (`KeyError: 'address'` at line 236), as recorded below.

## Why an app closed (2026-11-17)

All three CTest checks pass. `core` now also checks the close ledger on fake
times:
- a close request read as `requested` up to 120 s and a kill as `killed` up to
  10 s, then `own` with both hooks and `unknown` without;
- a live kill winning over a live close, and an expired kill leaving the close
  to decide;
- a repeated request restarting the clock, with the latest `via`;
- a close using its request up, and a pid of 0 or less stored as none;
- the 128 pending windows, dropping those asked longest ago, and requests past
  their time pruned;
- the 64 records and 10 minutes, with `oldest` and `next`;
- invalid UTF-8 replaced, text cut to 256 bytes at a code-point boundary, and
  the exact JSON of a record in a card, a cover and a window in no card.

`own_symbols` passes with the new `CloseReasons.cpp`, and `lua_library` passes.

All 411 Python unit tests pass. Three are new, in `tests/hyprctl_call_test.py`.
Through a stand-in `hyprctl` on PATH they check that:
- a JSON reply naming "Lua error" in a class parses;
- a plain `Lua error: boom` reply still raises;
- invalid UTF-8 inside a JSON string reads as U+FFFD.

Two of the three fail against the previous `Hyprctl.call`.

The new `tests/close_reason_workflows.py` passed all 13 of its checks in a fresh
nested session (Hyprland 0.56.2, Aquamarine with the render-node patch), started
with `--notify-recorder` and run with `--protocol` pointing to
`wlr-virtual-pointer-unstable-v1.xml`. Its keys are Super+F9
(`hl.dsp.window.close()`) and Super+F10 (`hl.dsp.window.kill()`), pressed with
wtype; the session resolves binds by key symbol, since wtype sends its own
keymap. The checks cover:
- the status at load: `close_reasons` true, both hooks in `watch`, a 16-digit
  instance, no records, and `fullscreen_focus` still true with the fullscreen
  hooks now found by their full names;
- a key close on face 2 of a 3-face card: `requested` by `key`, with the card,
  face, index, faces, pid, initial class, stable id and workspace;
- `hyprctl dispatch hl.dsp.window.close`: `requested` by `other`;
- an app quitting by itself and one killed from outside Hyprland (SIGKILL):
  `own`, the second taking the card apart (`dissolved`);
- a window in no card: no record when it quits by itself, `card` null when
  closed by key;
- a key kill of one of two windows of one `foot --server`: `killed` by `key`
  with the server's pid; the other window reads `own`;
- `hyprctl kill` and a click on a card app: `killed` by `click`;
- the cover closed by key: `cover` true, no face;
- the last app of a face of a 2-face card closed by key: `dissolved`, with the
  face it had;
- the last face of a card at `container_max_faces` (four on this branch);
- a class holding "Lua error", quotes, a backslash and a tab, read back exactly
  by the helper's `Hyprctl`;
- a plugin reload: the hooks install again, with a new instance and records
  from 1;
- all 57 status replies parsing as JSON.

Run with `--hooks-off`, in a fresh session whose Hyprland was started with
`HYPRFLIP_CLOSE_HOOKS=0`, it passed all 4 of its checks, which cover:
- `close_reasons` false and both hooks false in `watch`;
- a key close and an app quitting by itself read `unknown`;
- a key close of a window in no card leaves no record;
- a click kill still reads `killed` by `click`;
- every status reply parses.

These suites also passed against this core, each in its own fresh session
started with `--notify-recorder`:
- `cover_workflows.py` (15, with `--protocol`);
- `card_id_workflows.py` (13);
- `dwindle_workflows.py` (7).

`fullscreen_workflows.py` passed its first 7 checks and then failed where it
failed before (no window has the focus after an app leaves a fullscreen card,
`KeyError: 'address'`). It failed in the same place and the same way against a
build of 79fdb37, the commit this change starts from. So the fullscreen hooks,
now installed through `hookFunction`, are not the cause, and status reported
`fullscreen_focus` true in the new suite.

Not checked:
- aarch64 (omac), where no hook can install; only its stand-in,
  `HYPRFLIP_CLOSE_HOOKS=0`, was tried here;
- a sixth face: this branch keeps four faces, and the suite closes an app on
  the face at `container_max_faces`, so with six faces it checks face 6 of 6;
- XWayland apps, the trackpad close gesture, a taskbar's close and the group
  bar's middle-click, all of which go through the same hooked function;
- `kill -SEGV`: the suite kills from outside with SIGKILL instead, so that no
  core dump or crash notice reaches the desktop.

## Six faces (2026-11-17)

All three CTest checks and all 413 Python unit tests pass; five of the unit
tests are new:
- `saved_test.py`: the schema reads two to eight faces and refuses one and
  nine, `restore_line` writes a six-face line and refuses nine, and a store
  holding a six-face card reads;
- `unattended_test.py`: `keep` takes a closed app on face 5 of a six-face
  definition and refuses face 8, `capabilities` reports `max_faces` (6 from
  status, 2 when it is missing), and `open` refuses a seven-face recipe as
  `too_many_faces` with nothing launched or changed, and a three-face one on a
  core that does not say;
- `edit_test.py`: on a card with five faces and a cover, at a cap of six, the
  edit menu does not offer a new face, and `add_face` refuses naming the cover
  when one came while the menu was open.

Each nested suite ran in its own fresh session (Hyprland 0.56.2, Aquamarine
with the render-node patch, `--notify-recorder`):
- `multiface_workflows.py` (18): faces 5 and 6 by `attach face`, a seventh
  refused with "already has 6 faces", `show 5`/`show 6` and `show 7` refused
  "from 1 to 6", a six-face description round trip, and the slide case: with
  `duration_ms=400` and `transition="slide"` a six-face card of solid-colour
  apps turns by `face 4` (three faces on), flips 4 to 5, 5 to 6 and 6 round to 1,
  `face 6` from face 1 (one face back), `face 3` from face 6 and `face 6` from
  face 3 (three faces each), each with no fallback, ending on its face, with
  Hyprland answering; at 2400 ms a frame mid-slide shows face 5 beside face 6,
  and one shows face 6 beside face 1; three-finger swipes go 5 to 6, back, and
  6 round to 1; Super+Ctrl+Alt+4 and 1, bound by the block
  `examples/containers-setup.lua` ships and pressed with `wtype`, turn it to
  faces 4 and 1, and the Lua `face(n)` those keys call turns it to 5 and 6;
  then a plain flip of a two-face card beside it draws its own front mid-turn
  and ends on its back. Control: the same suite against a build whose slide
  shader still stops at four faces passed the status-only turn check and failed
  the frame check (no face 5 or 6 colour drawn). A second control, the suite
  without `resolve_binds_by_sym` in its nested config, failed at the key
  check: the key reached the face's app, which closed, instead of the binding.
- `cover_workflows.py` (15, with `--protocol`): a card with six faces of its
  own refuses a cover with "already has 6 faces"; one with five takes a cover,
  status lists five faces and the cover, and `attach face` is then refused with
  "already has 6 faces".
- `switcher_workflows.py` (12): `face 7` reads "from 1 to 6"; a six-face
  switcher opens with six previews inside the screen and `switcher pick 6`
  turns to the sixth face.
- `unattended_workflows.py` (13): `capabilities` reports `max_faces: 6`, and an
  open of a seven-face definition is `too_many_faces` with no hyprctl change.
- `saved_workflows.py`, `--phase save` (1) then `--phase restore` (5) in a
  second fresh session with the same `--state-dir`.

The cover, switcher, unattended and saved runs used the build before a
comment-only change in `Controller.cpp`; multiface ran on the final build.

Keys Super+Ctrl+Alt+1 to 4 are unchanged (`examples/containers-setup.lua` and
`examples/shortcuts.lua` were not touched). Keys pressed with `wtype` reach
bindings in a nested session only when its config sets
`input.resolve_binds_by_sym=true`, because wtype brings a keymap of its own;
the multiface suite sets it, as the edit, peek and portable suites do. The
switcher's digit keys are not bindings: they read evdev KEY_1 to KEY_9, which
wtype's own keymap does not promise to send, so the switcher suite picks the
sixth face with `switcher pick 6` and presses no digit. After the
review, multiface (18, with the keys) and switcher (12, its pass message now
naming `switcher pick 6`) passed again, each in a fresh session on the final
build.
`fullscreen_workflows.py` and the other suites were not run for this change.
The GLState restore of units 5 and 6 has no visible symptom to test for; the
plain flip after the slides is the only check near it.

## Covers through an update (2026-11-17)

Found live: updating from f005fe2 to 79fdb37 brought a covered card back
without its cover. The cover window was left as a stray tile, and the tile
check failed. A covered card with one face of its own could not be described
at all.

All three CTest checks and all 416 Python unit tests pass. Eight of the unit
tests are new, in `tests/install_test.py`. They check that:
- the cover comes off before the unload and goes back on after, and the card
  shows its cover or the face it showed;
- a card with one face of its own comes apart, and the update says so;
- a refused uncover puts back the covers already off and changes nothing;
- a cover that closed meanwhile is named, and the update goes on;
- the rollback and a recovery run put covers back;
- a core without covers gets no new request.
Taking out the uncover step or the rollback's re-cover makes them fail.

In fresh nested sessions (Hyprland 0.56.2, Aquamarine 0.15.1 with the
render-node patch):
- `tests/install_cards.py`: all 65 checks passed, one of them new. The new check
  updates twice: once with the keyboard on a covered card's cover, once on an
  app of a card showing one of its faces under its cover. Both cards come back
  with the same cover, covered state, faces, layouts and box. The cover fills
  the card's place in the same tile as before. The keyboard, the pointer and
  the monitors stay where they were. A covered card with one face of its own
  comes apart, its window and cover ordinary tiles on their workspace. Run
  alone against 79fdb37's `install.py`, the same check fails as the live
  update did.
- `tests/uninstall_session.py`: all 3 checks passed, one of them new. The new
  check uninstalls with a covered card and a card that shows a face over its
  hidden cover. Every app and both covers come out as ordinary, visible tiles
  on their workspaces. `uninstall.py` needed no change.
- `tests/cover_workflows.py`: all 15 checks passed. The plugin code is that of
  79fdb37, unchanged.

Not covered: an unfolded covered card. The core refuses a cover on an unfolded
card, so the update leaves it without its cover and prints the core's reason.

## Cover a card with a window (2026-11-17)

All three CTest checks and all 408 Python unit tests pass. Five of the unit
tests are new, in `tests/panel_control_test.py`. They check how the panel
handles a covered card:
- the snapshot leaves the cover out of `faces` and reports `covered`;
- `face` turns away from the cover, and a turn that leaves the cover shown is
  reported;
- `flip` turns from the cover;
- `add_face` counts the cover.

The new `tests/cover_workflows.py` passed all 14 of its checks in a fresh
nested session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch),
started with `--notify-recorder` and run with `--protocol` pointing to
`wlr-virtual-pointer-unstable-v1.xml`. It ran again on the final build.
Earlier runs without the drag check passed 12 and 13 checks. The checks cover:
- the status flag, and a card with no cover;
- every refusal, including a popup grab, which changes no card;
- the cover's status, keyboard and tile;
- numbering by the card's own faces in `show`, `name`, `face` and the Lua
  `face`, with `show cover`, `face cover` and the order of flips;
- apps added to the cover's face, to another face and as a new face, and
  `other_side`;
- uncover, and the keyboard rule;
- moves to numbered and special workspaces;
- the batch that swaps cards under a cover, with the pointer and keyboard
  unchanged;
- a real Super-drag onto the cover's face, refused with its notification;
- `control.py unattended save` of a covered card;
- with 300 ms animations: turns by flip, `face cover` and the switcher, and an
  uncover, park or cover closing during a turn;
- the cover released or closed by the user;
- ungroup and unload.

These suites also passed against this core, each in its own fresh session,
built before a change that only reformatted lines and reworded a usage reply.
The last three were started with `--notify-recorder`:
- `card_id_workflows.py` (13);
- `multiface_workflows.py` (9);
- `edit_workflows.py` (14);
- `switcher_workflows.py` (11);
- `dwindle_workflows.py` (7);
- `layout_workflows.py` (6);
- `floating_workflows.py` (10);
- `card_interactions.py` (9, with `--protocol`);
- `unattended_workflows.py` (12);
- `reveal_workflows.py` (19);
- `nearby_card_workflows.py` (6).

Not checked: a native Hyprland move of the card's group to a special workspace
that bypasses Hyprflip (the cover goes along), and the menus' edits on the
cover's face, which go through the same refusal as `attach`.
## A window opening beside a focused card stays outside it (2026-11-17)

Found on the pilot desktop: a chat link in a card's browser made another app
open a window, which looked as if it shared the browser's face; once it closed,
the browser showed a picture of its top half until it was restarted. The new
`tests/outside_window_workflows.py` (3) uses the pilot settings:
`group:auto_group` and `misc:focus_on_activate` on, the classic appearance, a
12 px card gap, scale 1.5 and its animations. It passes in fresh nested
sessions (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch) with
the GTK fixture, Helium 0.21.3.1 and Chromium on the front face. It checks
three things:

- A window opening while the card has the keyboard is its own tile, and the
  card's native group stays locked. This holds after show, hold, park, unpark,
  reveal and a reload. Dwindle splits the card's tile, which is what looked
  like a shared face.
- Once that window closes, the front app is drawn at its full size again.
- A pane that leaves a face leaves the other app drawn at its size again.

Against a core that leaves card groups unlocked, the first check fails: the
window joins the group and the card comes apart. The frozen picture did not
reproduce in any of these setups:

- the GTK fixture;
- Helium on the AMD render node and on the NVIDIA GPU;
- 2400x1600 and 3840x2160 at 1.5;
- with and without OmaRelay's `no_anim` and `focus_on_activate` props;
- the window tiled beside the card, or attached as a pane.

Hyprflip touches no client buffer and no surface state. `docs/CONTAINERS.md`
now says where new windows open.

Both CTest checks and all 388 Python unit tests pass. Fresh nested sessions
also passed `tests/unseen_draw_workflows.py` (3) and
`tests/reveal_workflows.py` (19).

## Movement shortcuts on and off (2026-11-14)

`scripts/navigation.py` holds what the guided setup and the panel helper share
about the movement module: whether it is on, the user's choice, and the switch.
`tests/navigation_test.py` has 18 unit tests against a stand-in Hyprland in a
disposable home: the require line comes and goes with its comment; `on`,
`edited` and `off` need both the file and its line, and only changes of the
user's own count as edited; on installs, loads, records and checks all 24 keys;
off removes the module, its line and the record; a changed copy is kept in the
backup either way; nothing reloads when the shortcuts already are as asked; and
keys that do not come or do not go, a new configuration error, a card that
changed or Hyprland failing mid-switch each put every file back, with its mode,
and leave no backup. A configuration error from before does not count, so the
shortcuts can go off when their module is what fails. The installer gains six
tests (`--no-navigation`, the choice, the shipped copy beside the helper and its
removal by `--backend-only`), the panel helper five (the snapshot fields, also
without Hyprland, and the action: no handoff, its checks, its errors) and the
uninstaller one check. 22 planted faults across the four scripts were each
caught; the 440 Python unit tests pass.

`tests/navigation_switch_workflows.py` runs it in a nested session with
`--native-cards`, in a home inside the session folder: `install-setup.py
--navigation` loads all 24 keys over the configuration's own Super+Shift+1; the
panel action through the installed `control.py` turns them off at once without a
handoff (the own key is back, the card unchanged) and on again; an edited copy
goes off with the backup the action names; `--no-navigation` turns them off and
a later plain install leaves them off. Its 5 checks pass. `tests/key_suites.py`
runs it as `switch`.

## card_of; the key-module suites in one run (2026-11-14)

`hl.plugin.hyprflip.card_of(address)` is new in the core. `tests/nearby_card_workflows.py`
gains two checks, 15 in all:
- `card_of()` names the card a window is in, by address or for the focused
  window, with the apps on its shown face (1, then 2 once a companion is
  attached); it gives nothing for the window beside the card, nor for an unknown
  address;
- on a core without `card_of`, simulated by hiding it from the modules, Super+Shift+Alt+3 and
  Super+J still act on the window beside the card, and on the card from inside
  it.

Five planted faults were each caught. One is in the core: `card_of` also
answering for the card beside a window, built and run like the fix. Four are in
the modules: the move keys or Super+J taking any answer from `card_of` for a
card, and on an older core the move keys asking `in_container()` alone or
Super+J asking `face_size()` alone.

`python tests/key_suites.py --hyprglass … --aquamarine …` then ran the five
suites that load the key modules, each in a fresh session: `workflows.py` 10,
`nearby_card_workflows.py` 15, `setup_workflows.py` 7, `edit_workflows.py` 14
and `pane_workflows.py` 12, all passing. A runner stopped mid-suite closed its
session and left no session directory. CTest passes its three checks, and the
410 Python unit tests pass.

## Movement module installed; Omarchy's workspace numbers (2026-11-14)

`scripts/install-setup.py --navigation` installs `hyprflip-navigation.lua`,
and later runs update it while it is unchanged. Seven new unit tests run the
installer against a stand-in Hyprland in a disposable home:
- the module comes only with `--navigation`, once, loaded last in
  `hyprland.lua`;
- an unchanged copy of the one module every release before had is updated
  without asking, and it stays loaded the user's way (this test needs the
  `v0.3.0-rc.22` tag and skips without it);
- a copy an earlier install recorded is updated;
- a copy with changes of its own is kept until `--navigation` replaces it, and
  the backup holds that copy;
- movement shortcuts that do not register each exactly once put every file
  back;
- a dry run writes nothing, and `--backend-only` refuses `--navigation`.

A new uninstall test removes the module, its lines and the installer's record.

`tests/nearby_card_workflows.py` gains two checks, 13 in all. A
`hyprflip_workspace_id` of the user's own decides where Super+Shift+Alt+3 takes
a window or a whole card. Without one, a stand-in for Omarchy 4.5's per-monitor
workspaces applies: a window moves with Omarchy's own key and a card goes to
Omarchy's number for that key. The stand-in's key and number differ on purpose,
so each check shows which one was used. The user's own function wins over
Omarchy's.

Ten planted faults were each caught: four in the module by the nested suite
(the user's function never asked; Omarchy's key never used; a card ignoring
Omarchy's number; Omarchy's key winning over the user's function) and six in
the installers by the unit tests (an edited copy replaced anyway; no require
line; the shortcuts unchecked after the reload; the released copy unknown;
nothing recorded; uninstall leaving the record). All 410 Python unit tests pass.
The setup, edit and pane suites, which load the setup module, pass 7, 14 and
12 checks with this branch.

## Move keys and Super+J beside a card (2026-11-14)

Found on the pilot desktop: with `nearby_card` on, Super+Shift+<number> on a
new app opened beside a card showed "Focus a multi-app card to move it as a
unit." and moved nothing. It reproduces in fresh nested sessions (Hyprland
0.56.2, Aquamarine 0.15.1 with the render-node patch, on the AMD GPU) with
0.3.0-rc.22's plugin and key modules. `tests/workflows.py` stops at "ordinary
window shortcuts still work", and the session records that warning; this file
lists no run of that suite since 0.3.0-rc.18.

`tests/nearby_card_workflows.py` gains five checks. Each runs the shipped
modules' own bound function. From the window beside the card:
- Super+Shift+arrow toward the card takes the window past it and back, and
  the card stays whole;
- Super+Shift+Alt+3 moves that window alone;
- Super+J turns that window's split instead of being refused for the card's
  two-app face.

From inside the card, Super+J still turns the face. Beside ordinary windows,
Super+Shift+arrow still swaps: the neighbour takes the window's tile exactly.
The session sets `dwindle:preserve_split` as Omarchy does; without it,
dwindle redraws each split from the tile's shape and togglesplit shows
nothing. Dwindle places new windows by the pointer, so the swap check looks
for the side the neighbours are on.

Hyprland swaps no window with a card's locked group, which is why the arrow
toward a card uses Hyprland's window move. That move puts the window past
the card, as a throwaway session showed before the check was written.

With the fixed modules, `tests/nearby_card_workflows.py` passes 11 checks
and `tests/workflows.py` passes 10. Seven planted faults were each caught by
the check written for it:
- the move keys asking `in_container()` alone, as rc.22 does;
- only the number keys doing so;
- Super+J asking `face_size()` alone, as rc.22 does;
- Super+J never acting on a card;
- the move keys never acting on a card, caught by `tests/workflows.py`;
- a card ahead never seen;
- every neighbour taken for a card.

The plugin is unchanged. CTest passes its three checks, and the 403 Python
unit tests pass.

## Updating a build directory in place; release checks for 0.3.0-rc.22 (2026-11-13)

Found on the pilot desktop: OmaCards' panel installing 0.3.0-rc.21 over its
existing Hyprflip source stopped at the build step with "Hyprland links Lua
5.5, but pkg-config found Lua 5.4.9 (lua5.4)", the cached result of 0.3.0-rc.20's
lua5.4 check. Reproduced in one build directory configured first with
0.3.0-rc.20's CMakeLists.txt and then with 0.3.0-rc.21's. With this change the
same directory configures against Lua 5.5.1 (`lua5.5`), builds, links
`liblua.so.5.5` and passes all three CTest checks; the same directory also
switches to `-DHYPRFLIP_LUA=5.4` and back. A fresh build passes all three CTest
checks and all 403 Python unit tests pass. The plugin's code is unchanged from
0.3.0-rc.21, so no nested suite was rerun; see that release's checks below. The
retry after a search that found the wrong Lua version was not exercised.

## Lua from Hyprland; release checks for 0.3.0-rc.21 (2026-11-13)

All three CTest checks and all 403 Python unit tests pass. The new CTest
`lua_library` requires the plugin to link the Lua library Hyprland links and no
other. On this Arch system (hyprland 0.56.2-4, which links `liblua.so.5.5`) the
build now finds Lua 5.5.1 (`lua5.5`) and the plugin links `liblua.so.5.5`; built
with `-DHYPRFLIP_LUA=5.4`, as before, it links `liblua5.4.so.5.4`, and the
check fails on it. Two new bootstrap tests check the package the installer
names: `lua54` for a Hyprland that links Lua 5.4, `lua` for 5.5, and a refusal
when Hyprland's Lua cannot be read.

In fresh nested sessions (Hyprland 0.56.2, Aquamarine 0.15.1 with the
render-node patch) against this core and helper:
- `tests/dwindle_workflows.py` (7 checks) passed; it calls the plugin's Lua API;
- `tests/uninstall_session.py` (2 checks) passed;
- OmaCards' `tests/run-native.py` (9 checks) passed twice.

No other nested suite was rerun for this release.

## Uninstall (2026-11-13)

`tests/uninstall_test.py` (13 tests, a stand-in Hyprland in a disposable home)
covers:
- every line, file and marker the installers wrote coming out;
- a plugin a reload left loaded being unloaded;
- a dry run;
- a new configuration error putting everything back;
- the search path staying for another module;
- earlier errors not counting;
- parked cards stopping it;
- the user's own lines staying;
- `--purge`;
- running without Hyprland;
- the question and its refusal without a terminal.

`tests/uninstall_session.py` passed both of its checks in a fresh nested session
(Hyprland 0.56.2, Aquamarine with the render-node patch), started with its own
home, so that the session loads the plugin from the configuration the installers
edit:
- after `install.py`, `install-setup.py` and a card of two apps, the uninstall
  unloads the plugin with the reload, leaves both apps as ungrouped windows and
  restores hyprland.lua byte for byte;
- a new install then loads again and uninstalls again.
## Change face with Tab; release checks for 0.3.0-rc.20 (2026-11-11)

Both CTest checks and all 388 Python unit tests pass, one of them new: the
shortcut registry offers Change face on Tab and still knows the action by its
earlier description, so older configs stay editable. The key itself was
checked with real key presses (a virtual keyboard sending evdev codes) in a
nested session: a tap, a hold, a second Tab stepping exactly one face without
running the binding again, and no Alt+Tab binding running when Super and Ctrl
are let go first.

OmaCards' `tests/run-native.py` (9 checks) passed twice in a fresh nested
session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch)
against this helper and core. The slide, unseen-draw and bound-window changes
in this release were checked as described below; no other nested suite was
rerun for it.

## Apps waiting unseen may draw (2026-11-10)

Both CTest checks and all 387 Python unit tests pass. The new
`tests/unseen_draw_workflows.py` (3) records, frame by frame, a GTK 4 window
drawing every frame (the fixture's new `spin`) and a foot terminal on one side
of a card, given another size out of sight; the motion probe now reports the
size each app last drew at, per frame and between frames (`now`). In a fresh
nested session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch)
it passes: a side resized while hidden is turned to with both drawn at their
new size; a parked card brought back to a bigger tile slides in after 16 ms
with no frame at the old size; a card built in view shows each app at its size
from its second frame. Against the core before this change (0.3.0-rc.19 with
the slide-gap fix) the slide waited 215 ms and the GTK window's first frame in
view was at its old size. A fresh nested session also passed
`tests/reveal_workflows.py` (19). Found on the pilot desktop: an app in a card
that OmaRelay built again on a visit showed half its height for a few seconds.
The suite does not reproduce seconds: a GTK window takes one frame at most,
so that app's own redraw is the likelier delay.

## A bound window fills the face only it can fill (2026-11-10)

All 387 Python unit tests pass, one new: an unattended `open` whose definition
names the user's terminal beside the workspace browser and alone on the back
face, with one terminal bound and another open elsewhere, puts the bound one on
the back face and opens the card. With nothing beside it in front, the front
keeps it and the open is `incomplete`, with nothing moved. Without the change
the new test fails: that open was `incomplete`. OmaRelay's nested card suite
(`python3 scripts/ovis.py cards-nested`, 14 checks) passed in a fresh nested
session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch) against
this helper and core. Found on the pilot desktop: a card saved with a terminal
on two faces could no longer be built after Hyprflip reloaded, so every visit
to it fell back to an instant cut.

## Slides keep the gap beside a card (2026-11-10)

Both CTest checks and all 380 Python unit tests pass. A tiled card's slot
also holds the gaps_in towards its neighbour, and a turn was drawn and clipped
in that slot. Measured in fresh nested sessions (Hyprland 0.56.2, Aquamarine
0.15.1 with the render-node patch) with the pilot desktop's gaps (8 in, 18
out, 2 px borders) at scale 1.5, a tile left of a tiled card: at rest the two
border boxes are 16 px apart. Mid-slide, at progress 0.15, 0.4 and 0.7 and
both ways, a three-face card (flip and slide both run the strip) and a
two-face card with `slide` drew their faces up to 8 px from the tile, the
slot's own edge. Drawn in the card's panes, every frame kept 16 px. Two-face
flip, vertical, fade, portal and dissolve never drew in the gap.

The new `tests/slide_gap_workflows.py` (4) captures frames mid-slide both ways
for a three-face card right and then left of a tile, with and without a card
frame, and for a two-face card with `slide`, and requires every column between
the border boxes to show only the background. Against the 0.3.0-rc.18 core it
fails: in all four frames of its first check the card's half of the gap was
covered. Against this core it passes. Fresh nested sessions also passed
`tests/transitions.py` (15), `tests/multiface_workflows.py` (9),
`tests/switcher_workflows.py` (11) and `tests/floating_workflows.py` (10).
`tests/fullscreen_workflows.py` passes its first 7 checks, every transition
and peek while fullscreen among them, then fails when an app leaves a
fullscreen card: afterwards no window has the focus. It failed there twice
with this core and once with the 0.3.0-rc.18 core, so this change is not the
cause.

## Show any face from the panel; release checks for 0.3.0-rc.19 (2026-11-10)

Both CTest checks and all 386 Python unit tests pass, six of them new: the
`face` action turns a hidden third face by number and a two-face card on a core
without numbered faces with one flip, never opens the edit chooser, focuses the
app the panel chose (or else the face's own), only focuses when the face is
already shown, and refuses a missing face or an app from another face; the
snapshot reports `capabilities.show_face`. Removing the chosen-app focus fails
two of them.

OmaCards' `tests/run-native.py` (9 checks) passed four times in a fresh nested
session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch) against
this helper, choosing an app on a hidden face with the `face` action, and once
against the 0.3.0-rc.18 helper, which flips instead. That suite cannot tell
whether the action turns the card itself: on a native card, focusing an app on
a hidden face also turns it, so the run passed with the turn removed. The unit
tests cover the turn. No other nested suite was rerun for this release.

## Ungroup from any side; release checks for 0.3.0-rc.18 (2026-11-10)

Both CTest checks and all 380 Python unit tests pass, three of them new or
changed: Edit card offers Ungroup card on a side with several apps (and still
not on a fullscreen card), and the panel snapshot reports
`capabilities.ungroup_any_face`. OmaCards' `tests/run-native.py` (9 checks)
passed three times in a fresh nested session (Hyprland 0.56.2, Aquamarine
0.15.1 with the render-node patch) against this helper, ungrouping a card
through its shown side holding two apps; the three apps stayed open. With only
the menu change reverted it failed with “That action is no longer available”.
The parked-card and card-keys changes in this release were checked as described
below; no other nested suite was rerun for it.

## Parked cards keep their size (2026-11-10)

Both CTest checks and all 378 Python unit tests pass. Measured in a fresh nested
session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node patch) at scale
1.5, with two cards of a real Helium window and a foot terminal taking turns
beside a tile the way OmaRelay switches them (`no_anim` cuts, hold, park on a
special workspace holding three more parked cards, unpark, `reveal 0.7 up`):
before, a parked card was laid out at 938x491 or 458x491 on the special
workspace against its 938x1025 tile, and all 8 slides waited the full 200 ms,
the browser never drawing at its tile's size unseen; after, the parked card
kept 938x1025 and all 8 slides began in the first frame after the batch.

Fresh nested sessions passed `tests/reveal_workflows.py` (19, one new: a card
parked from its tile keeps its apps' boxes, slides back with no frame waiting
and `last_slide_wait_ms` within two frames, and, its special workspace shown,
is laid out there with no move; `last_slide_wait_ms` is null before the first
slide), `tests/card_id_workflows.py` (13), `tests/unattended_workflows.py`
(12) and `tests/install_cards.py` (64). OmaRelay's `cards-nested` (13 checks)
and its card unit tests (161) pass against this core.

## Card keys beside a card (2026-11-10)

Both CTest checks and all 378 Python unit tests pass, one new for the
`nearby_card` preference (persisted, applied, refused on an older core). In a
fresh nested session (Hyprland 0.56.2, Aquamarine 0.15.1 with the render-node
patch), `tests/nearby_card_workflows.py` passes 6 checks: on by default; from
a tile beside a card, `flip`, `face <n>` and `unfold` act on that card and the
focus stays on the tile; turned off, a flip from the tile does nothing while
one from inside the card still turns; and with two cards on the workspace a
flip from the tile turns neither. Peek and the switcher hold need real keys,
which `wtype` does not deliver in a nested session; they use the same lookup.

## Installed release for panels (2026-11-10)

Release checks for 0.3.0-rc.17. Both CTest checks and all 377 Python unit
tests pass, including two new ones: `bootstrap.py` records the newest release
tag the installed commit contains and removes a stale record when the
checkout has no release tag, and the snapshot reports `installed_release`
only for well-formed releases. `scripts/bootstrap.py` then ran end to end on
the live desktop (Hyprland 0.56.2) from the `v0.3.0-rc.17` checkout, kept the
open cards, and recorded `0.3.0-rc.17`, which `control.py snapshot` reported.
The reveal slide in this release was checked by `tests/reveal_workflows.py`
(18), as described below; no other nested suite was rerun for this release.

## Reveal slides up and down (2026-11-10)

Both CTest checks pass. In a fresh nested session (Hyprland 0.56.2, Aquamarine
0.15.1 with the render-node patch, on the AMD GPU), `tests/reveal_workflows.py`
passes 18 checks, the earlier 17 unchanged plus one: a direction that is not
`up` or `down`, or one before the speed, is refused; a card slides up from
more than 60% of its height below its tile and down from as far above,
moving only in y and only towards its tile, never fading, ending exactly in
its tile; a picture is up during the slide and none after; and the
neighbour, focus and pointer stay. A frame grabbed halfway through a slow
slide shows the new card and its header coming up from below and the old
card's picture going out at the top. The slide does not clip: on a card that
does not reach the screen edge, the two cards pass over what is above or
below them for the length of the slide.

## Face slide, switcher, swipe and names (2026-11-09)

Release checks for 0.3.0-rc.16. Both CTest checks and all 375 Python unit
tests pass. Fresh nested sessions on Hyprland 0.56.2 passed every suite of
0.3.0-rc.15 with the same counts, plus the new `tests/switcher_workflows.py`
(11): the switcher opening with a preview of each of four faces, stepping,
picking, going to the last face, cancel and a workspace change putting it
away, an animated pick with no fallback, swipes fed through `hyprctl hyprflip
swipe` (a slow short swipe settling back, past halfway, a flick, resistance
past one face, a cancelled swipe), `face <n>` and Lua `face(n)` with their
refusal, and face names through the update round trip, including `&`, `%`
and spaces. Frame captures of the slide on three- and four-face cards show
the next face entering from the right inside the card.

Simulated keys from `wtype` do not reach bindings in a nested session, so the
hold-and-release of the flip key and real trackpad swipes were checked by
hand on omac (Asahi, 120 Hz) rather than in the suites.

## Cards with up to four faces (2026-11-09)

Release checks for 0.3.0-rc.15. Both CTest checks pass (core_test adds three
cases for the N-way unfold split) and all 375 Python unit tests, 21 of them new
for three- and four-face restore lines, recipes, Find, edit menus and the panel
protocol. Fresh nested sessions on Hyprland 0.56.2 passed every suite of
0.3.0-rc.14 with the same counts, plus the new `tests/multiface_workflows.py`
(9): a three-face restore, flipping round all faces, `show <n>` and its
refusal, adding a fourth face and refusing a fifth, removing a face by
releasing its only app, the update round trip through `card_restore.describe`,
unfolding three faces side by side, and a two-face card still dissolving.
OmaCards' native panel run passed against this helper.

## hy3 retired; every suite on dwindle (2026-11-09)

Release checks for 0.3.0-rc.14. The tree passes both CTest checks and all 354
Python unit tests. Every nested suite now loads only `build/hyprflip.so` and
builds cards with `card`; the hy3-only suites (containers, container upgrade,
stale targets, trial, updater) are removed with the provider. Fresh disposable
nested sessions on Hyprland 0.56.2 passed: install cards (64), reveal (17),
card id (13), unattended (12), floating (10), dwindle (7), fit (4), repair
(10), opening (6), setup (7), edit (14), layout (6), pane (12), workflows
(10), three panes (9), cold open with repair (12), chill (8), peek (19),
transitions (15), card motion (7), card frames (10), card interactions (9) and
the saved restart run (7).

Porting found three core bugs on dwindle, fixed here: release moved the focus
to the card's first app, moving a pane to the other face reset the proportions
of both faces, and replacing a tiled app left the outgoing app in a sliver.
The workflow suite's screenshot step needs the host screen on: with the screen
locked the nested session draws no frames and `grim` times out.

## Open cards brought here, floated and completed whole (2026-11-09)

Release checks for 0.3.0-rc.13, a helper-only change. All 356 Python unit tests
pass, 4 of them new: an open card on another workspace is moved here with
`card <id> workspace <here> silent`; one saved floating and open as a tile is
ungrouped and restored floating; one saved for its own workspace is still gone
to; and reopening a missing app on a core with `card_ungroup` sends one ungroup
and one quiet restore, with no attach. Fresh nested sessions passed the
unattended (12), floating `--dwindle` (10), dwindle (7) and card id (13) suites.
The repair, opening and saved suites need the hy3 build and were not run.

On the pilot desktop, the AI card was open as a tile in half the screen with
Claude Desktop closed. Opening it reopened Claude and rebuilt the card floating,
1151 x 604 px and inside the 1512 px screen, with ChatGPT at 509 px and Claude at
622 px. Before this change the same open failed with “This split is too small
for the applications”.

## Saved cards that must grow to fit (2026-11-08)

Release checks for 0.3.0-rc.12. The tree passes both CTest checks and all 352
Python unit tests, 4 of them new in `tests/saved_test.py`: a saved card opens in
one quiet restore with no mark or pair, a floating card starts from its front
app's size before setup tiled it, a refusal's reason reaches the person, and a
core without `card_ungroup` keeps the earlier path.

Fresh disposable nested sessions on Hyprland 0.56.2 passed:

- `tests/fit_workflows.py` (new): 4 checks with a GTK fixture that asks for a
  700 px minimum. A floating card restored from a narrower box grows to fit, on
  screen; one that would grow past the right edge moves back, along that side
  only; one that fits as given keeps its exact box, partly off screen; and one
  needing 3500 px on a 1920 px screen is refused with the app and both sizes
  named, all three apps left open and no card made.
- `tests/install_cards.py`: 64 checks. The first run of this tree failed here:
  the new clamp moved an unfolded floating card that an update put back on
  another monitor (x 300 to 2000). The clamp now applies only to a card that had
  to grow, and the rerun passed.
- `tests/reveal_workflows.py` (`--notify-recorder`): 17 checks.
- `tests/card_id_workflows.py`: 13 checks.
- `tests/unattended_workflows.py` (`--notify-recorder`): 12 checks.
- `tests/floating_workflows.py --dwindle`: 10 checks.
- `tests/dwindle_workflows.py`: 7 checks.

On the pilot desktop (Asahi MacBook, 1512x982 logical), the saved AI card,
Terminal on the front and ChatGPT (480 px minimum) beside Claude Desktop
(600 px) on the back, opened from the OmaCards panel path where it had failed
with “failed to add”. The suites that need the hy3 build (opening and saved
workflows) were not run.

## Release-candidate checks (2026-11-03)

The current tree passes both CTest checks (`make test`) and all 348 Python unit
tests. clang-format still reports 343 pre-existing findings, down from 348 after
the changed return block was formatted; formatting is not a clean gate.

Fresh disposable nested sessions on Hyprland 0.56.2, using the patched Aquamarine
render node and notification recorder, passed these suites:

- `tests/reveal_workflows.py`: 17 checks, including the two `leave` checks below
  and usage text that lists the animation verbs.
- `tests/card_id_workflows.py`: 13 checks.
- `tests/install_cards.py`: 64 checks.
- `tests/unattended_workflows.py`: 12 checks. The missing app returned the keyboard
  within 63 ms, below the suite's 300 ms limit, with the pointer unchanged.

An earlier unattended run stopped after five checks because the test runner's PID
namespace could not read the compositor-reported process id under `/proc`. The
fresh rerun used the same host PID namespace as the nested compositor and passed
without weakening its assertions. Every nested session started for these checks
was stopped and its connection file removed.

These checks exercise the real plugin with disposable terminal fixtures. They do
not establish how real browser pages render during a switch, or the feel and
frame pacing on the live desktop. The known small-page ghost at 4K described below
is unchanged and remains unresolved; this run adds no new 4K browser measurement.

## A swap with hold and reveal (2026-11-02)

`tests/reveal_workflows.py` takes a fresh nested session started with
`--notify-recorder` and needs `make test` first, for `build/motion_probe.so`. It
loads the core and the read-only motion probe, which now also records every
window's box and fade and how many fadeouts Hyprland holds, frame by frame. It
makes two headless outputs and uses the pilot desktop's curves and a magenta
wallpaper. It passes 17 checks in the 2026-11-03 rerun:

- `status` says `"reveal":true`.
- A bad id, address, speed or extra word gets a clear reply, adds no line to the
  notification recorder, and changes nothing. Building a card later adds lines,
  so the recorder was working. Hyprland's own bar cannot be read from here: the
  same branch in `Plugin.cpp` keeps both silent.
- A focus dispatch warps the pointer, so one left where it rested means no warp.
- Hold then reveal on a window: from the first frame, the box goes from about 92%
  to its goal without shrinking and the fade only rises. It ends exactly in the
  place it swapped into, with `no_anim` false, one picture that then goes, and the
  neighbour on every frame, the focus and the pointer unchanged.
- A window with a `no_anim` window rule comes in at once, and it still reads true.
- Speed factors 0.7 and 2 scale the time to settle (within 0.55-0.85 and 1.6-2.4
  of the same run at factor 1), and a later reveal at factor 1 takes as long as
  the first.
- A hold with no reveal leaves no fadeout, with the window in place or moved away.
- `leave` on a plain window creates one temporary close-animation picture, then
  removes it. The real window remains mapped and parked, with the focus and
  pointer unchanged and no notification; bringing it back restores the same tile.
- `leave` on a card snapshots only its shown face, cleans every picture, and keeps
  the parked card intact. Bringing it back restores its panes and the neighbour's
  tile, with the focus and pointer unchanged and no notification.
- `no_blur` set true stays true. Set false over a window rule of true, it reads
  true during the fade and false after, also when the window leaves and returns
  in mid-fade. A rule alone stays.
- 9 batches at 16 ms keep at most 2 pictures of a window, then none, with the last
  window right, `no_anim` and `no_blur` false and the focus unmoved.
- A card over a card: its two shown panes open as one and their fades match, its
  frame box is the same on every frame, and 2 pictures come and go.
- A plain window replacing a card: 90 ms in, at factor 4, a pixel of the Flip
  button is still the header's own colour. A card replacing a plain window: the
  same pixel is still the window's colour, and the frame's box starts smaller and
  grows with the panes.
- 9 card batches at 16 ms keep at most 4 pictures, then none, with the last card
  right.
- `hyprctl reload` during a reveal: it ends right, `no_blur` comes back, and the
  next reveal is a real open.
- Plugin unload during a reveal: Hyprland's list has no fadeout straight away, the
  window ends in its tile, and the output still draws what changes after.
- A monitor removed with a picture up: the picture is gone at once, and an unload
  and a new load after that work.

What this does not prove: everything ran nested on the second GPU, so it says
nothing about NVIDIA or about a real monitor's vblank, since a headless output runs
on a timer. It used terminals in its tiles; the frame figures below used Chromium.
Whether the speed feels right can only be judged on the real desktop. The card-id,
unattended and installer suites were also rerun on 2026-11-03, as recorded above.

One frame run at 3840x2160 and 1.5x, at factor 0.7, on six swaps each, with Chromium
windows and cards parked at other sizes: the box reached its goal at 277.5 ms
(277.2-278.9) for a window and 278.8 ms (276.4-280.2) for a card, and the fade at
about 252 and 254 ms. Capture missed most frames, so the frames' own settled
figures (390 and 351 ms) are the last grab, not the end. Herdr's stand-in did not
move or resize, and the tile never showed wallpaper.

**A known flaw at 4K:** a faint small page does show. It comes from a window parked
at another size, whose first frames in the tile still have its old layout. It was
seen on each of the four swaps looked at closely (three cards and one window), about
36-42 ms in, at a fade of about 0.12-0.16. It was gone from the next frame grabbed
(61 and 71 ms) on the two swaps where that frame was looked at. Nothing here fixes
it.

## Cards opened, saved and ungrouped by another program (2026-11-02)

`make test` passes (CTest: the core suite, with the new input-guard cases, and
`own_symbols`), and so do 348 Python unit tests (210 at rc.10) and
`python3 -m compileall -q scripts tests`. clang-format reports the same 348
findings as rc.10, with the same count in every file.

Three suites ran in fresh nested sessions with only the core loaded (Hyprland
0.56.2, Aquamarine 0.15.1 with the render-node patch, on the second GPU), each
on a workspace no monitor showed. Before its pointer measurements, each suite
shows that a plain focus dispatch warps the pointer to the centre of the window
it focuses, so a pointer left where it rested means that nothing warped it.
Before every measured action the pointer rests off-centre over a tile, and
`cursorpos` confirms it got there. Each suite first waits for the session's own
two windows (`session_windows` in `tests/control.py`): `tests/nested_session.py`
writes `session.json` a second before it opens them, and a suite started straight
after lost the keyboard to them.

- `tests/card_id_workflows.py` passes 13 checks. Besides the quiet restores,
  turns, parking and refusals of 2026-11-01, it takes a pair apart by id into
  two loose windows; refuses to ungroup a fullscreen card, and out of
  fullscreen ungroups it into loose tiles; ungroups a parked card, whose apps
  stay loose on `special:park`; swaps two cards beside a working tile in one
  `hyprctl --batch`, where every move replies ok and the tile stays; and leaves
  the layout as it was after a refused unpark in a batch and `preselect x`.
  `cursorpos` is unchanged right after and once settled around 20 scripted
  actions (4 quiet restores, 4 `show`, 2 `flip`, 7 silent `workspace` moves to
  park, unpark and a named workspace, and 3 `ungroup`), and before and after
  both batches.
- `tests/install_cards.py` passes 64 checks, with `input:follow_mouse` 1,
  `cursor:warp_on_change_workspace` 1 and `binds:hide_special_on_workspace_change`
  true, the values on the pilot desktop, and two monitors: the session's own and
  a headless 4K one at 1.5x that has the cards. Each check of the whole updates
  and of the tile corrections compares `cursorpos`, what each monitor shows (its
  workspace and open special workspace), the focused monitor and the keyboard
  before and after, and the cards' faces, sides, layouts and frames within 4 px;
  a correction that succeeds also compares the neighbour's tile. Where a whole
  update compares frames, it fails on a line saying that a tile was not returned,
  and every whole update fails on a line saying that something is not as it was.
  - The 8 earlier checks: a fresh install into a throwaway home; a tiled 70/30
    card beside its neighbour and an unfolded floating card kept as they were; a
    card parked on `special:park` left as separate windows, with a count and never
    "Could not keep a card"; the keyboard on the tiled card; an update from another
    workspace; a correction on the card's own workspace with the keyboard on the
    neighbour, then on the card; a card with `no_focus` there; a clean unload.
  - The keyboard on each app of a two-app face of a card alone on its workspace.
    The unload takes it from the first app, and it goes back.
  - The keyboard on each app of a two-app face, with a card built earlier on that
    workspace that a correction takes the keyboard for (the event socket shows it
    did), and the pointer over the neighbour or over the other monitor, where only
    the focused monitor differs. The layout has two more tiles, so tiles are not
    compared here: see below.
  - Two tiled cards alone on a workspace, of 2 and 2, 2 and 3, and 3 and 3 apps, as
    they fell and with their split turned. Each gets three updates: from another
    workspace, then twice with the keyboard on one card and the pointer over the
    other. Their frames are still within 4 px of the first ones at the end.
  - An update that corrects a card in the row below its neighbour on a hidden
    workspace (the event socket shows the visit), with the keyboard on the other
    monitor, on another workspace of that monitor, on nothing on an empty
    workspace, in a special workspace open over another workspace, and on each
    app of a two-app face of another card.
  - A correction of a card displaced with `togglesplit` and `swapsplit`, from the
    same places and more: the card hidden or shown; the keyboard on nothing on the
    other monitor; seven positions of an open special workspace, with the keyboard
    in it over another workspace, over the card, or over an empty workspace with the
    pointer over the other monitor, on the other monitor with it open over another
    workspace, the card or an empty workspace of the card's monitor, and in it on
    the other monitor, each with `binds:hide_special_on_workspace_change` on and off;
    and the pointer over the other monitor from the keyboard, where only the focused
    monitor differs. Showing an empty workspace hands the focus to the monitor under
    the pointer, so the special workspace reopens only after the focus is sent back.
  - A card with `no_focus` makes `settle` raise: Hyprland replies ok to its focus.
    No step goes out, no tile moves and everything comes back, from another
    workspace (with the card or a neighbour last focused there: showing the
    workspace then hands the keyboard to the neighbour) and from the other monitor.
  - A named workspace on either monitor makes `settle` raise before any focus,
    since a focus by id would land on workspace 1 (measured). The card stays out
    of its tile, and nothing else changes.
  - A card saved with a tile of no size, as an update under a fullscreen window
    saves it, gets no focus and no step, and nothing changes.
  - With `input:special_fallthrough` on and the keyboard in a special workspace
    over the card, `settle` raises, and the card and its neighbour stay where they
    are. With the keyboard on the other monitor the correction goes through.
  - A focus that moves to the other monitor just before a correction's `togglesplit`,
    `swapsplit` or `resize` (with a size the card does not have, so that one is
    due): that step does nothing, read right after it and at the end from the two
    tiles of that monitor; `settle` raises; and the keyboard, the pointer and what
    the monitors then show stay.
  - A monitor that goes away at a correction's first step, with the keyboard on
    another: it stays there, and the card and its neighbour keep at least 500 px on
    each side.
  - A fullscreen window with `misc:on_focus_under_fullscreen` 0, 1 and 2 and a
    maximized one with 1, on the card's workspace, with the keyboard on it, and
    hidden with the keyboard elsewhere. It stays so, nothing else changes, and the
    update prints that it left the tile alone. Run again before it ends, no
    correction visits that workspace and the update says nothing. Once it ends,
    the card, which was in the row below its neighbour, is on the left half.
  - An update whose request to show a workspace again gets no answer still ends,
    and prints that the keyboard or what a monitor shows is not as it was.
  - A recovery run after a crash, with the core gone and the keyboard on the
    side the recovery file does not show: the card comes back on its saved side
    with the keyboard on that side, and the focus does not turn it.

  Each fix was reverted in a scratch copy, one at a time, in a fresh session,
  with the 56 new checks running on after a failure: with each card corrected as
  soon as it is rebuilt, 7 checks fail (the six with two cards alone, where one ends
  up a sliver, and one with the pointer over the other monitor); with the keyboard
  going back only after the corrections, 1 (that one); with a special workspace
  reopened before the focus is sent back, 4; with a resize from anywhere, not only
  from the card's corner, 3 (both with `input:special_fallthrough` and the monitor
  that goes away); with steps not guarded by the keyboard, 3 (the focus that moves);
  without the final check of the card's box, 4; without the refusal under a
  fullscreen window, 4; with a saved tile of no size gone back to, 1; without the
  line that something is not as it was, 1; without the keyboard going back after
  the restores, 3; without the monitors being put back, 22; without a workspace
  being shown again, 18; without a special workspace being reopened, 9; without the
  focused monitor going back, 3; without taking back a keyboard that a refused
  card's workspace handed to a neighbour, 2; without the refusal of a named
  workspace, 2; without the check of `acceptsInput`, 1; with no focus back to the
  window that had the keyboard, 12 (the suite then stops at the first of the 8
  earlier checks, as they do not run on after a failure); with a plain focus
  instead of the no-warp one, 45 (likewise). Every new check fails in at least one
  of these. Ten fail only with the plain focus, since showing the last workspace or
  monitor again was enough there: the keyboard on another workspace of the card's
  monitor, in a correction and in an update; on the other monitor with the card
  shown; in a special workspace open over the card, with each value of the option;
  on the second app of a two-app face, with the pointer on either monitor; and on
  each app of a two-app face of another card, in an update that corrects a hidden
  one.
- `tests/unattended_workflows.py` passes 12 checks. Each request goes through
  `control.py unattended` in its own process, with one JSON line back, nothing
  on stderr and an exit code that agrees. `capabilities` finds the core.
  `give_back` sends one focus that leaves the pointer and `cursor:no_warps` as
  they were, and sends nothing but a read of the active window when that window
  has the keyboard already. A stored card opens beside the working tile in one
  batch of silent moves and a quiet restore, and the keyboard, the workspace and
  the working tile stay. Bound apps parked on a special workspace join a card
  while that workspace stays hidden. A missing app starts from a hidden launcher
  matched by its window class, inside the nested session, and the keyboard is
  back on the working tile within 300 ms (57 ms in this run). A slot the caller
  owns is never launched, though a launcher matches it, and a bound app no slot
  wants stays where it was. A restore the core refuses sends every imported app
  back where it was, a special workspace included, and floats the floating one
  again. Saving a parked card by id keeps no title and leaves the card and the
  menus' library alone, and saving it again is `unchanged`. Unloading releases
  the apps of all four cards, shown or parked. No window title (each test
  window's title starts with a sentinel) reached the helper's hyprctl calls,
  its replies, its store or a notification. `cursorpos` is unchanged around
  all 5 opens (the refused one included), both saves and `give_back`, and after
  each open the keyboard is on the working tile.

What an update still cannot do, measured in nested sessions unless it says otherwise:

- A rollback rebuilds cards plainly, by design, since the core it goes back to can
  be older than quiet restores. The last card rebuilt gets the keyboard and shows
  its workspace, and no tile is corrected: a card from the row below its neighbour
  stayed on the left half, and a good update after that keeps it there.
- With two more tiles on a card's workspace, tiles do not always come back as they
  were, and a card that is not back gets the printed line. Of ten layouts with one
  or two cards and up to three neighbours, updated from another workspace, one did
  not with the suite's options (`dwindle:smart_split` on): a card with two
  neighbours beside it came back 63 px narrower, and one neighbour 45 px wide, as
  its corner was right and a resize took the room from a neighbour it was not
  measured against. Four did not with the pilot desktop's options (`smart_split`
  off, `preserve_split` on, `force_split` 2): a card last or in the middle with two
  neighbours, a card with three, and a neighbour with two cards. Those tiles ended
  up elsewhere, none under 678 px. The keyboard, the pointer and the monitors stayed
  in all of them, and a committed check of one layout also shows that.
- With `cursor:warp_on_change_workspace` 2, the keyboard and the monitors come
  back but Hyprland warps the pointer as a correction visits a workspace, also
  a workspace shown on another monitor.
- With `input:special_fallthrough` on and the keyboard in a special workspace open
  over the card, the layout controls do not reach the card: it stays out of its
  tile, with the printed line, and nothing else changes. Over another workspace of
  its monitor, or with the keyboard elsewhere, the correction goes through, unless
  `binds:hide_special_on_workspace_change` is off too: the special workspace then
  stays open over the visited card, and the card stays out with the line.
- A card second in its split (right or below), beside one neighbour, whose split was
  moved by hand does not get its size back. The split returns to 50/50 and the line
  is printed, since the card's near corner moved with the split and the corner check
  stops the resize. A card first in its split comes back. Before this, the frame
  changed size at each update, silently, and the keyboard and pointer moved too.
- With `dwindle:default_split_ratio` 1.4, two tiled cards alone on a workspace ended
  up with one squeezed to 126 px in 4 of 7 layouts, with two printed lines: each step
  comes closer by distance, so the card ends in its corner, and the resize then takes
  the other card's room. Before this, all 7 differed. The ratio left unset does not
  do this.
- A move to an empty workspace during a correction's steps is undone: the keyboard is
  then on nothing, which reads as not taken, so the monitors go back. A move to a
  window stops the steps and keeps the keyboard with you.
- With the suite's options, two cards alone with a moved split come back at the same
  frames, but the update also prints the line for the first card, whose size only
  comes right with the second card's resize. With the pilot desktop's options it
  prints nothing.
- A monitor that shows a named workspace makes every correction give up, not just
  one on that monitor, and so does a special workspace or monitor with an unusual
  name (unit tests). A card that does not take the keyboard stays out of its tile
  too. Each prints the line.
- A fullscreen or maximized window on a card's workspace stops the correction before
  any focus, as a focus under it would take its fullscreen or end it. The tile stays
  as the rebuild made it, also after that window leaves fullscreen, as nothing
  corrects it later. While it lasts the core reads the rebuilt tile as no size, so an
  update run again has nothing to compare and says nothing.
- A focus that moves during a correction stops it. A step that had acted stays, so
  the card can stay half-way (unit tests and a committed check), with the line.
- With the pointer over another monitor than the keyboard, a correction or a
  keyboard given back can leave the focus on the keyboard's monitor, until the
  pointer moves: only a focus can give a window the keyboard.
- Hyprland's workspace history keeps a correction's visit: the `previous` workspace
  afterwards is the card's, not the one before.
- A correction from a keyboard on nothing with the card's workspace shown leaves the
  keyboard on the card, as no dispatch can take it from a window (unit tests). That
  state needs the keyboard on nothing before the update. A keyboard an unload took
  still goes back. After a crash between the unload and the restores, the next run
  reads the keyboard as the crash left it, which can be on nothing.
- If a monitor changed during the update, or the keyboard is on another window, the
  keyboard stays where it is (unit tests, as are a window that closed during the
  update and a monitor that went away). A monitor that goes away during a correction
  can leave the card's monitor showing the card's workspace, as the focus is
  no longer there to put it back (measured). A `hyprctl` that fails on the way back
  leaves the keyboard on the card and its workspace shown, and the update goes on.
  In each of these, and for a keyboard that was on a side the rebuilt card does not
  show, the update prints that the keyboard or what a monitor shows is not as it
  was, which `bootstrap.py` passes on.
- The monitor flips and a special workspace closing and opening again can be seen
  for a moment.

Which suites wait for the session's windows: `tests/install_cards.py`,
`tests/card_id_workflows.py`, `tests/unattended_workflows.py`,
`tests/dwindle_workflows.py` (7 checks), `tests/fullscreen_workflows.py` (12,
without `--protocol`) and `tests/unfold_workflows.py` (5), the last three each run
once in a fresh session for this. `tests/chill_card_workflows.py`,
`tests/floating_workflows.py --dwindle`, `tests/card_interactions.py --dwindle`,
`tests/integration.py`, `tests/menu_workflows.py` and the hy3 suites start the same
way and were not changed or run. Those that read the session's windows at once
(`tests/config_upgrade.py`, `tests/motion.py`, `tests/peek.py`, `tests/saved_workflows.py`
and others) stop with an error if started too early.

Notifications are recorded in `tests/unattended_workflows.py`, which needs a
session started with `--notify-recorder` and turns Hyprflip's notifications
on. The recorder stands in for `notify-send` only on the nested compositor's
PATH, so the suite puts the recorder's folder first on PATH and drops
`DBUS_SESSION_BUS_ADDRESS`, `DISPLAY`, `DESKTOP_STARTUP_ID` and
`XDG_ACTIVATION_TOKEN` for everything it starts: the terminals, the helper, its
hyprctl and the apps the helper launches, whose environment the suite reads
back. A refused Lua flip and a refused plain `restore` must notify, and each
added one line. A refused `card 9999 flip`, a bare `restore quiet` and a
refused complete `restore quiet …` must not, and added none; nor did any helper
request. The log held 2 lines at the end. `tests/card_id_workflows.py` and
`tests/install_cards.py` record no notifications and ran in sessions started
without options.

The drag guard's client-move case (a card's window moved by a drag the app asks
for, such as a GTK header bar, where no surface holds the pointer focus) was
measured by hand in nested sessions: the park was refused mid-drag and went
ahead after release. No committed suite covers it yet; see
[ROADMAP](docs/ROADMAP.md#to-do-a-nested-check-for-drags-the-app-starts). No
nested suite other than those named above was run for these changes.

## Cards driven by id (2026-11-01)

In a nested session with only the core loaded (Aquamarine 0.15.1 with the
render-node patch, on the second GPU), `tests/card_id_workflows.py` passes 7
checks. A quiet restore builds a tiled card beside a working tile without
moving the focus or the workspace, and moves the focus to the shown side when
it takes in the focused app. `card <id> show` and `flip` turn a card without
taking the focus (animated, no fallback) and carry the focus along when it was
on the card. The card parks on `special:park` and comes back, and Find leaves
it out while parked; it follows to a numbered workspace and moves silently to
a named one and back. Malformed actions and unknown ids change nothing, and
unloading releases the card's apps. Floating (dwindle 10) and unfold (5) pass.
Dwindle stops at its first check on this machine with rc.9 too (attaching the
850 px GTK fixture: "This split is too small"), so it was not run further; hy3
suites were not run.

CTest's new `own_symbols` check fails on the first build of this change, whose
`moveTo` sat in an anonymous namespace: the plugin linked, and the nested
Hyprland aborted with a symbol lookup error at the first parked move.

## Tiled cards keep their tile through updates (2026-10-07)

On the developer's desktop the panel installer updated to rc.5 and kept all 4
open cards with identical faces, sides, focus, layouts and proportions; the
3 floating cards kept their exact frames, but the tiled card came back stacked
under its neighbour instead of beside it (839 px away). `tests/install_cards.py`
now runs with a neighbouring tile on a 4K/1.5x output with smart and preserved
splits, and displaces the restored tiled card with `togglesplit` and
`swapsplit`; the correction returns it to within 4 px of its saved tile
(4 checks).

## Updates keep cards; one-command bootstrap (2026-10-06)

`tests/install_cards.py` runs the real `scripts/install.py` against a nested
session with a throwaway home: a fresh install, then an update with a tiled
card (70/30 face) and an unfolded floating card open; both come back identical
(3 checks). `scripts/bootstrap.py` ran end to end in a nested session whose
config file the installers write: check, build, self-test, core and helper
install, with all guided shortcuts registered. Unit tests cover the installer's
card handoff and the bootstrap's failure reports (205 tests).

## Menu, portable and notification suites (2026-10-05)

Run for the first time on this machine, in hy3 demo sessions on the second
GPU (`--containers --aquamarine`): menu workflows pass with Fuzzel, Rofi and
Wofi (4 checks: automatic Fuzzel selection, then real selection, text input and
Escape for each backend), portable workflows pass (5), and notification
workflows pass.

## Blur during snapshot transitions (2026-10-05)

With translucent, blurred apps over dense text (foot needs
`colors-dark.blur=yes`, since it opts out of compositor blur by default),
background detail behind the card measured about 24 throughout slide and fade
before the fix (sharp text) and about 1 after it (blurred), matching the
resting card; flip already blurred. Mid-slide captures show both faces
blurred and no matte leaking into colour. `tests/fullscreen_workflows.py` now
uses its own headless output, and the floating stacking check returns focus to
the card. Integration (18), motion (5), peek (19), floating (dwindle 10,
hy3 10), fullscreen (13), card frames (10), workflows (10) and dwindle (7,
including `layout toggle`) pass.

## Floating cards stay on top while turning (2026-10-04)

Reproduced on the second GPU with two overlapping floating cards: the focused
top card was drawn under the other card, and its flip turned behind it.
`tests/floating_workflows.py` now floats another window over a card, focuses
and flips the card, and checks that every app of both faces is stacked above
it with the focused app on top. Floating (dwindle 10, hy3 10), interactions
(dwindle 9, hy3 9), fullscreen (13), native-card Chill (9) and card frames (10)
pass.

## Cards joining a chilled workspace (2026-10-02)

`tests/chill_card_workflows.py` passes 9 checks with the adapter-v4 engine,
including a tiled card moved onto a chilled workspace: it floats inside the
screen with every app tagged, and tiles back when Chill is turned off. With a
v3 engine (no `join`) the same move is refused and the card stays in place.

## Workflow suites brought up to date (2026-10-02)

The six suites that failed on both rc.3 and its baseline were test problems,
not product bugs. After the fixes below, all 21 workflow suites pass in fresh
nested sessions on the second GPU, against 0.3.0-rc.3 plus these tests.

- Card frames (10): polling is compared with an idle baseline; headless outputs
  on the second GPU render continuously (60 idle frames, 66 while polling
  either `hyprctl version` or Hyprflip status).
- Edit (14): status is compared once window motion settles (card frames follow
  animated positions); menu checks allow the actions added since; the Edit
  shortcut opens `--cards`; failure injection also covers attachments made
  through the batched focus call.
- Guided setup (7): the setup module gets `hypr.hyprflip-preferences`, which
  installs provide; five-app faces need an explicit "create"; batched
  attachments are injected too.
- hy3 Chill (8): pair-failure injection also covers `card`, which cores with
  native cards use.
- Layout (6): the overfill check fills the other face to the five-app limit.
- Containers (13): the scale/rotation rule is awaited; rules apply asynchronously.

## Full workflow regression for 0.3.0-rc.3 (2026-10-02)

All suites below ran in fresh nested sessions on the AMD iGPU of an
RTX 5090 desktop (`--aquamarine`, see below), against this release's core,
hy3 provider and helper.

Pass: dwindle (7), floating `--dwindle` (9), card interactions `--dwindle` (9),
unfold (5), fullscreen (13), native-card Chill (8), card interactions hy3 (9),
floating hy3 (9), native-pair integration (18, including GPU captures),
opening (6), repair (9), peek (19), three panes (9), workflows with
Hyprglass (10), card motion (5).

Fail identically on the pre-work baseline `3449c39`, run the same way, so they
are not regressions of this release: containers (the nested Wayland output
ignores the 1.6× scale/rotation rule), edit (status after a cancelled edit),
layout ("Cannot overfill the other face"), setup (the module test cannot
`require("hypr.hyprflip-preferences")` in a bare session), card frames (66
frames rendered during 40 idle status polls; limit 15) and the hy3 Chill
injected pair-failure check. Menu and portable workflows were not run: no
Fuzzel, Rofi or Wofi is installed.

## Keeping nested sessions out of the way

Each nested session is an Aquamarine window on your desktop, and it takes the
focus and the pointer when it opens. To run suites while you work, load
`tests/hidden-sessions.lua` from your Hyprland config (copy it to
`~/.config/hypr/test-sessions.lua` and add `require("hypr.test-sessions")`).
It sends every `aquamarine` window to the hidden `special:hftests` workspace
without focus, and keeps it drawing at 60 fps so screenshot and motion checks
still run. Toggle that special workspace to watch a session. Headless Sway and
Weston cannot replace the parent for the same reason as on NVIDIA below.

## Nested sessions on NVIDIA

Most workflow suites add a headless 4K output. On an NVIDIA desktop the nested
compositor allocates through the parent's NVIDIA GBM device, which cannot
allocate buffers for headless outputs: every mode is rejected and the output
stays 0×0. Third-party compositors cannot serve as the parent instead, because
Aquamarine 0.15 requires `xdg_wm_base` and `wl_compositor` version 6.

On a machine with a second (non-NVIDIA) GPU, build Aquamarine 0.15.0 with
`tests/aquamarine-render-node.patch`, which lets `AQ_TEST_RENDER_NODE` choose
the render node, and pass its build directory to the launcher. It is loaded
only by the nested compositor through `LD_LIBRARY_PATH`:

```sh
git clone --branch v0.15.0 https://github.com/hyprwm/aquamarine /tmp/aq
git -C /tmp/aq apply "$PWD/tests/aquamarine-render-node.patch"
cmake -S /tmp/aq -B /tmp/aq/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/aq/build
python3 tests/nested_session.py --directory /tmp/hf-dw --aquamarine /tmp/aq/build
```

The launcher picks the first non-NVIDIA render node (override with
`--render-node`) and Mesa's EGL vendor.

## Fullscreen editing, card fullscreen and native-card Chill (2026-09-30)

In a disposable nested session with only Hyprflip loaded,
`tests/fullscreen_workflows.py` passes 13 checks, adding: apps joining,
replacing and leaving a fullscreen card (marked by address); divider width 0/2/4
and color; and the `fullscreen` action keeping apps unaware (`fullscreenClient`
0) through flips and focus, with either toggle leaving and app sync restored.
An app moved in from another workspace also joined a fullscreen card without
ending fullscreen.

`tests/chill_card_workflows.py` passes 8 checks against Omachill 1.2 prepared by
adapter v2: native card workspaces are open to Chill while `protects_workspace`
still protects them for v1 engines; Chill floats the card at exactly 80% of its
tile with every app tagged; flip, unfold and fold keep the chilled frame;
tiling back restores the slot; a fullscreen card blocks Chill; chilled apps join
and leave a chilled card; unload releases every app. The adapter produces the
same engine from a pristine source and from a v1-patched one, and is idempotent.

`tests/chill_workflows.py` (hy3) passes its first five checks with the v1
engine; its injected pair-failure check fails identically on the previous
commit's code and helpers, so it predates these changes. 199 Python tests pass.

```sh
python3 tests/chill_card_workflows.py /tmp/hf-fs/session.json \
  --engine /path/to/chillmode-prepared-by-adapter-v2.lua
```

## Whole-card fullscreen (2026-09-30)

Native dwindle and floating cards fullscreen as a whole card. The new
`tests/fullscreen_workflows.py` passes all ten checks in a disposable nested
session with only Hyprflip loaded: the visible face fills the monitor with a
2px accent divider and no pane borders; keyboard focus and a real virtual
pointer reach every pane under all three `misc:on_focus_under_fullscreen`
policies, and fullscreen follows the focused pane; flip, all transitions,
peek, unfold and face layout changes run while fullscreen; leaving restores
the tile and its neighbor exactly; maximize fills the work area; floating
cards return to their frame; unloading releases every app. Native-pair
fullscreen transfer and the 183 Python tests also pass.

The headless-output dwindle/floating suites and the animated native-pair
suite could not run in that nested session (headless outputs reported 0×0 and
mid-turn frames did not present); both failed identically on the previous
commit. Screenshots of the fullscreen divider were inspected.

```sh
python3 tests/nested_session.py --directory /tmp/hf-fs
python3 tests/fullscreen_workflows.py /tmp/hf-fs/session.json \
  --protocol /path/to/matching/Hyprland/protocols/wlr-virtual-pointer-unstable-v1.xml
```

## Stock Omarchy installation and laptop unfolding (2026-09-23)

The published `v0.3.0-rc.1` source was freshly cloned and built, then its actual
core and helper installers ran in a new home with Omarchy 4.0.4's stock
configuration and default dwindle layout. Bubblewrap hid the live home and made
the host filesystem read-only; the test used private D-Bus, PipeWire, Wayland,
config, cache and state. Omarchy's session startup jobs were omitted and its
real Quickshell shell was started separately. No compositor plugins were loaded
initially, and only Hyprflip was loaded afterward.

All five installer workflows pass: stock startup; a non-mutating core dry-run
and successful installation; real Omarchy menu detection and conflict-free
helper bindings; guided creation, flip and unfold; naming/saving through real
menus and cold reopening of three new fixture processes. This validates a
fresh user configuration with installed host packages. It does **not** establish
a fresh OS installation or independent-user beta results.

The `rc.2` implementation passes the C++ constraint/animation suite,
179 Python tests, seven existing tiled workflows and nine floating workflows.
Five new real-compositor checks cover 1440×900 and 1280×800 with both Classic and
Card frame appearance, plus impossible-size refusal. Real GTK app minima make
the equal-half layout in `rc.1` fail; the new allocation fits both faces without
changing their pane proportions, and folding restores the exact geometry.
Maximum-size and fractional-boundary cases also run in the independent C++ suite.

On the live laptop, the updated core successfully unfolds Gmail / WhatsApp +
Telegram inside the existing 1420×854 card. Content widths are 586, 399 and 399
logical pixels, with unchanged gaps. All three apps accept input; folding,
process identities, saved-definition bytes and the other loaded plugin handles
are preserved. This replaces the `rc.1` laptop limitation recorded below.

Reproduce using a built source checkout and a fresh disposable session:

```sh
make test
python3 tests/nested_session.py --directory /tmp/hf-beta
# In another terminal, sequentially:
python3 tests/unfold_workflows.py /tmp/hf-beta/session.json
python3 tests/omarchy_install.py --directory /tmp/hf-stock \
  --source /path/to/clean-built-hyprflip --parent-session /tmp/hf-beta/session.json
```

The installer test additionally needs the installed Omarchy 4 package,
Bubblewrap, D-Bus, PipeWire, foot and wtype. The unfold test needs GTK4's Python
bindings and grim. Both tests clean up their own processes and preserve their
logs/results in the specified temporary directory.

Local evidence: `/tmp/hf-stock3/results.json`, `/tmp/hf-beta/unfold-results.json`,
`/tmp/hf-unfold-before.log`, `/tmp/hf-unfold-final.log`,
`/tmp/hf-dwindle-beta.log`, `/tmp/hf-floating-beta.log`, and
`~/.local/state/hyprflip/adaptive-unfold-20260923-174207/`.

## Native dwindle cards (2026-09-23)

The current source supports multi-app cards directly on the built-in dwindle
layout. Validation used Hyprland 0.56.2 with matching headers/compiler, private
nested-compositor configuration and test windows. The dwindle runs loaded only
Hyprflip, plus a test-only input probe for the pointer suite; no hy3 provider was
loaded. These automated suites use disposable windows and configuration.

- The **C++ core suite** and **179 Python tests** pass. New helper regressions
  cover native creation/editing, saved definitions, optional-provider detection,
  older hy3-only status, and a layout change between choosing and applying.
- **7 tiled workflows** pass: a real GTK minimum-size regression where adding
  a tile frees the space needed by the finished card; guided creation beside a neighboring tile;
  all transitions, peek and unfold without moving that neighbor; five apps on
  both faces and sixth-app refusal; workspace moves, edits, float/tile,
  fullscreen and reload; reopening a saved ten-app card with the same apps and
  unequal pane proportions;
  closing a hidden pane and releasing the remaining apps on unload.
- **9 floating workflows** pass on dwindle, including movement/resizing from
  either pane, edits, saved workspace destinations, cold launching and unload.
- **9 real-pointer checks** pass on dwindle: classic/frame appearance, compact
  and desktop gaps, drag cancellation, adding floating apps, actual GTK minimum
  size refusal with rollback, full-face refusal, unfolded targets and unload
  during a drag. Captures of tiled, unfolded and floating cards were inspected.
- Existing **18 native-pair** and **13 hy3-container** checks pass with the new
  core. The older container test now checks the advertised five-pane capacity
  instead of assuming three, and checks `hy3_provider` after provider unload.
- The documented `--native-cards` demo starts with three apps, dwindle, the
  core plugin alone and no configuration errors.
- **7 OmaCards native panel workflows** pass with the core alone on dwindle:
  flip, unfold/fold, naming/saving, hidden-face editing, persisted motion and
  preview return, opening an existing saved card, and cold reopening all three
  fixture apps. The preview panel also passes its offscreen rendering checks.

Reproduce in a fresh disposable session:

```sh
make test
python3 -m unittest discover -s tests -p '*_test.py'
python3 tests/nested_session.py --directory /tmp/hf-dw
# In another terminal, sequentially:
python3 tests/dwindle_workflows.py /tmp/hf-dw/session.json
python3 tests/floating_workflows.py /tmp/hf-dw/session.json --dwindle
python3 tests/card_interactions.py /tmp/hf-dw/session.json --dwindle \
  --protocol /path/to/wlr-virtual-pointer-unstable-v1.xml \
  --captures /tmp/hf-dw/captures
```

Local evidence is under `/tmp/hf-dw2/`, `/tmp/hf-dwdemo/` and `/tmp/hf-livefix/`,
with build and suite logs at `/tmp/hyprflip-dwindle-*.log` and
`/tmp/hyprflip-live-dwindle/`. This does not establish fresh OS installation or
automatic migration of live hy3 cards. Core-only updates require saving and
ungrouping active multi-app cards before installation.

### Live Omarchy trial

The preview core and helper were installed on the existing Hyprland 0.56.2
desktop with backups. Only workspace 8 was assigned to dwindle; the other
workspaces retained hy3, and the hy3 and Hyprglass libraries stayed loaded.
The saved Gmail / WhatsApp + Telegram card reopened as a native tiled group.

Eight checks cover the installed flip and peek callbacks, focus memory,
application size guards, pane proportions, whole-card floating resize/movement,
workspace moves and reload, the live OmaCards editor/library, and saved-card
reopening with unchanged app processes and saved definition. Synthetic keys
did not reliably trigger this desktop's bindings; the registered callbacks were
invoked directly. This is not a claim of physical-keyboard validation.

In `rc.1`, at the laptop's 1440×900 logical size, the real apps' minimum sizes prevent
unfolding all three together. The command leaves the folded card intact.
Unfolding is covered separately with fixtures that fit. Normal desktop resize
commands operate on the native card's outer tile; inner proportions use the
card layout API, including saved-card restoration.

Evidence and installer backups are recorded under
`/tmp/hyprflip-live-dwindle/` and `~/.local/state/hyprflip/dwindle-trial-20260923-153143/`.

## Portable helpers and app finder (2026-09-22)

Validated with Hyprland 0.56.2 in a disposable compositor with plain Lua
configuration, private helper/config/state paths and a private D-Bus session.
The host runs Omarchy; this is isolation evidence, not a fresh-distribution or
other-Hyprland-version compatibility claim. No renderer or provider code changed.

- **168 Python tests** pass, including backend detection, picker subprocess
  cancellation, stale app identity, native/container reveal, shortcut conflicts,
  installation and rollback.
- **Fuzzel 1.15.0, Rofi 2.0.0 and Wofi 1.5.3** pass real Wayland keyboard
  selection, free-text card naming and Escape cancellation. A stopped shell
  automatically selects Fuzzel. Pickers were unpacked under `/tmp` for these
  checks; no system packages were installed.
- A private freedesktop notification service verifies early notification-ID
  delivery, closing only the progress notification and the standard Cancel action.
- The helper installer successfully imports its modules without Omarchy's Lua
  bootstrap, registers the new bindings and preserves an existing three-app card.
  Real Fuzzel menus create and save the card; after all three sample apps close,
  saved opening launches fresh windows with one front app and two back apps.
- Find reveals the exact hidden pane, navigates from another workspace without
  moving the card, preserves unfolded/floating cards, and works with native pairs.
- Actual virtual-pointer input verifies that ordinary middle-click is untouched,
  modified middle-click flips once on release, and a drag beyond the configured
  threshold does not flip.

Reproduce the portable UI checks with Fuzzel, Rofi, Wofi, foot and wtype installed:

```sh
python3 -m unittest discover -s tests -p '*_test.py'
python3 tests/nested_session.py --directory /tmp/hf-port --containers
# In another terminal, with the disposable session still running:
XDG_RUNTIME_DIR=/tmp/hf-port/runtime dbus-run-session -- \
  python3 tests/menu_workflows.py /tmp/hf-port/session.json --picker-bin /usr/bin
XDG_RUNTIME_DIR=/tmp/hf-port/runtime dbus-run-session -- \
  python3 tests/portable_workflows.py /tmp/hf-port/session.json --picker-bin /usr/bin
python3 tests/notification_workflows.py
```

The portable workflow check closes and reopens only the disposable demo's three
sample apps. Use a fresh demo for each run. The notification fixture additionally
requires Python GObject (`python-gobject` on Arch); the production helper does not.

The helpers were then installed on the live desktop with a backup at
`~/.local/state/hyprflip/guided-setup-20260922-174900-660381/`. K and the optional
mouse shortcut register once, configuration errors are empty, and the exact
card state, plugin handles, compositor-library hashes and saved-card file hash
match the pre-installation snapshot.

## Pane reordering and replacement (2026-09-21)

C → Layout adds a direct two-app swap and directional three-app reordering.
Split sizes stay attached to positions, and focus stays with the same app.
C → Replace exchanges any pane with an open app while keeping the old app open.
The matching ABI 6 provider swaps existing leaf slots without dissolving groups.
Super+J retains its existing split-direction toggle.

- **111 Python tests and the C++ core test pass.** The 12 new helper tests cover
  every adjacent move in both directions, full/singleton faces, focused and
  unfocused replacement, unfolded cards, remote floating apps, cancellation,
  stale layouts and window identities, failed-import recovery, lost IPC replies,
  marks and unchanged saved definitions.
- **12 real compositor workflows pass** in `tests/pane_workflows.py`, with Auto
  Chill and the current Hyprglass enabled. They verify Super+J, unequal slot
  sizes, focus, exact geometry after replacement, closing released original
  front/back apps, folded/unfolded operation, malformed arguments, remote
  floating handoff and rollback including Chill tags. Real GTK minimum sizes
  exercise refusal when either the incoming app or the released app cannot fit.
  A replacement from an ordinary nested hy3 split retains its siblings,
  proportions and independent layout controls.
- All **nine saved-card repair workflows** pass with the new provider.
- All **six upgrade checks** pass in a fresh disposable compositor: installed
  ABI 5 → ABI 6, later six-pane updates, focus interference, fullscreen refusal,
  and failed-load recovery while Hyprglass stays loaded.
- **Five installed native-menu workflows** pass using temporary windows: direct
  swap, directional reordering of an unfocused app, Escape from replacement,
  replacement on a full side and singleton-face replacement. Four menu captures
  were inspected in one batch; the native controls and theme are retained.

Reproduce after `./scripts/build-containers`:

```sh
python -m unittest discover -s tests -p '*_test.py'
ctest --test-dir build/containers/core --output-on-failure
python tests/nested_session.py --directory /tmp/hf-pane
# In another terminal:
python tests/pane_workflows.py /tmp/hf-pane/session.json \
  --engine /path/to/integrated/chillmode.lua --hyprglass /path/to/hyprglass.so
python tests/repair_workflows.py /tmp/hf-pane/session.json
```

Evidence: `/tmp/hf-pane/pane-results.json`, `/tmp/hf-pane/repair-results.json`,
`/tmp/hf-up-pane/`, `test-results/container-upgrade.json` and
`/tmp/hf-pane-ui-check/`. Both disposable compositors were stopped. The native
check closed only its temporary windows and returned to the desktop view from
which it started.

The tested core/provider and helper are installed. Backups are under
`~/.local/state/hyprflip/container-update-20260921-194252/` and
`~/.local/state/hyprflip/guided-setup-20260921-194526-033342/`. The menu service
temporarily stopped answering IPC after the plugin update; its later ping and
helper-only retry succeeded, without repeating the plugin update. Eleven final
checks in `/tmp/hf-pane-installed/checks.json` confirm installed bytes, original
apps/workspaces, card membership and splits, saved definitions, configuration,
Super+J, the unchanged Hyprglass library/handle/mapping and feature availability.
The immediate post-upgrade snapshot preserves the original card selection too.
Later desktop focus, selected workspace and remembered back-pane focus changed;
these observations are recorded separately and were not overwritten. Omachill
and Omaglass regenerated their shell-owned configuration modules; other Hyprland
Lua files and the Super+J binding remained unchanged.

## Reopen missing apps in an existing card (2026-09-21)

C → Reopen missing apps now restores a partially intact saved card without
dissolving or rebuilding it. ABI 5 adds exact face layout snapshots and a guarded
arrangement operation; the existing launcher and cancellation flow are shared.

- **99 Python tests and the C++ core test pass.** The 13 new repair tests cover
  first/middle/last slots, multiple missing apps, original focus/unfold state,
  current survivor proportions, remote floats, matching-definition and
  same-class ambiguity, stale layouts, cancellation, timeout, import-time resize,
  partial attachment rollback, marks and return of imported floating apps.
- **Nine real repair workflows pass** in `tests/repair_workflows.py`, including
  repairs on both three-pane faces, multiple missing panes, folded/unfolded
  cards, unchanged surviving PIDs, remote reuse, invalid layout arguments,
  real-tree rollback after injected failure, cancellation with a late app and
  provider rollback when application minimum size rejects an arrangement.
- **Nine Brave/Chill/Hyprglass checks pass** with `tests/cold_open.py --repair`:
  three all-closed launches and six partial repairs, alternately closing the
  browser and terminal on the back. The repaired browser surface was inspected
  with all four edge markers visible.
- All **six existing layout checks** pass. All **six upgrade checks** pass in a
  fresh disposable compositor, including the installed ABI 4 → ABI 5 upgrade,
  future six-pane updates, focus interference, fullscreen refusal and failed-load
  rollback with Hyprglass kept loaded.
- **Four installed native-menu workflows pass** using temporary windows and an
  isolated saved library: direct missing-app launch, first-pane insertion with
  original focus, Escape from the setup chooser, and one explicit choice between
  matching saved variants. Editor and chooser captures were inspected together;
  existing Omarchy controls and theme remain unchanged.

Reproduce after `./scripts/build-containers`:

```sh
python tests/nested_session.py --directory /tmp/hf-repair
# In another terminal:
python tests/repair_workflows.py /tmp/hf-repair/session.json
python tests/cold_open.py /tmp/hf-repair/session.json --repair \
  --engine /path/to/integrated/chillmode.lua --hyprglass /path/to/hyprglass.so
```

Evidence: `/tmp/hf-repair/repair-results.json`, `/tmp/hf-repair/cold-open/`,
`/tmp/hf-repair/layout-results.json`, `/tmp/hf-up-repair/`,
`test-results/container-upgrade.json` and `/tmp/hf-repair-ui-check/`.
The upgrade suite uses its own fresh nested session. Both disposable compositors
were stopped, and the native check restored the original cards, workspaces and
focus. Test apps never use or close the user's real browser/chat windows.

The matching core/provider and helper are installed. Plugin backups are under
`~/.local/state/hyprflip/container-update-20260921-184405/`, and helper/config
backups under `~/.local/state/hyprflip/guided-setup-20260921-184458-347326/`.
The helper installer initially found a transient shell IPC timeout after the
plugin update; a subsequent ping and helper-only retry succeeded. The plugin
update was not repeated. Eleven final checks confirm the installed bytes,
existing card/app identities, focus, workspaces, saved definitions, unchanged
Hyprglass handle/mapping, feature availability and clean configuration.
Final installation evidence is in `/tmp/hf-repair-installed/`.

## Direct card launcher and saved-card management (2026-09-21)

Selecting a saved card now opens or switches to it immediately. The native
searchable launcher is also available directly on Super+Ctrl+Alt+L; C retains
the card editor. Optional app/launcher review and manual restore are under
Manage saved cards. C → Manage card adds Update, Rename and Duplicate.

- **86 Python tests pass.** New checks cover one-selection opening, remote and
  floating app descriptions, empty-library guidance, existing-card navigation,
  in-place saved updates after resize/face transfer, remembered launchers,
  ambiguous saved variants, naming cancellation, stale card/definition refusal,
  atomic rename failure, concurrent source/destination edits and the 100-card
  limit. Installer checks include conflicts on L and exact-file rollback.
- **Six real compositor workflows pass** in `tests/opening_workflows.py`:
  missing-app launch/reuse/import, existing-card focus, layout update without
  retyping its name, Duplicate/Rename/Delete without touching running windows,
  late-app cancellation and launcher timeout.
- **Three all-closed Brave card launches pass** through the direct path in
  `tests/cold_open.py`, with Auto Chill and the current Hyprglass build enabled.
- **Seven native-menu checks pass** with temporary app windows and a separate
  test library: empty-library saving, search/direct switching, Update, Duplicate
  and Rename, Escape during naming, optional review cancellation and direct
  all-closed launching using the updated layout. The empty, running/closed
  launcher, management, naming and review screens were inspected together;
  the existing Omarchy theme and controls were retained.

Evidence is under `/tmp/hf-library/cold-open/`,
`/tmp/hf-library/opening-results.json` and `/tmp/hf-library-ui-check/`.
The native test restored the original cards, workspaces and focus.

The helper and L binding are installed. Eight post-install checks confirm helper
bytes, existing card membership/state, saved definitions, focus, plugin handles,
library bytes, clean config and the registered L binding. No compositor library
was replaced or unloaded. Backups are under
`~/.local/state/hyprflip/guided-setup-20260921-175951-194864/`; installation checks
and logs are under `/tmp/hf-library-installed/`.

## Saved-card cold-start fix (2026-09-21)

Opening a saved Gmail / WhatsApp + Telegram card with all three apps closed
could silently stop before grouping. The helper queried clients, then focus;
a browser window mapping between those replies looked like unrelated user
navigation. Cancelling released the workspace reservation, so Auto Chill
floated the three separate apps. The saved front/back definition was intact.

The helper now observes focus before collecting clients and allows a newly
mapped window time to acquire its startup identity. Only uniquely matched
windows can enter the card. Focusing a pre-existing unrelated app, moving to
an empty workspace, clicking Cancel or starting another menu still stops the
operation. Final focus and stale-window checks remain in place.

- 72 Python tests pass, including deterministic mapping between IPC replies,
  delayed startup identity, unrelated existing/new windows and workspace
  navigation. Both startup regressions failed before the fix.
- `tests/cold_open.py` reproduced the cancellation on the first pre-fix run
  with two real Brave app windows sharing an isolated profile and a Foot pane.
  With the fix, three consecutive all-closed launches rebuilt the saved
  one-front/two-back card with Auto Chill and the installed Hyprglass build
  enabled. Captures of both faces show complete browser surfaces after resize.
- All four existing `tests/opening_workflows.py` checks pass: reuse/import,
  focusing an already-open card, cancellation with a late app and launch timeout.

```sh
python tests/nested_session.py --directory /tmp/hf-reopen
# In another terminal; both optional integrations are copies inside the fixture:
python tests/cold_open.py /tmp/hf-reopen/session.json \
  --engine /path/to/integrated/chillmode.lua --hyprglass /path/to/hyprglass.so
python tests/opening_workflows.py /tmp/hf-reopen/session.json
```

Evidence: `/tmp/hf-reopen/cold-open/{results,trace}.json`, the front/back PNGs
in that directory, and `/tmp/hf-reopen/opening-results.json`. Browser tests use
local HTML and a temporary profile; they do not close the user's applications.

The live helper update preserved the existing card, plugin handles and focus;
configuration validation passed. Helper/config backups are in
`~/.local/state/hyprflip/guided-setup-20260921-173641-315436/`.
The three already-open user apps were restored to Gmail in front with WhatsApp
and Telegram behind, and both faces were visually checked. No compositor
library was changed or unloaded, and no rendering patch was needed for the
restored card. The clipping seen while the apps were left floating was not
independently reproduced or attributed to a renderer.

## Saved-card opening and face layout checks (2026-09-21)

This milestone adds explicit app launching to saved cards and ABI 4 face edits.
The desktop remains on the pinned Hyprland 0.56.2/hy3 combination.

- 67 Python tests cover launcher precedence/hidden entries, ambiguous matching,
  malformed desktop IDs, changed launcher files, duplicate prevention, stale
  windows, cancellation, request-lock handoff, launch failure and timeout,
  alongside existing setup/editor/install/rollback coverage. The C++ core test passes.
- `tests/opening_workflows.py` exercises real GIO desktop-entry launches in a
  disposable compositor. Four checks cover reuse/import and missing-app launch,
  already-open cards, cancellation with a late-arriving app, and a launcher that
  exits successfully without creating a window.
- `tests/layout_workflows.py` checks directions and unequal proportions, equal
  sizing, unfocused pane transfer and remembered focus, unfolded editing, both
  capacity limits, positive weights after very unequal transfers, application
  minimum-size refusal and exact geometry rollback with unequal unfolded faces.
- Six upgrade checks passed from the installed ABI 3 build to ABI 4 with the
  current Hyprglass kept loaded. They include multiple/six-pane cards, native
  pairs, focus races, fullscreen refusal and a forced load failure with rollback.
- The six-app saved-card suite passed across two real disposable compositor
  processes, including both axes, proportions, focus, cross-workspace import,
  injected partial failure, Chill geometry/tag recovery and successful retry.

Reproduce the new workflows after `./scripts/build-containers`:

```sh
python tests/nested_session.py --directory /tmp/hf-open
# In another terminal:
python tests/layout_workflows.py /tmp/hf-open/session.json
python tests/opening_workflows.py /tmp/hf-open/session.json
```

Evidence: `/tmp/hf-open/layout-results.json`,
`/tmp/hf-open/opening-results.json`, `/tmp/hf-open-restart/`,
`/tmp/hyprflip-open-upgrade.log` and `/tmp/hyprflip-opening-unit.log`.
Tests copy the built libraries before loading; they never replace a mapped
library in place or restart the real desktop.

The installed native Omarchy menu passed five workflow checks with temporary
Gmail/WhatsApp/Telegram test windows: layout selection, moving the unfocused
pane, cancelling the launch review, launching the missing app and rebuilding
the card, and clicking the progress toast to cancel while Do Not Disturb is
enabled. The editor, layout/move submenus, launch review and progress toast
were inspected together. All controls and copy fit the existing native theme.
Captures and results are in `/tmp/hf-open-ui-check/`.

Installation preserved the existing live card. Library backups are under
`~/.local/state/hyprflip/container-update-20260921-165455/`; helper/config backups
are under `guided-setup-20260921-165534-328422/` in the same directory. Hyprglass
remained loaded and its file did not change. No compositor restart was needed.
The installed core SHA256 is
`3f8b6b78d256c027ab3408a5f99184ad810bed6927d9efe1eb4e47cf1ade7423`;
the ABI 4 provider is
`74b9e149187ea63589ece5c4bb34b89bc9952e855779044db3debd47a1e0bccb`.

## Saved-card and peek checks (2026-09-21)

Checkpoint `7f2de93` contains the preceding multi-app container, transition and
Chill work. The next change adds named saved arrangements and hold-to-peek.

- 54 Python tests cover the existing setup/editor/installer plus saved-card
  cancellation, duplicate names, concurrent updates, corrupt files, atomic
  write failure, stale windows, changed focus, ambiguous matches and review.
  They also reject invalid targeted actions before mutation and verify that
  losing compositor IPC restores the previous library files without hiding
  the original error behind focus-cleanup errors.
- `tests/saved_restart.py` starts two separate disposable compositor processes.
  It saves a six-app card with different split axes and unequal proportions,
  restarts the compositor, opens fresh app processes, and restores the card
  from other workspaces. All memberships, proportions and remembered focus
  match. Further checks restore from Chill, inject a failure after partial
  grouping, recover floating geometry/workspaces/tags, and delete a saved
  definition without dissolving its running card.
- Six container-upgrade checks preserve multiple cards, six-pane proportions,
  native pairs, workspaces and focus, reject fullscreen interference, and
  recover from a failed plugin load. Forced focus changes between IPC requests
  now exercise both the updater and saved-card helper. Both select, verify and
  act in one Lua callback, with mark and pair/attach kept together.
- `tests/peek.py` passes 19 checks: every transition in both directions, early
  reversal, an actual synthetic key press/release with modifiers released first,
  typing, focus, unfold, workspace changes, config reload, a real GTK popup,
  pane closure, virtual monitor removal during Portal, virtual DPMS off/on,
  unload while holding, and native two-window pairs.
- The existing native suite passes all 18 lifecycle checks against the new
  core. The standalone C++ core test passes too.

Commands (after building):

```sh
python -m unittest discover -s tests -p '*_test.py'
ctest --test-dir build --output-on-failure
python tests/peek.py /tmp/hf-test/session.json
WAYLAND_DISPLAY=/run/user/1000/wayland-1 XDG_RUNTIME_DIR=/run/user/1000 \
  python tests/saved_restart.py --results /tmp/hf-saveproof \
  --engine /path/to/integrated/chillmode.lua
```

Use a fresh results directory for the restart test. It creates and stops its
own nested compositors and never restarts the real desktop. Omitting `--engine`
checks ordinary floating apps instead of Chill-tagged apps.

Evidence from this run is in `/tmp/hf-saverace/`,
`/tmp/hf-peek/peek-results.json`, `/tmp/hf-peek/native/integration.json` and
`/tmp/hyprflip-focus-unit.log`. Upgrade evidence is in
`/tmp/hyprflip-updater-fix-test.log` and `test-results/container-upgrade.json`.
The tested core SHA256 is
`7e0a6116f66acff17ca7236b548672e888aba685884022e99d5d31513b967caa`;
the unchanged ABI 3 provider is
`2fa46bc9dc6da8ca19aa986a540ea5c3b54d56e4bc11804df8b88fdeedc5cdb6`.

The synthetic keyboard uses `input.resolve_binds_by_sym=true` only inside its
test configuration. The physical desktop's resolver setting is retained.
Geometry changes legitimately trigger the existing instant-switch fallback;
the hotplug test settles both faces before requesting an animated turn.
GPU tests use a headless output so hiding the parent nested window cannot stop
their presentation loop. Native regression screenshots target the tested
output, and workspace return uses the actual starting workspace.

The DPMS check uses the current
[Lua dispatcher](https://wiki.hypr.land/configuring/core/dispatchers/).
Virtual hotplug and output power checks are not evidence of a physical monitor
reconnection or real system suspend/resume; those remain hardware checks before
a wider release.

After the user unlocked the desktop, four native menu checks passed: saving a
named three-app card, cancelling the restore review, restoring it, and deleting
the saved definition without dissolving the running card. Screenshots of the
edit menu, name entry and restore review were inspected. Temporary fixture apps
were closed and the user's cards were preserved. Evidence is in
`/tmp/hf-saved-ui-confirm/`; subsequent focus-guard changes leave the UI intact
and passed the restart/workflow suite again.

An initial live installation attempt rolled back after
marking an already grouped window; the guarded-focus fix above addresses that
race. The retry crashed while unloading the old core, before copying either new
library. Analysis found a stale Hyprglass decoration deletion callback into a
previously unloaded library. See [the crash analysis](docs/UNLOAD_CRASH_2026-09-21.md).

After the user confirmed concurrent Hyprglass work and later resumed this task,
installation completed at 16:08–16:10. Configuration was clean, Hyprglass matched
the compatibility-test library, and its loaded handle remained unchanged through
the update. The core, provider, menu helper and Lua bindings match the tested
files byte for byte. O, C and Space each register exactly once.

The existing workspace 2 card (Gmail opposite WhatsApp + Telegram) retained its
members, visible face, focused pane, sizes and positions. An installed peek
round trip revealed the other face and returned to the original pane. All
monitor workspaces and desktop focus were restored, with no configuration errors.
Evidence is in `/tmp/hyprflip-saved-installed-check.json`,
`/tmp/hyprflip-saved-install-resumed.log` and
`/tmp/hyprflip-saved-setup-resumed.log`. Backups are
`~/.local/state/hyprflip/container-update-20260921-160853/` and
`~/.local/state/hyprflip/guided-setup-20260921-160955-712179/`.

## Tested environment

The 0.1.1 implementation was built against Hyprland 0.56.2 (`efb50993780079460b0cbed1363e2166a2de1d9f`) with GCC 16.2.1. Compositor tests ran in a disposable Wayland-nested session with temporary configuration, followed by installation and daily use on a desktop running the same ABI.

The lifecycle suite passed **18 checks**, and the compatibility suite passed **7 checks**. Separate tests exercised two Brave application windows and an upgrade from a config-loaded 0.1.0 library to 0.1.1.

| Area | Checked behavior |
| --- | --- |
| Core motion | Reversal, midpoint crossing, stalled/negative time, smooth endpoints, projection bounds and inverse mapping |
| Pairing | Mark/cancel, invalid pairing, native group creation, exclusive active input |
| Repeated turns | 16 animated flips preserve position and size |
| Interruption | Keyboard input, external focus, workspace changes, config reload and unload |
| Lifecycle | Unpair, external group removal, member closure, surviving window access |
| Native state | Floating pairs and fullscreen transfer |
| Applications | Wayland/XWayland GTK windows and two Brave windows using local pages |
| Popups | Popover/grab fallback and rejection of modal children |
| Output mapping | Fractional scale 1.6 and transforms 0, 1 and 3; both faces captured and inspected |
| Hyprglass 1.0 | Temporary opt-out during turns and restoration of original tags |
| Upgrade | Exact group adoption preserves geometry, focus and current side; invalid adoption rejected |
| Configuration | Five shortcuts registered; key releases preserve animation; callbacks remain safe after unload |

## Running the checks

```sh
make test
python -m unittest discover -s tests -p '*_test.py'
```

The Python installer tests use temporary files and mocked IPC. They do not touch a running compositor. GitHub Actions runs these tests, the independent C++20 timeline/projection test and syntax/manifest checks. It does not compile the full plugin or run GPU integration tests; those need matching Hyprland development headers and a Wayland session.

For the compositor tests, open a separate terminal:

```sh
python -u tests/nested_session.py --directory /tmp/hf-test
```

Then run the suites one at a time against that connection file:

```sh
python tests/integration.py /tmp/hf-test/session.json
python tests/compatibility.py /tmp/hf-test/session.json \
  --hyprglass /path/to/hyprglass.so
python tests/browser.py /tmp/hf-test/session.json
python tests/motion.py /tmp/hf-test/session.json
```

Omit `--hyprglass` when it is unavailable. Compatibility checks need GTK4/PyGObject and XWayland; browser checks need Brave. The session needs GPU access, a visible parent Wayland compositor, Foot, Grim and wtype. Keep the parent display awake for rendering measurements. Use a short `/tmp` path because Unix socket names have a length limit. Ctrl+C in the launcher cleans up its children.

The harness disables physical display/session access and test clients use temporary configuration. JSON reports and captures go into ignored `test-results/`. Inspect screenshots as well as automated geometry checks. Do not rebuild or overwrite a library mapped into a compositor; unload it or load a separate copy first.

With an older local build available, these optional regression checks compare versions:

```sh
python tests/motion.py /tmp/hf-test/session.json --baseline /path/to/old/hyprflip.so
python tests/config_upgrade.py /tmp/hf-test/session.json --baseline /path/to/0.1.0/hyprflip.so
```

Before a release, `tests/key_suites.py` starts its own sessions and runs every suite that loads the shipped key modules, each in a fresh one (CONTRIBUTING.md, Releases):

```sh
python tests/key_suites.py --hyprglass /path/to/hyprglass.so
```

## Motion measurements

An initial comparison used identical 600 ms durations and 12 turns per version on the same nested output. Mean mismatch between pose advancement and render timestamps fell from 0.90 ms to 0.06 ms after moving from an 8 ms timer to render-cycle sampling. The 95th percentile fell from 2.18 ms to 0.37 ms. Median render intervals remained about 33.4 ms in both versions; 95th percentile CPU render duration changed from 3.86 ms to 4.28 ms.

These are development measurements of pose sampling and CPU render timing, not GPU execution or physical scanout. Only the console summary of that initial run was retained; rerun the supplied probe to obtain per-frame data. Reduced timing jitter does not establish higher frame rates, and additional texture filtering costs rendering work.

## Card lighting and reversal polish

On 2026-09-21, the animation update passed the C++ core test, **17 Python
unit/installer tests**, **5 card motion checks**, **7 compatibility checks**,
**18 native lifecycle checks**, **13 container checks**, **10 movement/unfold
checks** and **4 container upgrade checks**. Compatibility, workflows and
upgrade tests included the installed Hyprglass 1.0.0 library. Both the default
and experimental core builds compiled against the tested Hyprland ABI.

The core tests now verify that reversals preserve angle and angular velocity,
settle on the requested face, and follow the same trajectory with coarse or
fine time steps, including near endpoints. Ordinary turns retain their original
duration and symmetric quintic curve.

The new card suite compares one- and two-pane backs, including unequal splits,
at 3840×2160/60 Hz, scale 1.5 and transforms 0 and 1. Four ordinary 420 ms turns
per arrangement were measured separately from captures and unfolding. It also
checks reversal before/near/after the edge, repeated retargeting, exclusive input,
focus, unfold/refold and instant switching with animation disabled.

```sh
python tests/card_motion.py /tmp/hf-test/session.json \
  --plugin /path/to/previous/hyprflip.so \
  --output test-results/animation-before --captures
python tests/card_motion.py /tmp/hf-test/session.json \
  --output test-results/animation-after --captures --require-redraw
```

| Output / back panes | Render interval median, before → after | CPU render p95, before → after |
| --- | --- | --- |
| Landscape / 1 | 16.75 → 16.73 ms | 2.10 → 2.08 ms |
| Landscape / 2 | 16.75 → 16.74 ms | 2.10 → 2.09 ms |
| Portrait / 1 | 16.75 → 16.75 ms | 1.96 → 1.74 ms |
| Portrait / 2 | 16.73 → 16.74 ms | 1.96 → 2.01 ms |

These figures exclude the first turn from steady timing statistics. First-turn
CPU maxima ranged from 3.97–22.65 ms before and 18.13–28.19 ms after. The work
within those first frames was not separately profiled; this does not establish
that a cold turn always fits the 16.7 ms frame budget. A separate 12-turn native
pair comparison at 600 ms measured render-interval p95 of 21.25 → 21.21 ms and
CPU-render p95 of 4.40 → 4.80 ms. These runs do not establish a frame-rate gain.

The probe did confirm a redraw scheduling defect. At `RENDER_POST`, Hyprland
has already cleared the renderer's monitor reference. Using a weak monitor
reference captured at `preChecks` fixes the next-frame request. The new assertion
passed on every active turn frame in all four arrangements; the baseline
requested none of those frames in three arrangements. The headless backend
still rendered at roughly 60 Hz in both versions, which is why render intervals
alone did not expose the missing request.

Representative outgoing, near-edge, incoming, resting and unfolded captures were
inspected together on landscape and portrait outputs. The two back panes share
the light field, resting colors match the baseline, and the compatibility images
show correctly oriented GTK content at transforms 0, 1 and 3 with scale 1.6.
The lighting changes only RGB inside the existing pass; it adds no texture read,
framebuffer or idle animation. Unfold/fold retains the native layout animation
path. Its focus and final geometry are checked; the sampled IPC boxes do not
measure its per-frame visual easing.

Raw frame records, capture state and PNGs are retained locally under ignored
`test-results/animation-before`, `animation-after`, `animation-compatibility`,
`animation-lifecycle`, `animation-containers` and
`animation-native-motion.json`. Capture timing is approximate and screenshots
are not a substitute for a continuous scanout measurement. All measurements
describe this disposable GPU-rendered compositor, not physical display latency.

The tested build was then installed on the live Omarchy desktop. Post-update
checks confirmed matching library bytes, all three plugins loaded, no config
errors, and the existing Gmail/WhatsApp/Telegram card's membership, active face,
pane geometry, workspaces and input state preserved. Active window and monitor
workspaces also matched the pre-update snapshot. The disposable compositor was
closed. This installation check did not trigger a flip of the user's card.

## Limits

- Dwindle is the tested layout. Other layouts, HDR/color management and individual-window capture need validation.
- Fractional/rotated behavior was tested in a nested output. Physical hot-unplug, suspend/resume and session-lock interruption were not end-to-end tested.
- Pointer, touch and tablet interruption handlers are implemented; only keyboard interruption was automated.
- Long-running GPU/memory stress, dynamically changing size constraints and unusual transient windows need more coverage.
- Hyprglass's independent background is not projected; its original material returns after the turn.
- Browser tests use local pages. No logged-in ChatGPT session is required or exercised.
- Pairs survive config reloads and installer upgrades, but not manual unload or compositor restart.
- The direct installer and manual plugin loading were tested; end-to-end hyprpm installation has not been exercised.

For a desktop crash, inspect the actual core/backtrace before attributing it to a plugin. Report the relevant evidence and triggering action, not a raw core dump.

## Optional container experiment

The hy3 experiment uses separate binaries built by `./scripts/build-containers`.
On 2026-09-20, the same Hyprland 0.56.2/GCC 16.2.1 environment passed **13 container
checks**, **18 native lifecycle checks**, **6 native compatibility checks**, the
independent C++ core test and all **4 installer tests**. The fresh-checkout build
script, wrong-revision rejection, Python/shell syntax and C++ formatting were
also checked. Hyprglass was not included in this experiment's compatibility run.

```sh
./scripts/build-containers
# Start tests/nested_session.py in another terminal as described above.
python tests/containers.py /tmp/hf-test/session.json
python tests/integration.py /tmp/hf-test/session.json \
  --plugin build/containers/core/hyprflip.so
```

The container suite exercises real Wayland terminals: both split axes, the
two-pane limit, outside window placement, per-face focus, release, whole-card
workspace moves, repeated motion, reversal, input/focus interruptions,
fullscreen, config reload, close, external tree edits, and both plugin unload
orders. It captures split faces at rest, across the midpoint, and on an output
with scale 1.6 and transform 1. It waits for a subsequent frame after unload to
catch retained-render-object lifetime failures.

An initial provider-unload run exposed a SIGSEGV in
`Render::CRenderPass::clear()`: a retained hy3 pass had a deleter in the unloaded
library. The provider exit wrapper now removes its pass elements before calling
upstream's exit function. Both active-turn and idle unload/reload checks then
passed with actual `dlclose` enabled. This happened only in the disposable test
compositor; the live desktop library was not replaced.

Later on the same day, **5 workspace trial checks** passed with the installed
Hyprglass 1.0 library. Native dwindle pairs and a workspace-8-only hy3 layout
coexisted; real mark/pair/flip and attach/release shortcuts worked; container
animation temporarily suppressed and restored Hyprglass; reload preserved both
backends; and unpair left all panes accessible. The new check uses the example
trial configuration and copies all loaded libraries into its disposable session:

```sh
# Build both the default core (make) and the container provider first.
python tests/trial.py /tmp/hf-test/session.json --hyprglass /path/to/hyprglass.so
```

The `--all-workspaces` variant passed **9 checks** on the same day. It also
checks converting an existing tiled native pair, preserving a pre-existing
container, overriding saved layouts, creating new workspaces, leaving special
scratchpads on dwindle, moving a whole card and reloading the expanded config.
Native pairs are separated before changing layout and re-paired afterward:
ungrouping after switching exposed an expired hy3 target in the disposable
session. Cleanup unloads Hyprglass last; removing all three libraries in one
parse exposed a separate crash during hy3 layout removal after Hyprglass had
unloaded. The staged cleanup passed. Neither failure was on the real desktop.

The movement/unfold milestone passed **10 workflow checks**, **4 upgrade checks**,
the **13 container checks**, **18 native lifecycle checks**, the C++ core test and
**5 installer tests** on 2026-09-20. Both new suites included Hyprglass 1.0. They
used GPU-rendered headless outputs inside the disposable compositor; the movement
suite added a second output at scale 1.6 with transform 1. Screenshots of unfolded
cards were also inspected.

```sh
make
./scripts/build-containers
python tests/workflows.py /tmp/hf-test/session.json --hyprglass /path/to/hyprglass.so
python tests/container_upgrade.py /tmp/hf-test/session.json \
  --baseline-core /path/to/previous/hyprflip.so \
  --baseline-provider /path/to/previous/libhy3.so \
  --hyprglass /path/to/hyprglass.so
```

Workflow checks cover the exact registered number-row callbacks, directional
reordering and edge behavior, follow/silent focus, cross-output moves, two-to-four
live panes, the actual unfold key chord, unchanged outer footprint, unequal inner
ratios, focused-face refolding, opposite-face folding, release/unpair, reload and
fullscreen guards. A GTK client with a real 900×550 minimum rejects an unfold that
cannot fit. These checks do not establish the size behavior of every application.

Upgrade checks cover read-only dry runs, a fullscreen window blocking restoration,
old-ABI upgrades preserving multiple cards and a native pair, and deliberate load
failure with rollback of both libraries and folded/unfolded cards. During desktop
installation, a fullscreen screensaver initially blocked focus; rollback restored
the old cards. The updater now checks covering fullscreen windows before unloading
and waits for the intended application to receive focus before each restore step.
The subsequent desktop upgrade preserved both existing cards and loaded the new
shortcuts with no config errors.

A final desktop check used three disposable terminals on empty workspaces and
passed unfold/refold plus follow/silent moves between physical landscape and
portrait monitors, both at scale 1.5. It restored the user's existing cards,
workspaces and focus. This check invoked the installed Lua actions: the live
desktop resolves physical keycodes, whereas wtype supplies a custom virtual
keymap. The isolated workflow suite verifies the actual O chord with symbol
resolution enabled and separately checks the installed binding registrations.

Container-specific limits remain: no daily-use soak test, physical hot-unplug,
mixed Wayland/XWayland containers, broad application-specific minimum-size stress
or individual-pane capture validation. Native compatibility results do not
establish those container cases.
See [the experiment guide](docs/CONTAINERS.md) for scope and setup.

## Guided setup

On 2026-09-21, guided creation passed **17 unit/installer tests**, **7 disposable
compositor checks** and **4 live menu checks** on Omarchy 4 / Hyprland 0.56.2.
No compositor source or libraries changed for this feature.

```sh
python -m unittest discover -s tests -p '*_test.py'
python tests/setup_workflows.py /tmp/hf-test/session.json
python scripts/install-setup.py --dry-run
```

The isolated suite covers cancellation at both stages without changing real
windows or a pending mark, one- and two-app backs finishing folded on the front,
ungrouping and recreating, the shipped O callback's two paths, stale selections,
rollback after a refused attachment, and successful creation even when application
minimum sizes prevent a later unfold. Unit checks also cover duplicate titles, control characters, literal
title transport, superseded requests, shortcut conflicts and installer rollback.

The real Omarchy menu was exercised with disposable terminal fixtures on empty
workspaces. Keyboard selection created both two- and three-window cards, already
folded with the front focused and the back excluded from input; Escape
at either stage preserved their layout. The actual portrait and landscape menus
were captured and inspected together. Test windows closed afterward and the
user's original cards, workspaces and focus were restored. This menu test invoked
the helper directly; the installed O registration and its actual Lua callback
are checked separately, since the desktop resolves physical keycodes while wtype
supplies a different virtual keymap.

The wording/completion refinement was rechecked with the same 17 unit/installer,
7 isolated workflow and 4 live menu checks. The revised choices read **Only one
app** and **Add [app name]**. During this smoke test, the shell's default two-second
IPC timeout expired after opening the test windows. The test process used
`OMARCHY_SHELL_IPC_TIMEOUT=5s` and completed; the user's shell timeout was unchanged.

## Editing existing cards

On 2026-09-21, the Omarchy card editor passed **26 unit/installer tests**,
**8 disposable editor workflow checks**, the existing **7 guided creation
checks**, and **9 real menu checks** on the desktop's portrait and landscape
monitors. It uses the existing attach/release actions; no compositor source or
libraries changed.

```sh
python -m unittest discover -s tests -p '*_test.py'
python tests/setup_workflows.py /tmp/hf-test/session.json
python tests/edit_workflows.py /tmp/hf-test/session.json
python scripts/install-setup.py --dry-run
```

The editor suite exercises real front/back attachment, focus on the selected
app, per-face focus memory, the two-app limit, releasing a companion, four-pane
unfolded editing, explicit ungrouping when a side has only one app, cancellation
at both menus, and stale selections after app movement or a flip. A real GTK
minimum-size constraint rejects an attachment; the existing card, original mark
and focus survive. The actual C chord invokes the shipped callback and captures
the focused address for `--edit`; O still unfolds directly. The nested test
enables symbol resolution for wtype and intercepts the command dispatch instead
of opening the desktop's menu from the disposable compositor.

Unit checks additionally cover changed window identity, ownership, fullscreen,
workspace/focus changes, native-group guidance, empty candidate lists and both
shortcut conflicts. Creation and editing share the request lock, so a newer
request supersedes a waiting picker. Installer rollback and repeat installation
remain covered.

The live menu check used three disposable terminal fixtures on empty workspaces.
Keyboard selection added a Telegram-labeled fixture to the WhatsApp side, removed only
that fixture, and explicitly ungrouped the remaining card, on both display
orientations. Escape preserved the layout and active side. Action, app-picker
and full-side menus were captured and inspected together. These checks ran the
helper directly; the installed binding registration is verified separately.
No real messaging account was used. The fixture processes closed afterward and
the user's existing card, active window and monitor workspaces were restored.
The test process used the previously established five-second Omarchy shell IPC
timeout; the user's timeout was unchanged.

Reports are retained in ignored `test-results/edit-workflows.json` and
`test-results/edit-menu.json`; menu captures are in `/tmp/hyprflip-edit-ui/`.

The helper and Lua module were then installed and matched the tested files.
C and O each registered once, with no configuration errors or changes to card
membership, active face, geometry, plugin handles or library hashes. The reload
changed the focused monitor while retaining the active window and all visible
workspaces in the first check. The active window subsequently changed before a
guarded focus restoration could run, so the check left the newer focus alone.

## Either-pane removal and workspace picker

The follow-up editor changes passed **32 unit/installer tests**, **14 editor
workflow checks**, **7 creation checks** and **10 movement/unfold checks** on
2026-09-21. The movement suite included Hyprglass. Compositor libraries were
unchanged; the update is in the shared Python picker.

The full-side menu now offers both apps, identifies the focused one, and retains
the original focus when removing its companion. Both C editing and O creation
list local apps first, then numerically sorted workspace submenus. Back and
Escape do not move windows. App identity, original workspace and card state are
rechecked before the first move. Existing cards, native groups, floating windows
and special workspaces remain excluded from candidates.

The expanded editor suite imports an ordinary app from dwindle on a separate
output at scale 1.5 and transform 1, without switching that output away from its
source workspace. Folded and unfolded cards are covered. Guided creation imports
two apps from different workspaces. An injected creation failure returns both;
a real size-limit rejection during editing returns its imported app while
preserving the original card. Workspace return does not recreate the exact
source tiling tree. Named-workspace recreation and physical hotplug during a
picker operation were not tested.

The GTK fixture now constrains its content before presenting the window. A
Wayland trace confirmed `set_min_size(930, 580)` for its 900×550 content plus
margins, retained in `test-results/gtk-minimum-protocol.txt`. Earlier size-limit
reports relied on a later request that this GTK build did not advertise; the
new creation, editing and unfold checks supersede that minimum-size evidence.

The real Omarchy menu then passed **7 desktop checks** using temporary apps on
empty workspaces. Both monitor orientations showed local apps before workspace
entries, allowed importing a Telegram fixture from workspace 4, and offered
removal of either app while retaining WhatsApp focus when Telegram was removed.
Cancelling the workspace submenu left the source app in place. A separate
creation flow imported its back and finished folded on the front. Menus were
captured and inspected together; results are in `test-results/remote-menu.json` and images in
`/tmp/hyprflip-remote-ui/`. Test windows closed and the user's existing card,
workspaces and focus were restored. As before, only the test helper process used
the five-second Omarchy shell IPC timeout.

Only the tested helper was atomically replaced for this update, with its previous
version backed up. Existing C/O bindings already load that file. Installation
checks confirmed unchanged card state, focus, monitor workspaces, plugin handles,
library bytes and configuration bytes, with no reload or configuration errors.
The result is retained in `test-results/remote-install.json`.
## Three apps per face — 21 September 2026

The ABI 3 container build supports three live tiled applications per face, in
one horizontal or vertical split. This limit belongs to Hyprflip's bridge; hy3
supports larger groups. Adding the third application preserves the existing
split direction and relative pane weights. The setup helper reads the capacity
from status and retains the two-app limit with older providers.

Validation for this extension:

- C++ core tests and all **35 Python tests** passed.
- `tests/three_panes.py`: **9 checks** with Hyprglass, covering three apps on
  both faces, both output orientations, preservation of axis and proportions,
  rejection of a fourth app, focus for every pane, all three removal positions,
  workspace movement, six-pane unfolding, optional third-app setup, remote
  imports, hidden-window closure, and a real application minimum-size refusal
  that returns the candidate to its original workspace. Three-app unfolding
  arranges rows above one another or columns beside one another; a tall GTK
  window also exercises the minimum-size fallback to the alternate axis.
- Existing editor (**14**), guided setup (**7**), movement/unfold (**10**) and
  container lifecycle (**13**) checks passed. Guided setup now also injects a
  failure on the third app after the second has attached successfully; the new
  card is dissolved and the imported app returns to its source workspace.
- Upgrade tests: **5 checks**, including ABI 2 to ABI 3, subsequent upgrades
  with uneven three-pane splits on both faces, and a deliberately invalid core
  that rolls back both libraries and reconstructs folded/unfolded cards.
- Both mixed ABI combinations were loaded in isolation and correctly reported
  the provider as unavailable instead of reading an incompatible snapshot.

The movement suite initially timed out taking a screenshot of a Wayland-nested
output while its parent workspace was hidden. It passed after switching the
disposable compositor to an independent headless output; no production change
was made for this capture issue. All compositor tests target the isolated
session under `/tmp`, not the user's application windows.

`tests/card_motion.py --max-panes 3 --both-faces --require-redraw --captures`
passed all six pane-count/orientation cases and the unfold/instant-switch check.
The GPU-rendered headless output was 3840×2160 at 60 Hz, scale 1.5, tested at
transforms 0 and 1. Each face had one, two or three applications; companion
windows were parked on another workspace so the card footprint stayed constant.

| Orientation | Apps per face | Frame interval p95 | CPU render p95 |
| --- | --- | --- | --- |
| Landscape | 2 | 16.90 ms | 1.89 ms |
| Landscape | 3 | 16.95 ms | 2.21 ms |
| Portrait | 2 | 16.93 ms | 1.98 ms |
| Portrait | 3 | 16.86 ms | 2.15 ms |

Every sampled active frame requested another frame; flips and reversals
preserved exclusive face input and remembered application focus. First-turn CPU
peaks for three-app faces were 23.75 ms landscape and 26.77 ms portrait. These
are compositor render intervals and CPU submission measurements, not GPU
execution times or physical-display scanout guarantees. Capture work was kept
outside the measured turns. Results and images are under the ignored
`test-results/three-motion/` and `test-results/three-panes/` directories.

A batched visual review covered the native menus and six-app flip poses on both
orientations. It led to one layout refinement: perpendicular unfolding avoids
six thin strips. The updated provider passed the nine three-pane checks and
all five upgrade checks again, and a final visual confirmation showed two rows
of three panes on landscape and two columns of three on portrait. The flip
timeline and renderer used for the measurements above were unchanged. The text
"Segmentation fault (core dumped)" behind some original motion captures is the
test compositor's randomly selected Hyprland splash, recorded as `Current splash`
in its startup log, not a crash during the run.

The tested core, provider and helper were installed on the user's already-enabled
desktop. The updater preserved the existing card's membership, active face and
application focus, plus each monitor's selected workspace. The installed files
match the builds and helper in this checkout; configuration errors are empty.
Both libraries, the previous helper and session recovery metadata were backed
up under `~/.local/state/hyprflip/container-update-20260921-120845/`.

Live native-menu verification passed **8 checks** using temporary terminal
fixtures on empty portrait and landscape workspaces: adding a third app through
a remote-workspace submenu, removing an unfocused app from all three choices,
cancelling the third-app setup prompt, and completing guided creation with two
or three reverse apps. Original cards, geometry, displayed workspaces and focus
were restored. The install and UI reports are `test-results/three-install.json`
and `test-results/three-menu.json`; no application data was changed.

The final unfold refinement was installed with another backup at
`~/.local/state/hyprflip/container-update-20260921-121750/`. No cards were
registered at the start of that update; its before/after state, focus and
displayed workspaces matched. Earlier recovery metadata was retained rather
than replaying a card that was no longer registered on the live desktop.

## Transition modes and Chill integration (2026-09-21)

The seven-mode build adds Flip, Vertical flip, Slide, Fade, Dissolve, Portal and
Instant. Dissolve and Portal are experimental. The native picker previews a
round trip before saving a plain mode preference. The Omachill 1.2 adapter adds
workspace protection, selected-app handoff and bounded holds for plugin updates.

Validation on Hyprland 0.56.2 / GCC 16.2.1:

- C++ core checks and **40 Python selection/installer tests** passed.
- **15 transition checks** passed on a GPU-rendered 3840×2160@60 output at
  scale 1.5, in landscape and rotated portrait. Three panes on each face were
  tested with forward/reverse motion, round-trip previews, disabled animation,
  reload, close and unload interruptions. Instant was checked on both outputs.
- Warm median frame intervals were **16.69–16.75 ms**. Per-case 95th percentile
  CPU render submission was **1.26–2.07 ms**; warm face capture was
  **7.43–7.76 ms** once per turn. These are CPU/render-cycle measurements, not
  GPU execution or scanout latency. Screenshot capture was outside timed runs.
- **7 compatibility checks** passed with Portal, including a Wayland/XWayland
  pair, popups/modals, output transforms 0/1/3 at scale 1.6 and Hyprglass.
- The **18 native lifecycle checks** and **5 upgrade/rollback checks** passed.
- **8 Chill workflow checks** passed: ordinary floater geometry restoration,
  cancellation, creation, manual/automatic Chill, app open/close, card movement,
  reload, failed remote import recovery, lease expiry and updates with Auto
  Chill enabled. Upgrade holds survive Lua reloads via an instance-specific
  runtime file; normal window events do not read that file.

The host crash at 12:49 on September 21 was an expired hy3 layout target:
`Hy3Node::as_target()` threw `Attempted to upgrade an expired Hy3Node target`
while `Hy3Layout::newTarget()` mapped a new window. Creating a native group,
changing to hy3, ungrouping and opening a new window reproduced the exception
in a disposable compositor. The provider now prunes expired leaves before
lookup/insertion/geometry traversal and ignores expired windows in iteration.
The pinned upstream checkout remains untouched; CMake builds checked source
copies. **Three repeated migration/floating/container regression checks passed.**
The real desktop was restarted out of Hyprland safe mode with its intact normal
Lua configuration and the tested provider fix.

Reproduce the new checks in a fresh disposable session:

```sh
./scripts/build-containers
python tests/nested_session.py --directory /tmp/hf-check
# In a second terminal, with the same built ABI:
python tests/stale_targets.py /tmp/hf-check/session.json
python tests/transitions.py /tmp/hf-check/session.json --captures
python tests/compatibility.py /tmp/hf-check/session.json \
  --plugin build/containers/core/hyprflip.so --transition portal \
  --hyprglass /path/to/hyprglass.so --output /tmp/hf-check/compat
python integrations/omachill/prepare-source.py /path/to/omachill/chillmode.lua /tmp/chill-hyprflip.lua
python tests/chill_workflows.py /tmp/hf-check/session.json --engine /tmp/chill-hyprflip.lua
```

Render artifacts and metrics for this run are in `/tmp/hf-modes/`, with native
lifecycle and Chill results in `/tmp/hf-final/`. The two orientation contact
sheets were inspected together; pane geometry, orientation and reveal fields
were coherent across the card.

The live Omarchy menu passed **3 end-to-end checks**: a folded card created
from two chilled test apps, Portal preview followed by Escape without changing
the saved mode, and Use Fade surviving a reload with the card protected from
Auto Chill. The native menu and Portal/Hyprglass captures were inspected in the
confirmation pass. Test apps were closed and the original cards, selected
workspaces, focus and Flip preference restored.

The tested core/provider, picker and Omachill source/installed adapter were
installed. Hyprflip, hy3 and Hyprglass loaded together with no configuration
errors. The Omarchy shell needed a relaunch before picker installation; its
real menu flows passed. The shell later hit its default two-second IPC timeout
intermittently; the picker and installer now allow five seconds for shell IPC,
with an eight-second subprocess deadline. The native menu test already used
that five-second allowance. Recovery records are under
`~/.local/state/hyprflip/transition-install-20260921-135016/`, compositor-library
backups under `container-update-20260921-135017/`, and picker/config backups under
`guided-setup-20260921-135345-238757/` in the same state directory.

## Hyprflip 0.2.0 and OmaCards 0.1.0 release (2026-09-22)

Validated on Hyprland 0.56.2 with matching headers/compiler and Omarchy 4.0.4:

- A clean source copy passed `make test`; `scripts/build-containers` fetched
  the pinned hy3 revision and built both libraries successfully.
- **142 Python tests** passed, covering shared workflows, panel protocol,
  workspace destinations, shortcut conflicts/persistence, installation and
  locked-session update refusal. Python syntax and relative documentation links
  were checked as well.
- **9 native floating-card checks** passed: shared movement/resizing, every
  transition and peek, pane editing, float/tile and fullscreen round trips,
  workspace destinations, cold launching, close recovery and safe unloading.
- **8 Chill workflow checks** passed, including preserving cards through a
  live library update and recovering geometry after failed creation/import.
- **9 fresh-install checks** passed in a Wayland-nested compositor with an
  empty private home, isolated runtime and session bus, and the stock Omarchy
  shell. The documented core installer, provider activation and helper
  installer all succeeded. `omarchy plugin add` cloned OmaCards from its public
  GitHub URL, validated it and enabled its bar widget. Native pairing,
  three-app creation, floating mode, saved workspace destinations and persistent
  shortcut/motion settings worked. Cards, Edit, Library, Settings, Motion and
  Keyboard shortcuts opened through the real shell IPC with a responding
  backend and no configuration errors.

The fresh-install check used the host's installed build/runtime dependencies;
it was not a fresh operating-system installation. It did not load test
libraries into the user's compositor. The hyprpm pin is updated for this release,
but an end-to-end hyprpm-managed installation remains unverified.

Reproduce the automated helper and floating lifecycle checks:

```sh
python3 -m unittest discover -s tests -p '*_test.py'
./scripts/build-containers
python3 tests/nested_session.py --directory /tmp/hf-float
# In a second terminal, while that disposable session is running:
python3 tests/floating_workflows.py /tmp/hf-float/session.json
```

The release-run logs and JSON results were retained under `/tmp/hf-release3/`,
with build logs at `/tmp/hyprflip-release-build.log` and
`/tmp/hyprflip-release-containers.log`. Floating and Chill results from feature
acceptance are under `/tmp/hf-float2/`. These are local run artifacts, not
repository fixtures or a promise of compatibility with other compositor ABIs.

## Card frames and tiling gap parity (2026-09-22)

Built against Hyprland 0.56.2 (`efb50993780079460b0cbed1363e2166a2de1d9f`)
with the pinned hy3 provider. The C++ test and **168 Python tests** pass.
Disposable-compositor validation covers:

- **9 card-frame checks**: real pointer press/release, canceled drags and
  modified clicks, Flip/Fold, fullscreen, a covering floating window, classic
  tabs, and closing/unloading/reloading native group decorations. Status polling
  produced zero idle frames during 40 polls in the headless output probe.
- Spacing measured between the window borders: `gaps_in=14` leaves **28 pixels**
  in both axes, for tiled and floating cards. Directional workspace overrides
  produced the same 28-pixel horizontal and 20-pixel vertical gaps in both modes.
  Unfolded faces also use the normal horizontal gap.
- Dark/light native captures, portrait at scale 1.25, and pixel assertions for
  the keyboard recipient's outline on both panes after retiling. Independent
  visual review found a render-order issue with that outline; the corrected
  captures and covering-window check passed the follow-up review.
- **9 floating workflow checks**, including shared movement/resizing, pane
  editing, float/tile/fullscreen round trips, saved-card cold opening and unload.
- **15 transition checks**: six animated modes with three apps per face in both
  monitor orientations, reversal/preview, reduced motion, reload, close and
  unload. Nested-output frame timings are regression evidence, not a physical
  display performance benchmark.
- **18 native-pair and 13 provider-container checks** pass, including geometry,
  focus, input, fullscreen, workspace changes and unload/reload recovery.
- **9 upgrade checks** pass with Hyprglass loaded: old-provider upgrade,
  multiple/six-pane cards, focus drift, failed-load rollback, crowded workspaces
  with real GTK application minimum sizes, interruption during reconstruction,
  and six minimum-sized apps. Temporary reconstruction returns apps to their
  original workspace and restores the card root's width before resuming use.

Reproduce the new pointer, geometry and capture checks in a fresh disposable
session (never target the user's compositor):

```sh
./scripts/build-containers
python3 tests/nested_session.py --directory /tmp/hf-frames
# In a second terminal, while the disposable session runs:
python3 tests/card_frames.py /tmp/hf-frames/session.json \
  --protocol /path/to/matching/Hyprland/protocols/wlr-virtual-pointer-unstable-v1.xml \
  --captures /tmp/hf-frames/captures
```

The pointer fixture needs `wayland-scanner` and Wayland client development
headers; captures and outline assertions also need `grim`, `wtype`, `foot` and
ImageMagick. Local results are retained in `/tmp/hf-fr2/`; current visual-review
captures are under `.impeccable/review/` and are excluded from Git.

The first live update exposed the crowded-workspace restoration bug and rolled
back; the current updater fixes it and passed the additional checks above. The
second update installed both tested libraries and restored the full card, its
inner proportions and outer size (width difference below 0.05 logical pixels),
with Hyprglass's loaded handle unchanged and no configuration errors. Backups
are under `~/.local/state/hyprflip/container-update-20260922-214723/` and
`container-update-20260922-220505/`.

This live run was not crash-free: Quickshell crashed during the first attempt,
and Telegram aborted during the second, disconnecting after the updater's
successful reconstruction. The exact GTK build's debug symbols resolve both
stacks to `output_handle_name`, GTK 3's Wayland monitor-name callback; Telegram
logged `free(): invalid pointer`. This matches the path in the existing
[Omarchy report #10834](https://github.com/omacom/omarchy/issues/10834), without
proving the original corruption event on this machine. Hyprland remained
running and Quickshell recovered. These client failures are a remaining integration issue,
not evidence of a compositor crash or a clean end-to-end live update.

On 23 September, Telegram was reopened after unlock and attached to the
WhatsApp face, retaining the terminal added there in the meantime. Live checks
confirmed two 28-pixel internal gaps, the visible card frame, exclusive face
input, a responding shell and no configuration errors. This completes app
recovery; it does not claim the upstream GTK crash is fixed.


## Card preferences, compact gaps, drag-to-add and five-app faces — 23 September 2026

The matching ABI 7 core/provider build increases face snapshots to five panes.
Classic tabs and the experimental card frame are selectable independently of
Desktop or Compact (12 logical px) spacing. Temporary, explicit face targets
accept ordinary window-move drags; normal movement and resizing stay native.

Validation on the same Hyprland 0.56.2 ABI:

- **172 Python tests** and the **C++ core suite** passed.
- **9 real-pointer interaction checks** passed in a disposable compositor:
  Classic/Compact applied to existing hy3 cards; Escape and outside release;
  floating app dropped into a tiled face; minimum-size refusal restoring both
  the incoming float and pane proportions; fourth/fifth apps and sixth refusal;
  targeting either unfolded face; floating layout gaps on both axes and readable
  unfolded rows; reversible spacing and disabled drag targets; unload mid-drag.
- **9 pane workflow checks** passed on landscape and portrait outputs: five
  apps on each face, import from another workspace, sixth refusal, removal,
  focus/input ownership, movement/unfolding, guided setup, real minimum-size
  rollback and unfolding-axis fallback.
- **9 floating lifecycle checks** passed, including six animated transitions,
  peek, moving/resizing, edits, reload/fullscreen, saved workspace destinations,
  cold opening, closing panes and safe unload.
- **9 upgrade/recovery checks** passed with a copy of the installed Hyprglass:
  ABI 6 to ABI 7, ten-app cards preserving proportions, focus interference,
  fullscreen refusal, failed-load rollback, crowded workspaces, interrupted
  reconstruction and six minimum-sized apps.
- Native settings captures covered narrow/scaled layouts and light/dark themes.
  The interaction finish review passed after documenting the approved spacing
  and unfolding changes. No frame redesign was attempted.

Reproduce the new drag checks after `scripts/build-containers` in a fresh nested
session (never point this at the live compositor):

```sh
python3 tests/card_interactions.py /tmp/hf-drop/session.json \
  --protocol /path/to/Hyprland/protocols/wlr-virtual-pointer-unstable-v1.xml \
  --captures /tmp/hf-drop/captures
```

The live AORUS update retained every existing card app, process, face and
workspace. After reloading, measured empty gaps on its three-app reverse face
were **12 and 12 logical pixels**. Classic appearance, Compact spacing and
five-app capacity persisted; library hashes matched the tested build,
Hyprglass's loaded handle was unchanged and configuration errors were empty.
The installed Settings panel was visually verified with Classic and Compact
selected after refreshing the shell's cached QML.
The updater also now accepts Hyprland's nullable `solitaryBlockedBy` field;
its locked-desktop regression still refuses mutation when any output is locked.

Local recovery backups: `~/.local/state/hyprflip/container-update-20260923-073125`,
`guided-setup-20260923-073152-966236`, and `omacards-update-20260923-073242`.
This validation does not resolve the earlier GTK client crashes or the deferred
secondary-display driver issue. Marketplace publication requires an updated
immutable dependency pin; no new release was published during this work.
