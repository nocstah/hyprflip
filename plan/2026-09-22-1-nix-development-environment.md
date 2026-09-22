---
status: approved
issue: 1
spec: spec/2026-09-22-1-nix-development-environment.md
---

# Plan: Reproducible local builds and nested testing on NixOS

## Approved decisions

Create a project-local devenv environment for Linux, validated on this
x86_64-linux NixOS host. Preserve the exact Hyprland 0.56.2 requirement and
all runtime ABI guards. Do not upgrade the host compositor, install plugins
into it, change desktop configuration or configure Omarchy/OmaCards.

Pin the Hyprland flake to `efb50993780079460b0cbed1363e2166a2de1d9f`
(v0.56.2 and the existing hyprpm pin). Let the environment's nixpkgs follow
`hyprland/nixpkgs`, retaining upstream revision
`e72e4f299401a3689d4b3d5fc6496b11db7064eb` and its dependency graph.
Use the flake's Hyprland package, development output, build dependencies and
stdenv. Evaluation confirmed Hyprland `0.56.2+date=2026-08-05_efb5099`,
GCC 16.1.0, Lua 5.5.0 and `out`, `man`, `dev` outputs.

Provide CMake, Ninja, GNU Make, pkg-config, Git, Python 3, binutils, foot and
grim, plus Lua/GLES development outputs from the same package set. Compiler,
Hyprland and hyprctl resolution must use these packages inside the shell.
Supply libxkbcommon through shell-local `LD_LIBRARY_PATH`, constructed with
`lib.makeLibraryPath`, for the existing Python ctypes lookup. No Python logic
change or global loader configuration is needed.

Correct the core's Lua requirement from 5.4 to 5.5 to match the compositor's
Lua state ABI; accept appropriate 5.5 pkg-config aliases, not another Lua
version. Keep the pinned hy3 revision
`42b7ed8fd9aefd3f36e5f617afd5071245c67853` and existing source patch process.
Reuse the build commands, tests and isolated nested-session launcher. Do not
add a build wrapper, test framework, renderer changes or provider API changes.

Commit `devenv.nix`, `devenv.yaml` and generated `devenv.lock`; ignore generated
state and local overrides. Document explicit `devenv shell` entry without
automatic trust or launch actions. Update requirements and Nix instructions
in `docs/INSTALL.md`, link them from `README.md`, and record actual validation
in `TESTING.md`, distinguishing unit/build results from nested/GPU checks.

## Steps

1. Check branch/status and read affected files. Confirm the approved plan and
   existing artifacts remain on `build/1-nix-development-environment`.
   Inspect pre-existing build outputs before rebuilding; preserve any outputs
   made with a different toolchain outside the chosen clean build locations.
   Record host plugin state and hashes of existing Hyprland configuration
   files for comparison after testing, without recording their contents.
   Verify a parent Wayland socket is available.

2. Add `devenv.yaml` with the pinned Hyprland input and nixpkgs follow; add
   `devenv.nix` implementing the package/compiler/library decisions above.
   Extend `.gitignore` for devenv state and local overrides while keeping the
   lock tracked. Generate `devenv.lock` through devenv, not by hand.
   Verify with `devenv info`, inspect lock pins, then check shell paths,
   versions, pkg-config resolution and Python library loading. Cold downloads
   or source builds may take time; retain logs and report actual failures.

3. Change `CMakeLists.txt` to select Lua 5.5 with `pkg_search_module` and
   explicit version bounds on accepted aliases. Keep Hyprland and GLES checks.
   Update Lua requirements in `README.md` and `docs/INSTALL.md` in the same
   change. Run the core build/test and Python suite in the environment.
   Verify the configured compiler and Lua version in CMake output/cache.

4. Run `scripts/build-containers` with the pinned environment and default
   two-job limit, then run its C++ test. Inspect core and provider dynamic
   dependencies for missing libraries; the core must directly use Lua 5.5.
   Record libinput's transitive Lua 5.4 dependency. Confirm both builds retain
   compositor ABI checks and the hy3 pin.
   Investigate any build failure before changing scope or package pins.

5. Use fresh paths of at most 18 bytes for three disposable sessions:
   `/tmp/hf-native`, `/tmp/hf-cards` and `/tmp/hf-demo` (choose other short
   names if occupied). Keep each launcher running while its checks execute,
   then terminate only that launcher and verify its children exit. Run native
   integration tests in the first, container tests in the second, and the
   interactive `--containers` demo in the third. Inspect test captures and
   verify demo readiness, provider availability and the three-window card.
   Use `tests/control.py` or test scripts with the explicit session JSON for
   every nested IPC command. No planned launcher edits; evaluate unexpected
   runtime requirements before expanding scope.

6. Finish Nix build/test/demo instructions in `docs/INSTALL.md` with a README
   link. Record versions, commands, test counts and observed runtime results
   in `TESTING.md`. Compare host configuration hashes and plugin state,
   confirm test processes have exited, run `git diff --check`, and inspect
   the final diff for generated artifacts or unrelated changes. Commit with
   Conventional Commit messages on the task branch. Prepare a PR linking
   intent, spec and plan with `Closes #1`; since origin is read-only, use a
   user-owned fork if publication is available, otherwise report the exact
   publication blocker and leave local commits ready for review.

