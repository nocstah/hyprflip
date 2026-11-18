# Contributing

Hyprflip currently targets Hyprland 0.56.2. Start by checking the exact version and ABI reported by `hyprctl version`; internal compositor APIs and compiler ABIs change between releases.

## Development

```sh
make test
python -m unittest discover -s tests -p '*_test.py'
clang-format --dry-run --Werror src/*.cpp src/*.hpp tests/*.cpp
python -m compileall -q scripts tests
```

Use the compiler and development headers matching the compositor. The pure timeline test also builds independently with C++20; GitHub Actions uses that path and runs the installer tests without a graphical session. CI does not establish compositor or GPU compatibility.

Use the disposable nested session described in [TESTING.md](TESTING.md) for rendering and lifecycle changes. Keep actual application focus, native group membership and geometry correct through reversals, interruptions and unloads. Test the blur matte as well as the visible color pass, and inspect normal and rotated output captures.

Changes targeting a new Hyprland version should include the matching version check, integration results and a `hyprpm.toml` commit pin. A pin maps a Hyprland commit to an existing plugin commit, so it is added after that implementation commit exists.

## Releases

Before tagging a release, run these on a desktop with the matching Hyprland, and record the results in [TESTING.md](TESTING.md) with the release's other checks:

```sh
make test
python -m unittest discover -s tests -p '*_test.py'
python tests/release_suites.py --hyprglass /path/to/hyprglass.so \
    --protocol /path/to/wlr-virtual-pointer-unstable-v1.xml --omacards /path/to/omacards
```

`tests/release_suites.py` runs every compositor suite a release needs, each in its own disposable nested session, and prints a summary: updates and uninstall, restores and close reasons with the close hooks on and off, covers, fullscreen cards, the layouts, the switcher, the key module suites of `tests/key_suites.py` (which load `examples/containers-navigation.lua` and `examples/containers-setup.lua`), and, with `--omacards`, OmaCards' native panel checks against this checkout. Run all of it for every release, including those that change only the core: a core change can alter what the modules and the panel see. `--protocol` adds the real pointer checks; without it, or without `--omacards`, the summary notes what did not run. Add `--aquamarine` on NVIDIA, as TESTING.md describes. `--only` and `--skip` choose suites while you work; `tests/key_suites.py` still runs the key module suites alone.

When the checks pass and TESTING.md records them, `python3 scripts/release.py
<version>` makes the release: it turns the changelog's Unreleased section into
the version's heading, names the version in the README and the beta guide, ends
the version's TESTING.md section with the commit it was released from, runs the
unit tests, commits "Release Hyprflip <version>", tags it, and pins
`hyprpm.toml` to that commit in a second commit. It refuses until TESTING.md has
a heading naming the version, and pushes nothing: it prints the push and `gh
release create` commands. `--dry-run` shows the changes, and `--body FILE` gives
the release commit a message body, and `--trailer "Co-Authored-By: …"` adds a
trailer to both commits.

## Bug reports

Include reproduction steps, Hyprland and plugin versions, compiler version, layout, monitor scale/rotation and other loaded plugins. For rendering issues, indicate whether the problem happens with an opaque terminal pair and whether it occurs in a nested session.

For a crash, provide the relevant backtrace and the action preceding it. Core dumps contain application memory: do not attach raw cores, private window contents or credentials. A compositor crash with a plugin loaded is not sufficient to identify the responsible component.

Use [GitHub issues](https://github.com/nocstah/hyprflip/issues) and pull requests for feedback and changes. Contributions use the repository's [MIT license](LICENSE).
