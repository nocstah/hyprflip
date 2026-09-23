# Optional hy3 provider

This directory builds `Bridge.cpp` into upstream hy3 **hl0.56.0.1**, commit
`42b7ed8fd9aefd3f36e5f617afd5071245c67853`, against Hyprland **0.56.2**.
It is an experiment, not a supported interface offered by upstream hy3.

The bridge owns no windows or layout tree. Its registry holds weak references to
two-child groups; each child is a leaf or a split of at most five leaves.
It calls hy3's existing tree operations. The core accesses a versioned function
table through `src/ContainerABI.hpp`, resolves live window identifiers, and never
caches the provider across events. A load epoch prevents IDs from being reused
across different provider lifetimes.

ABI 7 expands both snapshot arrays to five apps per face. It retains exact
split snapshots, atomic face arrangement and pane replacement. Its entry point
`hyprflip_hy3_bridge_v7`
is versioned separately so an old core/provider combination cannot call an
incompatible table. Status advertises `layout_controls` and `container_max_panes`; the
picker defaults to two when talking to older builds. An additional attachment retains
the existing split axis and pane weights. This is a Hyprflip limit, not a hy3
group limit.

`arrange` accepts exactly the current members of one face, in the desired order,
with positive finite proportions summing to one. It splices direct children
within their existing parent, without unlocking or extracting surviving panes.
Application size limits are checked before committing; failure restores the
previous order, axis, exact weights and selection. The helper uses
`hyprctl hyprflip 'arrange horizontal 0xADDRESS:0.6 0xADDRESS:0.4'` (or the Lua
`arrange` function), focused on that face. Status advertises `repair_cards` and
includes each container's `layouts` with `axis`, `ratios` and `focused` address.
The editor also uses `arrange` to swap/reorder apps, keeping ratios attached to
slots and focus attached to the same app.

`replace` exchanges a card leaf and an eligible tiled leaf on the same
workspace. It swaps their owning list slots, parents and weights, updating the
parents' focused-child pointers without extracting nodes or collapsing groups.
Both leaves and all card members must fit their resulting slots; failure
exchanges them back. The card's ID, root and surrounding groups survive, and
replacing the remembered pane follows the incoming app. A sole face app and a
full five-pane face need no special restructuring. Status advertises
`pane_replacement`; the IPC action is `replace 0xOLD 0xNEW` (also available as a
single string argument to the Lua `replace` function). The helper imports/tiles
the incoming app before calling it and restores that handoff on refusal.

Edits preserve the two-face tree, validate application size limits and restore
the previous membership, order, weights and selection on refusal. Transfers
require a nonempty source and room at the destination. Remaining source weights
are normalized proportionally, avoiding negative weights in very uneven splits.

The bridge also provides whole-card directional movement, silent workspace moves
and temporary unfolding. The core and provider must be upgraded together. Unfolding changes
the same card root from tabs to a split, preserving its children and their size
ratios; refolding restores tabs on the focused face. It uses Hyprland's geometry
animation and tries the other split axis if application size constraints require
it. Rows with three or more apps prefer vertically arranged faces; columns with three or more apps prefer
horizontally arranged faces, keeping each pane readable when both sides appear.
Mixed directions retain the footprint-based choice. The provider records the
unfolded state so unrelated external tree edits are
still detected.

The CMake wrapper also renames upstream's exit entry point and calls it after
removing retained `Hy3TabPassElement` objects from the compositor's render pass.
Hyprland 0.56.2 normally clears the preceding pass at the next frame. That is too
late after a real `dlclose`: its plugin-defined deleters would already be
unmapped. `-fno-gnu-unique` permits actual unload and makes this boundary testable.
No upstream source file is rewritten.

With the compact frame disabled, the card's hy3 tab bar remains usable at rest.
It is hidden during animation with its space reserved; it is not part of an
individual application's framebuffer.

## Optional card frame

The compact card frame uses a separate optional export,
`hyprflip_hy3_card_frame_v1(id, headerHeight)`. The current container ABI is
version 7; update core and provider together. A separate optional export,
`hyprflip_hy3_card_style_v1(id, headerHeight, gap)`, applies the header and empty
gap override to owned card roots only. A negative gap inherits desktop spacing.
The original frame export remains available for compatible callers. Only registered Hyprflip roots
reserve the header and suppress their tab bar, including when unfolded. Core
rendering and input handling remain in the MIT module. `CardFrame.hpp` and the
provider-side implementation are GPL-3.0-only, like the bridge.

## License and provenance

`Bridge.cpp` is licensed under GPL-3.0-only, with the license text in this
directory. Upstream [hy3](https://github.com/outfoxxed/hy3) is distributed under
GPLv3 and retains its own authorship and license in the fetched source tree.
The shared ABI header and Hyprflip core retain the repository's MIT license.

The build script downloads upstream into the ignored `build/containers/` tree.
It does not vendor upstream implementation into the core. If distributing the
experimental hy3 binary, include its corresponding pinned upstream source, this
bridge, CMake wrapper and applicable license notices.
