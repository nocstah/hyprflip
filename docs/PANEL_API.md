# OmaCards and the shared workflow helper

`scripts/workflow.py` holds the same guarded operations used by the existing
menus and the optional OmaCards bar panel. `scripts/setup.py` is the compatible
entry point: C/L first try the enabled panel, with the original menus as a
fallback. `--legacy` explicitly selects those menus. `--front` and explicit
`--edit ADDRESS` continue to use them.

Install with `python3 scripts/install-setup.py`. Native-pair installations can
use `--backend-only` to install the helper and preference loader without the
guided card bindings. This update changes Python and Lua files, not native
compositor libraries. The Lua preference loader accepts only known transition
names, integer durations from 0 to 2000 milliseconds, known appearance names,
integer card gaps from -1 to 128 logical pixels, `#RRGGBB` accent and divider
colors, and integer fullscreen dividers from 0 to 16 pixels.

## Local JSON protocol 1

The compositor status advertises `native_cards` for the core's own dwindle and
floating cards, and `container_provider` when multi-app cards are available.
The shared helper checks the workspace layout and these capabilities together:
it creates and opens cards only on a dwindle workspace of a core reporting
`native_cards`. Status from older cores also carried `hy3_provider`; the current
core no longer reports it and the helper does not read it. No panel protocol
change is required.

```sh
python3 ~/.local/lib/hyprflip/control.py snapshot
python3 ~/.local/lib/hyprflip/control.py run --request '<JSON object>'
```

Snapshot is read-only. It normalizes two-window pairs and multi-app cards into
two faces, includes card/library tokens, original focus/workspace/session,
core capabilities, app icons, transition modes and animation settings.
There are no persistent window IDs: tokens belong to one Hyprland instance.
`installed_commit` and `installed_release` describe what `scripts/bootstrap.py`
last installed, or are null. The release (such as `0.3.0-rc.16`) is the newest
release tag that commit contains, so a panel can require a minimum release and
accept later ones instead of matching one exact commit.
`context.anchor_label` names the app that will become the front of a new card;
it is display text only and never used to identify or retarget a window.

A card on a special workspace, which another program parked there, no longer
counts as an open saved card. It is still listed in `cards`, with the special
workspace's negative id in `workspace`, but its `saved_names` is empty and its
`name` is made of its apps' labels. A saved row whose only match is a parked
card has `open: false` and the detail of a card that is not open, such as
`Open here`, instead of `Go to · Workspace …`. The detail leaves out the apps
the parked card holds: it offers neither to bring them nor to resize them.
Opening that row never goes to the parked card or reveals it, and an app the
parked card holds is named instead of taken: “… is held by a hidden card. Close
it or bring that card back, then try again.”

Every mutation includes `protocol: 1`, an `action`, and the snapshot's `context`.
Card operations also include `target: {kind, id, token}` from the displayed
card. Saved-card operations include `name` and `recipe_token` from its row.

| Action | Additional fields |
| --- | --- |
| `flip`, `unfold`, `floating`, `fullscreen` | `target` |
| `preview` | `target`, `mode` |
| `edit` | `target`, `face` (0/1), optional `pane` address and `intent` |
| `face` | `target`, `face` index from 0, optional `pane` address on that face |
| `create` | Uses the original focused app |
| `open`, `manage` | `name`, `recipe_token` |
| `transition` | `mode` from the advertised list |
| `duration` | Integer `duration_ms`, 0–2000 |
| `shortcut` | `binding` action ID, integer modifier `mask`, XKB `key` |
| `appearance` | `style`: `classic` or `frame` |
| `spacing` | Integer `gap`: -1 for Desktop spacing, or 0–128 logical pixels |
| `accent` | Boolean `enabled`, optional `color` (`#RRGGBB`) |
| `divider` | Integer `width`, 0–16; optional `color` (`#RRGGBB`, or empty to follow the accent) |

Editor intents are stable IDs: add, replace, remove, other_side, previous, next,
horizontal, vertical, balance, save, manage, repair, unpair. An empty intent
opens the shared action chooser. Editing a hidden face explicitly shows it first.
`unpair` works from any face when `capabilities.ungroup_any_face` is true;
older helpers offer it only from a face that holds a single app.

`face` shows one face of a card without the action chooser, when
`capabilities.show_face` is true. It turns straight to that face (an unfolded
card folds onto it; a core without numbered faces turns once), waits for the
turn to end, and focuses `pane`, or else the face's own app.

`run` emits newline-delimited JSON on stdout and reads responses on stdin:

