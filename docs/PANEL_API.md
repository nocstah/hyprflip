# OmaCards and the shared workflow helper

`scripts/workflow.py` holds the same guarded operations used by the existing
menus and the optional OmaCards bar panel. `scripts/setup.py` is the compatible
entry point: C/L first try the enabled panel, with the original menus as a
fallback. `--legacy` explicitly selects those menus. `--front` and explicit
`--edit ADDRESS` continue to use them.

Install with `python3 scripts/install-setup.py`. Native-pair installations can
use `--backend-only` to install the helper and preference loader without the
container bindings. This update changes Python and Lua files, not native
compositor libraries. The Lua preference loader accepts only known transition
names and integer durations from 0 to 2000 milliseconds.

## Local JSON protocol 1

```sh
python3 ~/.local/lib/hyprflip/control.py snapshot
python3 ~/.local/lib/hyprflip/control.py run --request '<JSON object>'
```

Snapshot is read-only. It normalizes native pairs and provider containers into
two faces, includes card/library tokens, original focus/workspace/session,
provider capabilities, app icons, transition modes and animation settings.
There are no persistent window IDs: tokens belong to one Hyprland instance.
`context.anchor_label` names the app that will become the front of a new card;
it is display text only and never used to identify or retarget a window.

Every mutation includes `protocol: 1`, an `action`, and the snapshot's `context`.
Card operations also include `target: {kind, id, token}` from the displayed
card. Saved-card operations include `name` and `recipe_token` from its row.

| Action | Additional fields |
| --- | --- |
| `flip`, `unfold`, `floating` | `target` |
| `preview` | `target`, `mode` |
| `edit` | `target`, `face` (0/1), optional `pane` address and `intent` |
| `create` | Uses the original focused app |
| `open`, `manage` | `name`, `recipe_token` |
| `transition` | `mode` from the advertised list |
| `duration` | Integer `duration_ms`, 0–2000 |
| `shortcut` | `binding` action ID, integer modifier `mask`, XKB `key` |

Editor intents are stable IDs: add, replace, remove, other_side, previous, next,
horizontal, vertical, balance, save, manage, repair, unpair. An empty intent
opens the shared action chooser. Editing a hidden face explicitly shows it first.

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
