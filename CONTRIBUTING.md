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

## Bug reports

Include reproduction steps, Hyprland and plugin versions, compiler version, layout, monitor scale/rotation and other loaded plugins. For rendering issues, indicate whether the problem happens with an opaque terminal pair and whether it occurs in a nested session.

For a crash, provide the relevant backtrace and the action preceding it. Core dumps contain application memory: do not attach raw cores, private window contents or credentials. A compositor crash with a plugin loaded is not sufficient to identify the responsible component.

Use [GitHub issues](https://github.com/nocstah/hyprflip/issues) and pull requests for feedback and changes. Contributions are provided under the repository's [MIT license](LICENSE).