- `question`: id, mode (`select`/`input`), prompt, choices containing value,
  label and detail. Reply `{"reply": id, "value": "..."}` with a stable value.
- `handoff`: id. Close the popup and release its keyboard grab, then send
  `{"resume": id}`. A handoff may occur after an answer as well as before apply.
- `opening`: saved name and labels of apps still being awaited.
- `done`, `cancelled`, `error`: terminal message. Process exit is the completion
  boundary; do not start another request while the first is unwinding recovery.

Send `{"cancel": true}` to cancel even during launch waits. Closing stdin or
SIGTERM/SIGINT also unwinds the request. Requests share the existing token/lock
with native menus, so newer operations supersede older pending choices. Keep
stdin open throughout an operation, including between handoff messages.

`control.py unattended` is separate from protocol 1. It serves programs that
open and save cards with nobody at a menu: one `--request` argument, one JSON
line back, no stdin, no questions and no notifications (see
[open and save cards unattended](SCRIPTING.md#open-and-save-cards-unattended)).
It takes the same request lock as the menus and the panel, waiting at most its
`lock_ms`, but it never supersedes a pending menu or panel request.

The backend revalidates session, workspace, focus, membership, pane identity and
saved-definition fingerprints. Titles and names remain plain JSON data; the
interface has no arbitrary shell-command operation. Limits bound request size
and response buffering. Layer-shell focus is never used to choose a new target.

## Validation

The Python regression suite covers the shared workflows, stale panel targets,
window-address reuse, protocol cancellation, direct named opening, hidden-face
activation, duration rollback, and shortcut fallback. OmaCards supplies separate
QML fixture captures and a native layer-shell integration runner for disposable
Hyprland sessions. Compositor renderer behavior is unchanged by this extraction.

## Settings and placement extensions (protocol 1)

Snapshots include `shortcuts` with active action rows and occupied chords for
local conflict feedback. `shortcut` accepts `binding`, integer `mask`, and a
validated XKB `key`; the backend rechecks live conflicts, persists atomically,
applies through owned Lua handles, and restores the previous value on failure.
The panel uses Wayland's shortcuts inhibitor only while recording a combination.

`floating` is an explicitly targeted card action. Cards report their `floating`
mode; `capabilities.floating` gates this control. Saved rows carry optional
`workspace`; the existing Manage workflow changes it. Missing workspace means
Current workspace. The usual session/focus/recipe validation precedes navigation.

`capabilities.appearance` and `capabilities.spacing` gate the corresponding
global preferences. Snapshots expose `appearance` (`classic` or `frame`) and
`card_gap` (-1 for Desktop spacing; 12 for Compact). The helper persists each
value atomically and restores the previous value if application fails. These
preferences apply to existing cards without changing their membership.
`capabilities.accent` gates the accent ring. Snapshots expose `accent_ring`
(boolean) and `accent_color` (`#RRGGBB`, or empty when unset or invalid). The
`accent` action takes `enabled` and an optional `color`; the color is applied
first when enabling. `control.py accent-color --color '#RRGGBB'` updates only
the color, without a panel request, so a shell can follow its theme; unchanged
colors are not rewritten or dispatched. Both values persist like spacing.
`capabilities.nearby` gates the card-keys-beside-a-card switch. Snapshots
expose `nearby_card` (boolean); the `nearby` action takes `enabled` and
persists it like the accent ring.
`fullscreen` toggles whole-card fullscreen for a native (dwindle or floating)
multi-app card, targeted like `floating`; two-window groups are refused. Apps are not told they are fullscreen, so browsers keep their toolbars.
Cards report `fullscreen` and `native` (a dwindle or floating card that can
fullscreen as a whole); `capabilities.fullscreen` gates the control. While a
native card is fullscreen, the helper keeps editing it (flip, unfold, layout,
add, replace, remove) and marks an added app by address so focus never leaves
the card; ungrouping and reopening missing apps wait until it leaves fullscreen.
`capabilities.divider` gates the divider between a fullscreen card's apps.
Snapshots expose `fullscreen_divider` (0–16 pixels; 0 lets the apps touch) and
`divider_color` (`#RRGGBB`, or empty to follow `accent_color`, then the active
border). The `divider` action takes `width` and an optional `color`, applied
first; both persist like spacing. Both capabilities are true only on cores that
report `fullscreen_divider`.
`capabilities.drag_to_add` reports whether the compositor's temporary drop
targets are enabled; dragging stays a native compositor interaction.
