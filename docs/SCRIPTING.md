# Driving cards from other programs

A workspace manager, a launcher or a phone companion can build and drive cards
over `hyprctl hyprflip` without taking the keyboard from the person at the
desktop. Everything here works on native cards with only the core loaded;
[hy3 cards](CONTAINERS.md) take part where noted.

## Find a card

`hyprctl hyprflip status` prints JSON. Each entry of `containers` (multi-app
cards) and of `pairs` (two-window native groups) has an `id`. A container also
lists:

| Field | Meaning |
| --- | --- |
| `faces` | Window addresses of the front (`faces[0]`) and the back (`faces[1]`) |
| `active` | The side shown: 0 front, 1 back |
| `unfolded` | Both sides shown side by side |
| `workspace` | `id`, `name` and `special` (true on a special workspace) |
| `floating`, `box` | Placement, and the whole card's `[x, y, w, h]` |

An id lasts as long as its card. After the plugin or Hyprland reloads, read
the ids again.

## Build a card

```sh
hyprctl hyprflip restore [quiet] <tiled|floating> <active> <unfolded> <x> <y> <w> <h> \
  front <axis> <focused> <address:ratio>... back <axis> <focused> <address:ratio>...
```

`restore` turns open windows on one workspace into a native card. `active` is
the side to show (0 or 1) and `unfolded` 0 or 1. The box is the card's frame for
a floating card; a tiled card takes its front app's tile, and the box only
checks that every app's size limits fit. For each face, `axis` is `horizontal`
or `vertical`, `focused` is the app that has that face's focus, and each app is
`0xADDRESS:ratio` (the ratios of a face are shares, any positive numbers). A face
holds one to five apps.

Without `quiet`, the card takes the focus on its shown side, switching to its
workspace. With `quiet`, the focus stays where it is, unless it was on one of
the card's apps: then it goes to the shown side, never staying on a hidden app.

