# Optional hy3 provider

This directory builds `Bridge.cpp` into upstream hy3 **hl0.56.0.1**, commit
`42b7ed8fd9aefd3f36e5f617afd5071245c67853`, against Hyprland **0.56.2**.
It is an experiment, not a supported interface offered by upstream hy3.

The bridge owns no windows or layout tree. Its registry holds weak references to
two-child groups; each child is a leaf or a split of at most three leaves.
It calls hy3's existing tree operations. The core accesses a versioned function
table through `src/ContainerABI.hpp`, resolves live window identifiers, and never
caches the provider across events. A load epoch prevents IDs from being reused
across different provider lifetimes.

ABI 3 increases each face's snapshot capacity to three windows. Its entry point
is versioned separately so an old core/provider combination cannot interpret the
larger structure. The status response advertises `container_max_panes`; the
picker defaults to two when talking to older builds. A third attachment retains
the existing split axis and pane weights. This is a Hyprflip limit, not a hy3
group limit.

The bridge also provides whole-card directional movement, silent workspace moves
and temporary unfolding. The core and provider must be upgraded together. Unfolding changes
the same card root from tabs to a split, preserving its children and their size
ratios; refolding restores tabs on the focused face. It uses Hyprland's geometry
animation and tries the other split axis if application size constraints require
it. Three-app rows prefer vertically arranged faces; three-app columns prefer
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

The card's hy3 tab bar remains usable at rest. It is hidden during animation with
its space reserved; it is not part of an individual application's framebuffer.

## License and provenance

`Bridge.cpp` is licensed under GPL-3.0-only, with the license text in this
directory. Upstream [hy3](https://github.com/outfoxxed/hy3) is distributed under
GPLv3 and retains its own authorship and license in the fetched source tree.
The shared ABI header and Hyprflip core retain the repository's MIT license.

The build script downloads upstream into the ignored `build/containers/` tree.
It does not vendor upstream implementation into the core. If distributing the
experimental hy3 binary, include its corresponding pinned upstream source, this
bridge, CMake wrapper and applicable license notices.
