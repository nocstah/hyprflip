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
limits do not fit, and refuses while a grab or drag is in progress.

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

A workspace is a number, `name:<name>`, `special` or `special:<name>` (names of
letters, digits, `-`, `_` and `.`, up to 64). Relative forms such as `+1` or
`previous` are refused: they depend on where the focus is. Named and special
workspaces take native cards; hy3 cards move to numbered ones. A pair shows and
flips by id; move its windows with Hyprland.

None of these take the focus. When the focus is on one of the card's apps it
moves with the shown side, as a keyboard flip does. A silent move takes the
focus off the card only if it was there, to the next window of the workspace
left behind.

## Parked cards

A card moved to a special workspace that is not shown is parked: its apps keep
running, Find leaves it out (it lists apps on normal workspaces only) and
drag-to-add offers only cards on visible normal workspaces. Bring it back with
`card <id> workspace <number> silent`. Showing that special workspace shows the
card there.

`tests/card_id_workflows.py` checks all of this in a nested session with only
the core loaded.