It replies `ok: ok`. Read the new card's id from `status`, by one of its
addresses. It refuses apps that are gone, already in a card or whose size
limits do not fit, and refuses while a grab or drag is in progress
([scripted calls and input](#scripted-calls-and-input) says which input holds
up a quiet restore).

```sh
hyprctl hyprflip restore quiet tiled 0 0 0 0 1200 900 \
  front horizontal 0x55d0a1b2c3d0 0x55d0a1b2c3d0:1 \
  back horizontal 0x55d0a1b2c4e0 0x55d0a1b2c4e0:1
```

## Act on a card by id

| Action | Behavior |
| --- | --- |
| `card <id> show front` / `show back` | Show that side; an unfolded card folds onto it |
| `card <id> flip` | Turn the card with the configured transition; instantly when its workspace is not on screen |
| `card <id> workspace <workspace>` | Move a multi-app card and follow it |
| `card <id> workspace <workspace> silent` | Move it and stay where you are |
| `card <id> ungroup` | Take the card or pair apart where it is ([below](#ungroup-a-card-by-id)) |

A workspace is a number, `name:<name>`, `special` or `special:<name>` (names of
letters, digits, `-`, `_` and `.`, up to 64). Relative forms such as `+1` or
`previous` are refused: they depend on where the focus is. Named and special
workspaces take native cards; hy3 cards move to numbered ones. A pair shows,
flips and ungroups by id; move its windows with Hyprland.

None of these take the focus. When the focus is on one of the card's apps it
moves with the shown side, as a keyboard flip does. A silent move takes the
focus off the card only if it was there, to the next window of the workspace
left behind.

## Ungroup a card by id

`card <id> ungroup` takes a card or a pair apart, shown or parked. Its apps
stay open as separate windows on the card's workspace. It takes no focus and
leaves the pointer where it is. It refuses while one of the card's windows is
fullscreen: `Leave fullscreen before ungrouping the card.` Cores that have it
report `"card_ungroup": true` in `status`.

Ungrouping a card that is on screen re-tiles its place: Hyprland lays its apps
out again as new tiles, and they can split a neighbouring tile. With one app on
each face, the back app takes the card's tile and the front app splits the
neighbour. A program that wants the layout kept parks the card first and
ungroups it there, where its apps come apart without touching the shown
workspace, then moves them where they belong:

```sh
hyprctl hyprflip card 12 workspace special:park silent
hyprctl hyprflip card 12 ungroup
```

## Scripted calls and input

`card <id> workspace <workspace> silent`, `card <id> ungroup` and
`restore quiet …` go ahead while the screen is locked and while a button is
held on another window. They still refuse while:

- a keyboard or pointer grab is active, such as an open popup menu;
- a drag-and-drop is in progress;
- the pointer is locked or confined;
- a button pressed on one of the card's windows is still held (for a quiet
  restore, on one of the apps it names);
- one of those windows is being moved or resized, including a move the app
  asks for itself, such as dragging a GTK header bar.

Every other action still refuses while any input is in progress, a locked
screen included, as before. That includes `card <id> show`, `card <id> flip`,
`card <id> workspace` without `silent` and a plain `restore`. A busy refusal of
`card <id> …` or `restore …` always starts with `Finish the active grab or
drag`. Match that prefix, wait a moment and try again.

## Replies and notifications

A call replies `ok: …` or `error: …`. Calls by id (`card <id> …`) and quiet
restores sent with `hyprctl` never show a notification, desktop or Hyprland's
own, a bare `restore quiet` included: the program that sent them reads the
reply and decides what to tell. A refused plain `restore …`, a refused Lua call
and the other actions still notify as before.

Hyprland 0.56's `hyprctl` exits 7 when the reply is an error; the reply is still
on stdout. Exits 1 to 6 are its own failures to reach Hyprland, such as 4 when
it cannot connect and 6 when no answer comes within its 5 seconds. Treat 7 with
an `error:` reply as a refusal, and the others as Hyprland not answering.
`hyprctl --batch` exits 0 with one reply per command, refusals included. A
batch that Hyprland never answered exits 0 as well; its last line names the
failure, such as `Couldn't connect to … (4)`. Without a loaded core, Hyprland
answers `unknown request` and exits 0: treat any reply to an action that does
not start with `ok:` as not done.

## Parked cards

A card moved to a special workspace that is not shown is parked: its apps keep
running, Find leaves it out (it lists apps on normal workspaces only) and
drag-to-add offers only cards on visible normal workspaces. Bring it back with
`card <id> workspace <number> silent`. Showing that special workspace shows the
card there.

The saved-card menus and OmaCards leave a parked card alone. They never count
it as an open saved card, go to it, reveal it or fill in its missing apps, and
they name an app it holds instead of taking it (see
[saved cards](SAVED_CARDS.md#opening-behavior)).

An update with `scripts/install.py` leaves a parked card as separate windows on
its special workspace and says how many it left: the core does not build cards
on special workspaces, and the program that parked the card rebuilds it. It
keeps the cards on normal workspaces. If the new core refuses to rebuild one of
them, that card's apps stay as separate windows and the other cards are still
kept. If `hyprctl` cannot reach Hyprland, the update is rolled back and the
installer keeps its recovery file; the next update in the same Hyprland session
rebuilds the pairs and cards from it when no card or pair is open.

## Open and save cards unattended

A program that builds cards while the user works elsewhere, such as a workspace
manager that gives each workspace its own card, can open a definition as a card
and save a live card by its id through the helper, with nobody at a menu:

```sh
python3 ~/.local/lib/hyprflip/control.py unattended --request '<JSON object>'
```

`scripts/install-setup.py` installs the helper; `--backend-only` is enough. It
never asks anything, never shows a notification and never reads stdin. It never
switches the workspace or moves the pointer. When one of its apps takes the
keyboard, it gives the keyboard back to `focus` where it can, and
`focus_returned` is false when one of the card's apps keeps it. It prints
exactly one JSON line and exits 0 when that line says `"ok": true`, 1
otherwise. A helper too old to have `unattended` prints nothing on stdout and
exits 2 with a usage error.

A request is a JSON object of at most 65536 bytes with `"protocol": 1`, an
`action` and only the fields that action takes. When `XDG_RUNTIME_DIR` or
`HYPRLAND_INSTANCE_SIGNATURE` is missing, a valid request gets `unavailable`.

| Action | Fields (optional in brackets) | Reply |
| --- | --- | --- |
| `capabilities` | none | `actions`, `core`, `max_panes` |
| `list` | `store` [`name`] | `cards` |
| `delete` | `store`, `name`, `token` [`lock_ms`] | `result`: `deleted` or `absent` |
| `open` | `workspace`; `name` and `store`, or `recipe` [`bind`, `owned`, `focus`, `launch`, `timeout_ms`, `lock_ms`] | `result`: `opened`, and the card |
| `save` | `store`, `name`, `card`, `members`, `previous` [`base`, `keep`, `floating`, `owned`, `lock_ms`] | `result`: `saved` or `unchanged` |

A reply that succeeds carries `protocol`, `"ok": true` and a `result` named
after its action, or after what happened.

`capabilities` lists the actions and says `"core": true` when the loaded core
has native cards and `card <id> ungroup`. It says `"core": false` only when
Hyprland answers without such a core; when Hyprland does not answer, the reply
is the `hyprland` error. `max_panes` is the core's limit of apps per face, 0
without a core.

`list` gives each definition in the store, or only `name`, with its `token`,
its `active` face, whether it is `floating` and its `faces`. Each app there has
a `class`, `initial_class`, `label` and `launcher` (true when the definition
remembers a launcher for it). A store that does not exist yet lists no cards.
`delete` removes `name` only while `token` is still its token; otherwise the
reply is `conflict`. Neither of them asks Hyprland anything.

### Open a card

```json
{"protocol": 1, "action": "open", "store": "/home/me/.local/state/example/cards.json",
 "name": "acme", "workspace": 3, "bind": ["0x55d0a1b2c3d0", "0x55d0a1b2c4e0"],
 "owned": ["example-browser", "example-terminal"], "focus": "0x55d0a1b2c5f0",
 "launch": true, "timeout_ms": 15000, "lock_ms": 2000}
```

- `workspace` is the numbered workspace the card opens on. It must exist and
  use dwindle; anything else is `unsupported_workspace`. A workspace the
  definition names is ignored. To hide the new card, park it afterwards with
  `card <id> workspace special:<name> silent`.
- `name` opens a definition from `store`. `recipe` gives
  [a definition](#a-definition) in the request instead, with every `title`
  empty. It is never stored, and the reply's `token` is null.
- `bind` names up to 10 windows the card may take. Each fills the first open
  slot of its app, front face first. No other window is ever taken. A bound
  window that no slot wants stays where it is and is listed in `unused`.
- `owned` lists up to 8 app classes the caller opens itself. A slot whose class
  or initial class is listed is never launched.
- `focus` is the window the keyboard goes back to. It defaults to the window
  that had the keyboard when the request started.
- `launch` (default true) lets it launch missing apps. `timeout_ms` (1000 to
  60000, default 20000) is how long it waits for their windows, and `lock_ms`
  (0 to 30000, default 5000) how long it waits for the lock.

A window can be bound when it is mapped, belongs to no card, pair or group, and
is not pinned, hidden or fullscreen. It must be on a numbered workspace, or on
a special workspace whose name has only letters, digits, `-`, `_` and `.`, up
to 56 of them: those are the places it can be sent back to. A window in a card,
pair or group is `in_card`, a fullscreen one `fullscreen`, and any other window
that cannot be bound `changed`. A fullscreen window on the destination
workspace is `fullscreen` too.

A slot that no bound window fills is launched unless the table below says
otherwise. `missing` says why a slot stayed empty:

| `missing` | Why |
| --- | --- |
| `owned` | Its class or initial class is in `owned` |
| `open_elsewhere` | A window of that app is open outside `bind` |
| `not_launched` | `launch` is false |
| `no_launcher` | No launcher matches it |
| `launch_failed` | Its launcher failed before a window came |
| `timeout` | No window of its own came within `timeout_ms` |

A launcher is the one the definition remembers (`desktop_id`), or else the one
installed launcher whose file name or `StartupWMClass` matches the app's class.
A label never picks a launcher. Apps start through `gio launch`, and the helper
waits for their windows without holding the lock. The user moving around does
not end that wait. A new window fills a slot only when it is plainly that
slot's own.

Slots left empty drop out: the apps left share their face's room in their saved
proportions, and the face's focus goes to the nearest app left. A face with no
app at all is `incomplete`, and nothing moves. When that is clear before
anything launches, nothing is launched either.

Then the helper commits, under the lock again. The definition must still have
its token (`conflict`), and every chosen window must still be bindable, with
the same process, class, workspace and floating state (`changed`). Floating
apps are tiled first. One `hyprctl --batch` then sends a silent move
(`follow=false`) for each app on another workspace, followed by the core's
`restore quiet`. The reply names the card that `status` shows with exactly
those apps, even when the batch's own reply was lost. When there is none, every
app goes back where it came from, special workspaces included, and an app that
floated floats again. The reply is then `refused`, `busy` when the core refused
for input in progress, or `hyprland` when the batch got no answer. An app that
could not go back is listed in `stranded`, with `rollback_failed`.

Opening never switches the workspace. A launched app may take the keyboard as
its window maps. The helper gives it back to `focus` from windows of the apps
this request launched, matched by their class, once per window, while the user
is still on the workspace where the request started and `focus` is there. After
the batch, it gives the keyboard back when one of the card's apps holds it and
`focus` is outside the card, still on the current workspace; a user who moved
elsewhere is never pulled back. `focus_returned` is false when one of the
card's apps keeps the keyboard. The helper never focuses the window that
already has the keyboard. Hyprland's focus puts the pointer in the middle of
the window it focuses, so the helper's focus is a single request that turns
`cursor:no_warps` on for that focus alone and back to what it was, and the
pointer stays where it is.

When `name` opened a stored definition and a launched app filled a slot, the
launcher that brought it is written back to the store, checked against the
token. The reply's `token` is then the definition's token after that write; use
it as the next `previous`. `remembered` appears only in that case: true, or
false when the write failed. The card stays open either way.

```json
{"protocol": 1, "ok": true, "result": "opened", "card": 12, "token": "…",
 "workspace": {"id": 3, "name": "3", "special": false},
 "slots": [[{"class": "example-browser", "initial_class": "example-browser",
             "label": "example-browser", "launcher": false, "address": "0x55d0a1b2c3d0"}],
           [{"class": "example-terminal", "initial_class": "example-terminal",
             "label": "example-terminal", "launcher": false, "address": "0x55d0a1b2c4e0"},
            {"class": "obsidian", "initial_class": "obsidian", "label": "obsidian",
             "launcher": true, "address": null, "missing": "open_elsewhere"}]],
 "launched": [], "unused": [], "focus_returned": true}
```

`slots` gives every slot of the definition, face by face: its app, the
`address` of the window in it (null when there is none) and, for an empty one,
`missing`. `launched` lists the apps this request started, with their `class`,
`initial_class`, `wm_class`, `desktop_id` and the `address` of their window
(null if none came in time), so a caller can still find a window that comes
late. `card` is the new card's id, ready for `card <id> …` calls.

### Save a card

```json
{"protocol": 1, "action": "save", "store": "/home/me/.local/state/example/cards.json",
 "name": "acme", "card": 12, "members": ["0x55d0a1b2c3d0", "0x55d0a1b2c4e0"],
 "previous": "<token>", "keep": [{"face": 1, "index": 1}], "floating": false,
 "owned": ["example-browser", "example-terminal"], "lock_ms": 200}
```

`save` captures the native card with that id, shown or parked, into the
caller's store. It never focuses, moves or changes the card, and it never
touches the user's library.

- `members` must be exactly the card's apps (`changed`). An unknown id is
  `no_card`, a pair `not_native`, and a fullscreen card `fullscreen`.
- `previous` is the token the caller last read for `name`, or null for a new
  name. A token that no longer matches, or null for a name that exists, is
  `conflict`. A new name is always written. An existing one is written only
  when the card differs from it (`saved`); otherwise the reply is `unchanged`.
- `keep` lists closed apps to keep from the definition being replaced, each by
  its `face` (0 or 1) and its `index` there. A face that lost only those apps
  and shares its room evenly, as Hyprflip leaves it after a close, is kept as
  it was. Otherwise each kept app goes back at its place with its saved share,
  shrunk if needed so the apps still open keep, between them, at least a tenth
  of the face for each. Kept apps beyond the core's limit of apps per face are
  left out and listed in `dropped`.
- `base` is the definition the card came from, such as the `recipe` it was
  opened with ([a definition](#a-definition), with every `title` empty). It is
  allowed only with `previous` null, and stands in for the replaced definition
  there: `keep` indexes it, and needs it when not empty. With a token, `keep`
  indexes the stored definition and `base` is `invalid_request`.
- `floating`, when given, replaces whether the card floats. A workspace the
  replaced definition names is kept.
- An app whose class or initial class is in `owned` never gets a launcher. Any
  other keeps the one the replaced definition remembered, or gets the one
  installed launcher its class matches, never one found by its label. Each
  app's label comes from its class.

The reply carries `name`, the definition's `token`, `dropped` and `slots`,
where a kept app's `address` is null.

### A definition

A store keeps a definition under each name, and `recipe` and `base` carry one in
the request. `list` shows only part of it, so a caller that sends its own builds
it by these rules:

```json
{"active": 0, "floating": false,
 "faces": [{"apps": [{"class": "example-browser", "initial_class": "example-browser",
                      "title": "", "label": "Browser",
                      "desktop_id": "example-browser.desktop"}],
            "ratios": [1], "axis": "horizontal", "focus": 0},
           {"apps": [{"class": "example-terminal", "initial_class": "example-terminal",
                      "title": "", "label": "Terminal"},
                     {"class": "example-notes", "initial_class": "example-notes",
                      "title": "", "label": "Notes"}],
            "ratios": [0.7, 0.3], "axis": "vertical", "focus": 0}]}
```

- `active` is the face shown, 0 or 1. `floating` (true or false) and `workspace`
  (1 to 2147483647) are optional.
- `faces` holds exactly two faces, front first. Each has `apps` (1 to 5),
  `ratios`, `axis` (`horizontal` or `vertical`) and `focus`, the index of the
  app that has the face's focus.
- `ratios` has one number per app, each above 0 and at most 1, and together
  they sum to 1. That is stricter than `restore`, which takes any positive
  shares.
- Each app has `class`, `initial_class`, `title` (always empty in a request) and
  a non-empty `label`, each at most 512 characters, and optionally `desktop_id`,
  the file name of its launcher, such as `example-browser.desktop`.

A definition in a request that breaks one of these is `invalid_request`.

### The store

`store` is required by `list`, `delete` and `save`, and by `open` with a
`name`. It is a file of the caller's own, never the user's library:

- an absolute, normalized path to a `.json` file whose name has 1 to 64
  letters, digits, `-`, `_` or `.` before `.json`;
- in a real directory, not a symlink, that the caller owns and nobody else can
  write;
- if the file exists, a regular file with one link, owned by the caller;
- neither the library nor a file in the library's folder.

Anything else is `invalid_store`, before anything is read or created. The
helper never creates the folder. The file has the library's format and limits:
at most 100 definitions and 1 MiB, with names of up to 64 characters. It is
written atomically with mode `0600`, and its lock and temporary files sit
beside it. It never keeps a window title: titles are blanked before anything is
compared, digested or written. A file the helper cannot read is
`store_unreadable`, and it is never overwritten.

### Errors

```json
{"protocol": 1, "ok": false, "code": "busy",
 "message": "Another card change is still in progress. Try again in a moment.",
 "labels": [], "launched": []}
```

Each code has a fixed message, and `labels` names apps by their labels: no
reply carries a window title or an exception's text. `incomplete` also carries
`slots`, and `rollback_failed` carries `stranded`. A failed `open` lists the
apps it started in `launched`; they stay open.

| Code | Meaning | What to do |
| --- | --- | --- |
| `invalid_request` | The JSON, the protocol, a field or an address is wrong, or a definition in the request has a title | Fix the request |
| `invalid_store` | The store path breaks a rule above | Use a private folder of your own |
| `store_unreadable` | The store could not be read or written; a damaged file is never overwritten | Repair or move the file |
| `invalid_name` | The name is empty, longer than 64 characters, or has control characters or extra spaces | Fix the name |
| `not_found` | The store has no definition by that name | List again, or send a `recipe` |
| `unavailable` | Hyprland answered without a core that has native cards and `card <id> ungroup`, or the session variables are missing | Wait until such a core is loaded, or run the helper inside the Hyprland session |
| `hyprland` | Hyprland did not answer, or refused one of the helper's own steps | Try again soon |
| `unsupported_workspace` | The workspace is not an existing numbered dwindle workspace | Choose another one |
| `fullscreen` | A window on that workspace, a bound window or the card to save is fullscreen | Try again after fullscreen ends |
| `incomplete` | A face has no app to show; `slots` says why | Bind, allow or install the missing apps |
| `in_card` | A bound window already belongs to a card, pair or group | Bind another window |
| `busy` | The lock stayed taken for `lock_ms`, or the core refused for input in progress | Try again in a moment |
| `changed` | A bound window closed, changed or cannot be bound, or `members` no longer match the card | Read the windows again |
| `conflict` | The definition changed since the caller read it, or a new name already exists | List again and use the current token |
| `refused` | The core refused the card; every app went back | Do not repeat the request unchanged |
| `rollback_failed` | The core refused the card, and the apps in `stranded` could not go back | Move those windows back, or tell the user |
| `not_native` | The id names a pair or a card that is not native | Save native cards only |
| `no_card` | No card has that id | Read the ids from `status` |
| `limit` | The store already holds 100 definitions | Delete one first |
| `cancelled` | A signal stopped the request before any app moved | Nothing to undo |
| `internal` | Something unexpected failed | Report it |

### Locking and cancelling

`open` takes the menus' request lock while it checks the request and again for
its commit, never while it waits for launched apps. `save` and `delete` hold it
throughout. Each waits up to `lock_ms` for the lock and then replies `busy`.
An unattended request never supersedes a menu or panel request that waits for
an answer, as a newer menu request does: it only waits its turn. Store writes
also take the store's own lock. `list` and `capabilities` take no lock.

SIGTERM or SIGINT ends a waiting request with one `cancelled` line and exit 1:
a request that waits for the lock, or an `open` before its batch goes out.
Nothing has moved then: apps tiled for the card float again, and apps it
launched stay open. Once the batch has gone out, a signal waits for the result,
and the request prints its usual reply.

### Window titles

A request travels on the command line, where other local users can read it,
so it never carries a window title: a `recipe` or `base` with a title is
`invalid_request`. The helper's own `hyprctl` calls carry addresses, numbers
and checked names only, and its replies and its store carry no title either.

## How this is tested

`tests/card_id_workflows.py` checks the calls by id and
`tests/unattended_workflows.py` the helper, each in a nested session with only
the core loaded. The refusal during a move the app asks for itself has been
checked by hand so far.