If implementation deviates, update this plan in the same commit as the code.
Do not weaken checks or silently substitute a different compositor/toolchain.

### Implementation adjustment: upstream Glaze packaging

The initial shell build failed configuring Hyprland: its pinned Nix package
provides Glaze 8.0.0, but CMake requires Glaze 7 and falls back to an unavailable
in-sandbox source download. In `devenv.nix`, override only the compositor's
`glaze-hyprland` argument with Glaze 7.2.0 (the version its CMake fallback names).
Use `fetchFromGitHub` with the verified source hash
`sha256-f3NVRi3SXKo42hn0WCw7JsOK3EkdOVJIcuzhPorKjFY=` and CMake flags supported
by that release. Keep the approved compositor, compiler and nixpkgs revisions.
The development headers and nested compositor must use this same override.

### Implementation adjustment: runtime test dependencies and stale assertion

Include `wtype` for the existing keyboard-input integration check. CMake's
FindPkgConfig also probes unused static-link metadata and emits missing-private-
dependency messages. Investigation confirmed resolving those probes would
require a separate transitive static development closure. Keep the environment
limited to this project's shared-library builds, document these non-fatal
messages, and validate normal pkg-config flags and runtime shared dependencies.
The first native integration run passed nine checks, then timed out because
its floating-pair helper expected
`status.pairs`. `Controller::pair()` routes floating windows through
`FloatingCards::api()`, reported in `status.containers`. Update only that test's
floating case to verify container faces and active side; keep tiled-pair
assertions unchanged. Rerun the suite in a fresh nested session. No production
controller or renderer behavior changes are needed.

Link inspection found Lua 5.4 transitively through the pinned libinput package's
Lua plugin support. Keep that upstream dependency unchanged. Verify that
Hyprflip directly links Lua 5.5, no libraries are missing, and the nested
compositor reports `Lua 5.5` when evaluating `return _VERSION`; report the
libinput dependency explicitly rather than claiming a Lua-5.4-free closure.

## Tests

Run the following inside `devenv shell`, unless stated otherwise. Execute
and inspect each result before proceeding to a dependent check.

| Check | Command or inspection | Expected result |
| --- | --- | --- |
| Environment evaluation | `devenv info` from the checkout | Successful evaluation; lock contains approved pins |
| Tool selection | `command -v Hyprland hyprctl cc c++`; `Hyprland --version`; `c++ --version` | Pinned store executables; Hyprland 0.56.2; GCC 16.1.0 |
| Development metadata | `pkg-config --modversion hyprland lua5.5 glesv2` (use the selected 5.5 alias if different) | Hyprland 0.56.2, Lua 5.5, available GLES |
| Python shared library | `python3 -c 'import ctypes; ctypes.CDLL("libxkbcommon.so.0")'` | Exit zero |
| Core | `make test` | Build and CTest pass |
| Python | `python3 -m unittest discover -s tests -p '*_test.py'` | All tests pass; current baseline has 142 tests |
| Provider/core | `./scripts/build-containers` | Both plugin libraries built |
| Container core test | `ctest --test-dir build/containers/core --output-on-failure` | All tests pass |
| Shared libraries | `readelf -d` and `ldd` on built core/provider libraries | Core directly links Lua 5.5; no missing libraries; libinput's transitive Lua 5.4 dependency recorded |
| Native session | `python3 tests/nested_session.py --directory /tmp/hf-native`, then `python3 tests/integration.py /tmp/hf-native/session.json` in another shell | READY, integration checks pass and captures render correctly |
| Container session | `python3 tests/nested_session.py --directory /tmp/hf-cards`, then `python3 tests/containers.py /tmp/hf-cards/session.json` in another shell | READY, container checks pass and captures render correctly |
| Interactive demo | `python3 tests/nested_session.py --directory /tmp/hf-demo --containers` | READY; matching plugins loaded; one card with one front and two back windows |
| Demo IPC | `python3 tests/control.py /tmp/hf-demo/session.json hyprflip status` and `python3 tests/control.py /tmp/hf-demo/session.json configerrors` | Provider available, expected card, no config errors |
| Cleanup | Stop each launcher; check tracked processes and host baseline | No surviving test children; host plugin/configuration state unchanged |
| Repository | `git diff --check`; `git status --short` | No whitespace errors or unintended tracked outputs |

Do not use an unqualified `hyprctl version` as proof of the nested version:
it connects to the inherited host session. Query the nested session explicitly.
Compilation alone cannot establish rendering correctness or compatibility
with the host's Hyprland 0.56.0. Record blocked checks as blocked, not passed.

## Rollback

Stop only the tracked test launchers and their remaining children, then exit
the development shell. No host rebuild or desktop configuration rollback is
required. Preserve test logs for diagnosis. Revert implementation commits on
the task branch to remove the environment and Lua/documentation changes;
retain the approved artifact history. Remove only task-created build/session
directories when no longer needed, and restore any outputs preserved in step 1.
Do not delete the lock to repair a failed environment or run a system-wide
garbage collection as part of rollback.
