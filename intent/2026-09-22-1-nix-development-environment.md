---
status: approved
issue: 1
author: olafkfreund
---

# Intent: Reproducible local builds and nested testing on NixOS

## Problem

This checkout has no pinned project development environment. Local CMake
configuration fails because pkg-config cannot find Hyprland 0.56.2; Lua 5.4
and GLES development metadata are also unavailable in the shell. The Python
suite runs 142 tests but reports nine errors resolving libxkbcommon.so.0.
The standalone C++ timeline test passes.

The host compositor reports Hyprland 0.56.0, while the project requires
0.56.2 and checks the compositor ABI at load time. A successful compilation
alone would therefore not establish compatibility with the host desktop.

## Proposed outcome

- A contributor can enter a reproducible project-local development environment
  and build the core plugin and pinned experimental hy3 provider.
- The existing C++ and Python tests pass with dependencies provided by that
  environment, including Python's runtime lookup of libxkbcommon.
- The existing disposable nested-session workflow can run with a compositor,
  headers and compiler that match the built plugins.
- Documented commands and recorded validation distinguish successful builds,
  automated tests and actual nested compositor checks.

## Affected users and systems

NixOS contributors, this repository's development environment and build
documentation, and disposable local Hyprland test sessions. The optional
hy3 provider is included in build and nested-demo validation. Omarchy menu
and panel integration are outside this task.

## Constraints

- Use a project-local devenv environment with committed dependency pins.
- Preserve the Hyprland 0.56.2 requirement and runtime ABI checks.
- Verify an available matching source revision and toolchain during design;
  do not assume a package version or silently substitute the host version.
- Reuse existing build and test entry points where possible.
- Do not upgrade the host compositor, modify desktop configuration or load
  test plugins into the user's active compositor.
- Keep generated build outputs and test-session state out of version control.
- Follow the separately approved intent, spec and plan stages before
  implementation.

## Open questions

None for the problem framing. Exact package/source pins and any adjustments
needed by the existing nested-session launcher will be established in the spec.
