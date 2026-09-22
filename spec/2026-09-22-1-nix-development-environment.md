---
status: approved
issue: 1
intent: intent/2026-09-22-1-nix-development-environment.md
---

# Spec: Reproducible local builds and nested testing on NixOS

## Design

### Pinned environment

Add `devenv.nix`, `devenv.yaml` and a generated, committed `devenv.lock`.
Use the existing CMake, Makefile, Python tests and nested-session scripts.
Ignore devenv-generated state and local overrides in `.gitignore`.

Pin the Hyprland input to `efb50993780079460b0cbed1363e2166a2de1d9f`:
GitHub's v0.56.2 tag resolves to this commit, which also matches the existing
`hyprpm.toml` pin. Make the environment's nixpkgs input follow
`hyprland/nixpkgs`, preserving the upstream lock's nixpkgs revision
`e72e4f299401a3689d4b3d5fc6496b11db7064eb` and dependency graph.

Use that flake's Hyprland package, its development output, and its `stdenv`
for the plugin compiler. Nix evaluation of this pinned package confirms
version `0.56.2+date=2026-08-05_efb5099`, GCC 16.1.0, Lua 5.5.0 and
`out`, `man`, `dev` outputs. Provide the
package's build dependencies so exported headers and transitive pkg-config
requirements resolve without hand-maintained store paths. Explicit tools:
CMake, Ninja, GNU Make, pkg-config, Git, Python 3, binutils, foot and grim.
Supply Lua and GLES development outputs from the same package set.

Ensure the project's `Hyprland`, `hyprctl`, C and C++ compiler commands resolve
to these pinned packages when entering `devenv shell`. Do not rely on the
host's `/run/wrappers/bin/Hyprland` or GCC 15.3. Activation must not launch a
compositor or load plugins automatically. Document explicit shell entry;
automatic activation/trust is not required.

Set the development shell's `LD_LIBRARY_PATH` to the Nix libxkbcommon library
directory using `lib.makeLibraryPath`. This supplies the existing
`ctypes.CDLL('libxkbcommon.so.0')` in `scripts/shortcuts.py` without changing
application logic or global loader settings.

### Correct the Lua dependency

The pinned compositor's `CMakeLists.txt` requests Lua 5.5 and its Nix package
uses `lua5_5`. Hyprflip currently requests `lua5.4` while passing the compositor's
Lua state into plugin callbacks. Change the core CMake Lua requirement to
5.5, using the available pkg-config naming aliases for that version, and
update the requirements in `README.md` and `docs/INSTALL.md` accordingly.
Do not expose both Lua versions as a workaround. Keep the exact Hyprland
version requirement and all runtime ABI guards.

### Build and runtime validation

Keep the hy3 source pin and patch process in `scripts/build-containers`.
Both libraries must build against the environment's compositor dependencies.
Do not change the provider API, renderer or feature behavior for this task.

Reuse `tests/nested_session.py` with a fresh short `/tmp` path. The existing
launcher already isolates configuration, runtime, data and session identity,
and disables physical DRM/logind acquisition. Use its explicit session JSON
for integration tests. No launcher changes are planned; unexpected runtime
requirements must be evaluated before expanding scope.

Document the Nix workflow in `docs/INSTALL.md`, linked from `README.md`, and
record actual results in `TESTING.md`. Report nested/GPU checks separately
from compilation and unit tests. Host desktop installation, system upgrades,
Omarchy menus and OmaCards remain outside scope.

## Alternatives rejected

- Host-wide packages or a compositor upgrade: unnecessary for project-local
  compilation and nested testing, and would change the active desktop.
- Removing version or ABI checks: hides incompatibility rather than fixing it.
- Latest independent nixpkgs and compiler: can diverge from the compositor ABI.
- Lua 5.4 alongside a Lua 5.5 compositor: mixes Lua ABIs across callbacks.
- A custom build wrapper or new test harness: existing commands already cover
  the intended build and runtime checks.

## Risks

- A cold environment may require substantial downloads and a GCC/Hyprland
  source build if binary substitutes are unavailable.
- Upstream Nix packaging and hy3 compilation have not yet been built here;
  source inspection is not proof of successful builds.
- Nested rendering depends on the host's Wayland session and graphics driver.
  A working build does not prove GPU compatibility or suitability for loading
  into the host's Hyprland 0.56.0 session.
- The Lua dependency correction changes documented prerequisites for other
  platforms; the target remains upstream Hyprland 0.56.2.

## Verification

1. `devenv info` evaluates; the generated lock retains the named source pins.
2. Inside `devenv shell`, verify compiler and executable paths, Hyprland 0.56.2,
   pkg-config metadata for Hyprland, Lua 5.5 and GLES, and Python xkbcommon loading.
3. `make test` and `python3 -m unittest discover -s tests -p '*_test.py'` pass.
4. `./scripts/build-containers` and CTest in `build/containers/core` pass.
5. Inspect plugin dynamic dependencies for Lua 5.5 and no Lua 5.4 linkage.
6. In a fresh nested session run `tests/integration.py`; in another fresh
   session run `tests/containers.py`, passing their session JSON paths.
7. Start the `--containers` demo, verify readiness and card state, and stop it
   cleanly. Check captures from runtime tests for visible rendering defects.
8. Record results and confirm no host plugin/configuration changes or surviving
   test processes. Review the final diff and keep generated outputs untracked.

## Design evidence

- [Pinned Hyprland flake](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/flake.nix)
- [Compiler selection](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/nix/overlays.nix)
- [Compositor Lua requirement](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/CMakeLists.txt#L291)
- [devenv input following and locking](https://devenv.sh/inputs/)
- [devenv stdenv option](https://devenv.sh/reference/options/#stdenv)
