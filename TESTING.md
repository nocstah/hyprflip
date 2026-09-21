# Validation

## Saved-card and peek checks (2026-09-21)

Checkpoint `7f2de93` contains the preceding multi-app container, transition and
Chill work. The next change adds named saved arrangements and hold-to-peek.

- 54 Python tests cover the existing setup/editor/installer plus saved-card
  cancellation, duplicate names, concurrent updates, corrupt files, atomic
  write failure, stale windows, changed focus, ambiguous matches and review.
  They also reject invalid targeted actions before mutation and verify that
  losing compositor IPC restores the previous library files without hiding
  the original error behind focus-cleanup errors.
- `tests/saved_restart.py` starts two separate disposable compositor processes.
  It saves a six-app card with different split axes and unequal proportions,
  restarts the compositor, opens fresh app processes, and restores the card
  from other workspaces. All memberships, proportions and remembered focus
  match. Further checks restore from Chill, inject a failure after partial
  grouping, recover floating geometry/workspaces/tags, and delete a saved
  definition without dissolving its running card.
- Six container-upgrade checks preserve multiple cards, six-pane proportions,
  native pairs, workspaces and focus, reject fullscreen interference, and
  recover from a failed plugin load. Forced focus changes between IPC requests
  now exercise both the updater and saved-card helper. Both select, verify and
  act in one Lua callback, with mark and pair/attach kept together.
- `tests/peek.py` passes 19 checks: every transition in both directions, early
  reversal, an actual synthetic key press/release with modifiers released first,
  typing, focus, unfold, workspace changes, config reload, a real GTK popup,
  pane closure, virtual monitor removal during Portal, virtual DPMS off/on,
  unload while holding, and native two-window pairs.
- The existing native suite passes all 18 lifecycle checks against the new
  core. The standalone C++ core test passes too.

Commands (after building):

```sh
python -m unittest discover -s tests -p '*_test.py'
ctest --test-dir build --output-on-failure
python tests/peek.py /tmp/hf-test/session.json
WAYLAND_DISPLAY=/run/user/1000/wayland-1 XDG_RUNTIME_DIR=/run/user/1000 \
  python tests/saved_restart.py --results /tmp/hf-saveproof \
  --engine /path/to/integrated/chillmode.lua
```

Use a fresh results directory for the restart test. It creates and stops its
own nested compositors and never restarts the real desktop. Omitting `--engine`
checks ordinary floating apps instead of Chill-tagged apps.

Evidence from this run is in `/tmp/hf-saverace/`,
`/tmp/hf-peek/peek-results.json`, `/tmp/hf-peek/native/integration.json` and
`/tmp/hyprflip-focus-unit.log`. Upgrade evidence is in
`/tmp/hyprflip-updater-fix-test.log` and `test-results/container-upgrade.json`.
The tested core SHA256 is
`7e0a6116f66acff17ca7236b548672e888aba685884022e99d5d31513b967caa`;
the unchanged ABI 3 provider is
`2fa46bc9dc6da8ca19aa986a540ea5c3b54d56e4bc11804df8b88fdeedc5cdb6`.

The synthetic keyboard uses `input.resolve_binds_by_sym=true` only inside its
test configuration. The physical desktop's resolver setting is retained.
Geometry changes legitimately trigger the existing instant-switch fallback;
the hotplug test settles both faces before requesting an animated turn.
GPU tests use a headless output so hiding the parent nested window cannot stop
their presentation loop. Native regression screenshots target the tested
output, and workspace return uses the actual starting workspace.

The DPMS check uses the current
[Lua dispatcher](https://wiki.hypr.land/configuring/core/dispatchers/).
Virtual hotplug and output power checks are not evidence of a physical monitor
reconnection or real system suspend/resume; those remain hardware checks before
a wider release.

After the user unlocked the desktop, four native menu checks passed: saving a
named three-app card, cancelling the restore review, restoring it, and deleting
the saved definition without dissolving the running card. Screenshots of the
edit menu, name entry and restore review were inspected. Temporary fixture apps
were closed and the user's cards were preserved. Evidence is in
`/tmp/hf-saved-ui-confirm/`; subsequent focus-guard changes leave the UI intact
and passed the restart/workflow suite again.

The live installation did **not** complete. An initial attempt rolled back after
marking an already grouped window; the guarded-focus fix above addresses that
race. The retry crashed while unloading the old core, before copying either new
library. Analysis found a stale Hyprglass decoration deletion callback into a
previously unloaded library. See [the crash analysis](docs/UNLOAD_CRASH_2026-09-21.md).
The installed Hyprflip libraries and helper remain the previous versions. Do
not treat the nested checks as evidence of a completed desktop installation.

## Tested environment

The 0.1.1 implementation was built against Hyprland 0.56.2 (`efb50993780079460b0cbed1363e2166a2de1d9f`) with GCC 16.2.1. Compositor tests ran in a disposable Wayland-nested session with temporary configuration, followed by installation and daily use on a desktop running the same ABI.

The lifecycle suite passed **18 checks**, and the compatibility suite passed **7 checks**. Separate tests exercised two Brave application windows and an upgrade from a config-loaded 0.1.0 library to 0.1.1.

| Area | Checked behavior |
| --- | --- |
| Core motion | Reversal, midpoint crossing, stalled/negative time, smooth endpoints, projection bounds and inverse mapping |
| Pairing | Mark/cancel, invalid pairing, native group creation, exclusive active input |
| Repeated turns | 16 animated flips preserve position and size |
| Interruption | Keyboard input, external focus, workspace changes, config reload and unload |
| Lifecycle | Unpair, external group removal, member closure, surviving window access |
| Native state | Floating pairs and fullscreen transfer |
| Applications | Wayland/XWayland GTK windows and two Brave windows using local pages |
| Popups | Popover/grab fallback and rejection of modal children |
| Output mapping | Fractional scale 1.6 and transforms 0, 1 and 3; both faces captured and inspected |
| Hyprglass 1.0 | Temporary opt-out during turns and restoration of original tags |
| Upgrade | Exact group adoption preserves geometry, focus and current side; invalid adoption rejected |
| Configuration | Five shortcuts registered; key releases preserve animation; callbacks remain safe after unload |

## Running the checks

```sh
make test
python -m unittest discover -s tests -p '*_test.py'
```

The Python installer tests use temporary files and mocked IPC. They do not touch a running compositor. GitHub Actions runs these tests, the independent C++20 timeline/projection test and syntax/manifest checks. It does not compile the full plugin or run GPU integration tests; those need matching Hyprland development headers and a Wayland session.

For the compositor tests, open a separate terminal:

```sh
python -u tests/nested_session.py --directory /tmp/hf-test
```

Then run the suites one at a time against that connection file:

```sh
python tests/integration.py /tmp/hf-test/session.json
python tests/compatibility.py /tmp/hf-test/session.json \
  --hyprglass /path/to/hyprglass.so
python tests/browser.py /tmp/hf-test/session.json
python tests/motion.py /tmp/hf-test/session.json
```

Omit `--hyprglass` when it is unavailable. Compatibility checks need GTK4/PyGObject and XWayland; browser checks need Brave. The session needs GPU access, a visible parent Wayland compositor, Foot, Grim and wtype. Keep the parent display awake for rendering measurements. Use a short `/tmp` path because Unix socket names have a length limit. Ctrl+C in the launcher cleans up its children.

The harness disables physical display/session access and test clients use temporary configuration. JSON reports and captures go into ignored `test-results/`. Inspect screenshots as well as automated geometry checks. Do not rebuild or overwrite a library mapped into a compositor; unload it or load a separate copy first.

With an older local build available, these optional regression checks compare versions:

```sh
python tests/motion.py /tmp/hf-test/session.json --baseline /path/to/old/hyprflip.so
python tests/config_upgrade.py /tmp/hf-test/session.json --baseline /path/to/0.1.0/hyprflip.so
```

## Motion measurements

An initial comparison used identical 600 ms durations and 12 turns per version on the same nested output. Mean mismatch between pose advancement and render timestamps fell from 0.90 ms to 0.06 ms after moving from an 8 ms timer to render-cycle sampling. The 95th percentile fell from 2.18 ms to 0.37 ms. Median render intervals remained about 33.4 ms in both versions; 95th percentile CPU render duration changed from 3.86 ms to 4.28 ms.

These are development measurements of pose sampling and CPU render timing, not GPU execution or physical scanout. Only the console summary of that initial run was retained; rerun the supplied probe to obtain per-frame data. Reduced timing jitter does not establish higher frame rates, and additional texture filtering costs rendering work.

## Card lighting and reversal polish

On 2026-09-21, the animation update passed the C++ core test, **17 Python
unit/installer tests**, **5 card motion checks**, **7 compatibility checks**,
**18 native lifecycle checks**, **13 container checks**, **10 movement/unfold
checks** and **4 container upgrade checks**. Compatibility, workflows and
upgrade tests included the installed Hyprglass 1.0.0 library. Both the default
and experimental core builds compiled against the tested Hyprland ABI.

The core tests now verify that reversals preserve angle and angular velocity,
settle on the requested face, and follow the same trajectory with coarse or
fine time steps, including near endpoints. Ordinary turns retain their original
duration and symmetric quintic curve.

The new card suite compares one- and two-pane backs, including unequal splits,
at 3840×2160/60 Hz, scale 1.5 and transforms 0 and 1. Four ordinary 420 ms turns
per arrangement were measured separately from captures and unfolding. It also
checks reversal before/near/after the edge, repeated retargeting, exclusive input,
focus, unfold/refold and instant switching with animation disabled.

```sh
python tests/card_motion.py /tmp/hf-test/session.json \
  --plugin /path/to/previous/hyprflip.so \
  --output test-results/animation-before --captures
python tests/card_motion.py /tmp/hf-test/session.json \
  --output test-results/animation-after --captures --require-redraw
```

| Output / back panes | Render interval median, before → after | CPU render p95, before → after |
| --- | --- | --- |
| Landscape / 1 | 16.75 → 16.73 ms | 2.10 → 2.08 ms |
| Landscape / 2 | 16.75 → 16.74 ms | 2.10 → 2.09 ms |
| Portrait / 1 | 16.75 → 16.75 ms | 1.96 → 1.74 ms |
| Portrait / 2 | 16.73 → 16.74 ms | 1.96 → 2.01 ms |

These figures exclude the first turn from steady timing statistics. First-turn
CPU maxima ranged from 3.97–22.65 ms before and 18.13–28.19 ms after. The work
within those first frames was not separately profiled; this does not establish
that a cold turn always fits the 16.7 ms frame budget. A separate 12-turn native
pair comparison at 600 ms measured render-interval p95 of 21.25 → 21.21 ms and
CPU-render p95 of 4.40 → 4.80 ms. These runs do not establish a frame-rate gain.

The probe did confirm a redraw scheduling defect. At `RENDER_POST`, Hyprland
has already cleared the renderer's monitor reference. Using a weak monitor
reference captured at `preChecks` fixes the next-frame request. The new assertion
passed on every active turn frame in all four arrangements; the baseline
requested none of those frames in three arrangements. The headless backend
still rendered at roughly 60 Hz in both versions, which is why render intervals
alone did not expose the missing request.

Representative outgoing, near-edge, incoming, resting and unfolded captures were
inspected together on landscape and portrait outputs. The two back panes share
the light field, resting colors match the baseline, and the compatibility images
show correctly oriented GTK content at transforms 0, 1 and 3 with scale 1.6.
The lighting changes only RGB inside the existing pass; it adds no texture read,
framebuffer or idle animation. Unfold/fold retains the native layout animation
path. Its focus and final geometry are checked; the sampled IPC boxes do not
measure its per-frame visual easing.

Raw frame records, capture state and PNGs are retained locally under ignored
`test-results/animation-before`, `animation-after`, `animation-compatibility`,
`animation-lifecycle`, `animation-containers` and
`animation-native-motion.json`. Capture timing is approximate and screenshots
are not a substitute for a continuous scanout measurement. All measurements
describe this disposable GPU-rendered compositor, not physical display latency.

The tested build was then installed on the live Omarchy desktop. Post-update
checks confirmed matching library bytes, all three plugins loaded, no config
errors, and the existing Gmail/WhatsApp/Telegram card's membership, active face,
pane geometry, workspaces and input state preserved. Active window and monitor
workspaces also matched the pre-update snapshot. The disposable compositor was
closed. This installation check did not trigger a flip of the user's card.

## Limits

- Dwindle is the tested layout. Other layouts, HDR/color management and individual-window capture need validation.
- Fractional/rotated behavior was tested in a nested output. Physical hot-unplug, suspend/resume and session-lock interruption were not end-to-end tested.
- Pointer, touch and tablet interruption handlers are implemented; only keyboard interruption was automated.
- Long-running GPU/memory stress, dynamically changing size constraints and unusual transient windows need more coverage.
- Hyprglass's independent background is not projected; its original material returns after the turn.
- Browser tests use local pages. No logged-in ChatGPT session is required or exercised.
- Pairs survive config reloads and installer upgrades, but not manual unload or compositor restart.
- The direct installer and manual plugin loading were tested; end-to-end hyprpm installation has not been exercised.

For a desktop crash, inspect the actual core/backtrace before attributing it to a plugin. Report the relevant evidence and triggering action, not a raw core dump.

## Optional container experiment

The hy3 experiment uses separate binaries built by `./scripts/build-containers`.
On 2026-09-20, the same Hyprland 0.56.2/GCC 16.2.1 environment passed **13 container
checks**, **18 native lifecycle checks**, **6 native compatibility checks**, the
independent C++ core test and all **4 installer tests**. The fresh-checkout build
script, wrong-revision rejection, Python/shell syntax and C++ formatting were
also checked. Hyprglass was not included in this experiment's compatibility run.

```sh
./scripts/build-containers
# Start tests/nested_session.py in another terminal as described above.
python tests/containers.py /tmp/hf-test/session.json
python tests/integration.py /tmp/hf-test/session.json \
  --plugin build/containers/core/hyprflip.so
```

The container suite exercises real Wayland terminals: both split axes, the
two-pane limit, outside window placement, per-face focus, release, whole-card
workspace moves, repeated motion, reversal, input/focus interruptions,
fullscreen, config reload, close, external tree edits, and both plugin unload
orders. It captures split faces at rest, across the midpoint, and on an output
with scale 1.6 and transform 1. It waits for a subsequent frame after unload to
catch retained-render-object lifetime failures.

An initial provider-unload run exposed a SIGSEGV in
`Render::CRenderPass::clear()`: a retained hy3 pass had a deleter in the unloaded
library. The provider exit wrapper now removes its pass elements before calling
upstream's exit function. Both active-turn and idle unload/reload checks then
passed with actual `dlclose` enabled. This happened only in the disposable test
compositor; the live desktop library was not replaced.

Later on the same day, **5 workspace trial checks** passed with the installed
Hyprglass 1.0 library. Native dwindle pairs and a workspace-8-only hy3 layout
coexisted; real mark/pair/flip and attach/release shortcuts worked; container
animation temporarily suppressed and restored Hyprglass; reload preserved both
backends; and unpair left all panes accessible. The new check uses the example
trial configuration and copies all loaded libraries into its disposable session:

```sh
# Build both the default core (make) and the container provider first.
python tests/trial.py /tmp/hf-test/session.json --hyprglass /path/to/hyprglass.so
```

The `--all-workspaces` variant passed **9 checks** on the same day. It also
checks converting an existing tiled native pair, preserving a pre-existing
container, overriding saved layouts, creating new workspaces, leaving special
scratchpads on dwindle, moving a whole card and reloading the expanded config.
Native pairs are separated before changing layout and re-paired afterward:
ungrouping after switching exposed an expired hy3 target in the disposable
session. Cleanup unloads Hyprglass last; removing all three libraries in one
parse exposed a separate crash during hy3 layout removal after Hyprglass had
unloaded. The staged cleanup passed. Neither failure was on the real desktop.

The movement/unfold milestone passed **10 workflow checks**, **4 upgrade checks**,
the **13 container checks**, **18 native lifecycle checks**, the C++ core test and
**5 installer tests** on 2026-09-20. Both new suites included Hyprglass 1.0. They
used GPU-rendered headless outputs inside the disposable compositor; the movement
suite added a second output at scale 1.6 with transform 1. Screenshots of unfolded
cards were also inspected.

```sh
make
./scripts/build-containers
python tests/workflows.py /tmp/hf-test/session.json --hyprglass /path/to/hyprglass.so
python tests/container_upgrade.py /tmp/hf-test/session.json \
  --baseline-core /path/to/previous/hyprflip.so \
  --baseline-provider /path/to/previous/libhy3.so \
  --hyprglass /path/to/hyprglass.so
```

Workflow checks cover the exact registered number-row callbacks, directional
reordering and edge behavior, follow/silent focus, cross-output moves, two-to-four
live panes, the actual unfold key chord, unchanged outer footprint, unequal inner
ratios, focused-face refolding, opposite-face folding, release/unpair, reload and
fullscreen guards. A GTK client with a real 900×550 minimum rejects an unfold that
cannot fit. These checks do not establish the size behavior of every application.

Upgrade checks cover read-only dry runs, a fullscreen window blocking restoration,
old-ABI upgrades preserving multiple cards and a native pair, and deliberate load
failure with rollback of both libraries and folded/unfolded cards. During desktop
installation, a fullscreen screensaver initially blocked focus; rollback restored
the old cards. The updater now checks covering fullscreen windows before unloading
and waits for the intended application to receive focus before each restore step.
The subsequent desktop upgrade preserved both existing cards and loaded the new
shortcuts with no config errors.

A final desktop check used three disposable terminals on empty workspaces and
passed unfold/refold plus follow/silent moves between physical landscape and
portrait monitors, both at scale 1.5. It restored the user's existing cards,
workspaces and focus. This check invoked the installed Lua actions: the live
desktop resolves physical keycodes, whereas wtype supplies a custom virtual
keymap. The isolated workflow suite verifies the actual O chord with symbol
resolution enabled and separately checks the installed binding registrations.

Container-specific limits remain: no daily-use soak test, physical hot-unplug,
mixed Wayland/XWayland containers, broad application-specific minimum-size stress
or individual-pane capture validation. Native compatibility results do not
establish those container cases.
See [the experiment guide](docs/CONTAINERS.md) for scope and setup.

## Guided setup

On 2026-09-21, guided creation passed **17 unit/installer tests**, **7 disposable
compositor checks** and **4 live menu checks** on Omarchy 4 / Hyprland 0.56.2.
No compositor source or libraries changed for this feature.

```sh
python -m unittest discover -s tests -p '*_test.py'
python tests/setup_workflows.py /tmp/hf-test/session.json
python scripts/install-setup.py --dry-run
```

The isolated suite covers cancellation at both stages without changing real
windows or a pending mark, one- and two-app backs finishing folded on the front,
ungrouping and recreating, the shipped O callback's two paths, stale selections,
rollback after a refused attachment, and successful creation even when application
minimum sizes prevent a later unfold. Unit checks also cover duplicate titles, control characters, literal
title transport, superseded requests, shortcut conflicts and installer rollback.

The real Omarchy menu was exercised with disposable terminal fixtures on empty
workspaces. Keyboard selection created both two- and three-window cards, already
folded with the front focused and the back excluded from input; Escape
at either stage preserved their layout. The actual portrait and landscape menus
were captured and inspected together. Test windows closed afterward and the
user's original cards, workspaces and focus were restored. This menu test invoked
the helper directly; the installed O registration and its actual Lua callback
are checked separately, since the desktop resolves physical keycodes while wtype
supplies a different virtual keymap.

The wording/completion refinement was rechecked with the same 17 unit/installer,
7 isolated workflow and 4 live menu checks. The revised choices read **Only one
app** and **Add [app name]**. During this smoke test, the shell's default two-second
IPC timeout expired after opening the test windows. The test process used
`OMARCHY_SHELL_IPC_TIMEOUT=5s` and completed; the user's shell timeout was unchanged.

## Editing existing cards

On 2026-09-21, the Omarchy card editor passed **26 unit/installer tests**,
**8 disposable editor workflow checks**, the existing **7 guided creation
checks**, and **9 real menu checks** on the desktop's portrait and landscape
monitors. It uses the existing attach/release actions; no compositor source or
libraries changed.

```sh
python -m unittest discover -s tests -p '*_test.py'
python tests/setup_workflows.py /tmp/hf-test/session.json
python tests/edit_workflows.py /tmp/hf-test/session.json
python scripts/install-setup.py --dry-run
```

The editor suite exercises real front/back attachment, focus on the selected
app, per-face focus memory, the two-app limit, releasing a companion, four-pane
unfolded editing, explicit ungrouping when a side has only one app, cancellation
at both menus, and stale selections after app movement or a flip. A real GTK
minimum-size constraint rejects an attachment; the existing card, original mark
and focus survive. The actual C chord invokes the shipped callback and captures
the focused address for `--edit`; O still unfolds directly. The nested test
enables symbol resolution for wtype and intercepts the command dispatch instead
of opening the desktop's menu from the disposable compositor.

Unit checks additionally cover changed window identity, ownership, fullscreen,
workspace/focus changes, native-group guidance, empty candidate lists and both
shortcut conflicts. Creation and editing share the request lock, so a newer
request supersedes a waiting picker. Installer rollback and repeat installation
remain covered.

The live menu check used three disposable terminal fixtures on empty workspaces.
Keyboard selection added a Telegram-labeled fixture to the WhatsApp side, removed only
that fixture, and explicitly ungrouped the remaining card, on both display
orientations. Escape preserved the layout and active side. Action, app-picker
and full-side menus were captured and inspected together. These checks ran the
helper directly; the installed binding registration is verified separately.
No real messaging account was used. The fixture processes closed afterward and
the user's existing card, active window and monitor workspaces were restored.
The test process used the previously established five-second Omarchy shell IPC
timeout; the user's timeout was unchanged.

Reports are retained in ignored `test-results/edit-workflows.json` and
`test-results/edit-menu.json`; menu captures are in `/tmp/hyprflip-edit-ui/`.

The helper and Lua module were then installed and matched the tested files.
C and O each registered once, with no configuration errors or changes to card
membership, active face, geometry, plugin handles or library hashes. The reload
changed the focused monitor while retaining the active window and all visible
workspaces in the first check. The active window subsequently changed before a
guarded focus restoration could run, so the check left the newer focus alone.

## Either-pane removal and workspace picker

The follow-up editor changes passed **32 unit/installer tests**, **14 editor
workflow checks**, **7 creation checks** and **10 movement/unfold checks** on
2026-09-21. The movement suite included Hyprglass. Compositor libraries were
unchanged; the update is in the shared Python picker.

The full-side menu now offers both apps, identifies the focused one, and retains
the original focus when removing its companion. Both C editing and O creation
list local apps first, then numerically sorted workspace submenus. Back and
Escape do not move windows. App identity, original workspace and card state are
rechecked before the first move. Existing cards, native groups, floating windows
and special workspaces remain excluded from candidates.

The expanded editor suite imports an ordinary app from dwindle on a separate
output at scale 1.5 and transform 1, without switching that output away from its
source workspace. Folded and unfolded cards are covered. Guided creation imports
two apps from different workspaces. An injected creation failure returns both;
a real size-limit rejection during editing returns its imported app while
preserving the original card. Workspace return does not recreate the exact
source tiling tree. Named-workspace recreation and physical hotplug during a
picker operation were not tested.

The GTK fixture now constrains its content before presenting the window. A
Wayland trace confirmed `set_min_size(930, 580)` for its 900×550 content plus
margins, retained in `test-results/gtk-minimum-protocol.txt`. Earlier size-limit
reports relied on a later request that this GTK build did not advertise; the
new creation, editing and unfold checks supersede that minimum-size evidence.

The real Omarchy menu then passed **7 desktop checks** using temporary apps on
empty workspaces. Both monitor orientations showed local apps before workspace
entries, allowed importing a Telegram fixture from workspace 4, and offered
removal of either app while retaining WhatsApp focus when Telegram was removed.
Cancelling the workspace submenu left the source app in place. A separate
creation flow imported its back and finished folded on the front. Menus were
captured and inspected together; results are in `test-results/remote-menu.json` and images in
`/tmp/hyprflip-remote-ui/`. Test windows closed and the user's existing card,
workspaces and focus were restored. As before, only the test helper process used
the five-second Omarchy shell IPC timeout.

Only the tested helper was atomically replaced for this update, with its previous
version backed up. Existing C/O bindings already load that file. Installation
checks confirmed unchanged card state, focus, monitor workspaces, plugin handles,
library bytes and configuration bytes, with no reload or configuration errors.
The result is retained in `test-results/remote-install.json`.
## Three apps per face — 21 September 2026

The ABI 3 container build supports three live tiled applications per face, in
one horizontal or vertical split. This limit belongs to Hyprflip's bridge; hy3
supports larger groups. Adding the third application preserves the existing
split direction and relative pane weights. The setup helper reads the capacity
from status and retains the two-app limit with older providers.

Validation for this extension:

- C++ core tests and all **35 Python tests** passed.
- `tests/three_panes.py`: **9 checks** with Hyprglass, covering three apps on
  both faces, both output orientations, preservation of axis and proportions,
  rejection of a fourth app, focus for every pane, all three removal positions,
  workspace movement, six-pane unfolding, optional third-app setup, remote
  imports, hidden-window closure, and a real application minimum-size refusal
  that returns the candidate to its original workspace. Three-app unfolding
  arranges rows above one another or columns beside one another; a tall GTK
  window also exercises the minimum-size fallback to the alternate axis.
- Existing editor (**14**), guided setup (**7**), movement/unfold (**10**) and
  container lifecycle (**13**) checks passed. Guided setup now also injects a
  failure on the third app after the second has attached successfully; the new
  card is dissolved and the imported app returns to its source workspace.
- Upgrade tests: **5 checks**, including ABI 2 to ABI 3, subsequent upgrades
  with uneven three-pane splits on both faces, and a deliberately invalid core
  that rolls back both libraries and reconstructs folded/unfolded cards.
- Both mixed ABI combinations were loaded in isolation and correctly reported
  the provider as unavailable instead of reading an incompatible snapshot.

The movement suite initially timed out taking a screenshot of a Wayland-nested
output while its parent workspace was hidden. It passed after switching the
disposable compositor to an independent headless output; no production change
was made for this capture issue. All compositor tests target the isolated
session under `/tmp`, not the user's application windows.

`tests/card_motion.py --max-panes 3 --both-faces --require-redraw --captures`
passed all six pane-count/orientation cases and the unfold/instant-switch check.
The GPU-rendered headless output was 3840×2160 at 60 Hz, scale 1.5, tested at
transforms 0 and 1. Each face had one, two or three applications; companion
windows were parked on another workspace so the card footprint stayed constant.

| Orientation | Apps per face | Frame interval p95 | CPU render p95 |
| --- | --- | --- | --- |
| Landscape | 2 | 16.90 ms | 1.89 ms |
| Landscape | 3 | 16.95 ms | 2.21 ms |
| Portrait | 2 | 16.93 ms | 1.98 ms |
| Portrait | 3 | 16.86 ms | 2.15 ms |

Every sampled active frame requested another frame; flips and reversals
preserved exclusive face input and remembered application focus. First-turn CPU
peaks for three-app faces were 23.75 ms landscape and 26.77 ms portrait. These
are compositor render intervals and CPU submission measurements, not GPU
execution times or physical-display scanout guarantees. Capture work was kept
outside the measured turns. Results and images are under the ignored
`test-results/three-motion/` and `test-results/three-panes/` directories.

A batched visual review covered the native menus and six-app flip poses on both
orientations. It led to one layout refinement: perpendicular unfolding avoids
six thin strips. The updated provider passed the nine three-pane checks and
all five upgrade checks again, and a final visual confirmation showed two rows
of three panes on landscape and two columns of three on portrait. The flip
timeline and renderer used for the measurements above were unchanged. The text
"Segmentation fault (core dumped)" behind some original motion captures is the
test compositor's randomly selected Hyprland splash, recorded as `Current splash`
in its startup log, not a crash during the run.

The tested core, provider and helper were installed on the user's already-enabled
desktop. The updater preserved the existing card's membership, active face and
application focus, plus each monitor's selected workspace. The installed files
match the builds and helper in this checkout; configuration errors are empty.
Both libraries, the previous helper and session recovery metadata were backed
up under `~/.local/state/hyprflip/container-update-20260921-120845/`.

Live native-menu verification passed **8 checks** using temporary terminal
fixtures on empty portrait and landscape workspaces: adding a third app through
a remote-workspace submenu, removing an unfocused app from all three choices,
cancelling the third-app setup prompt, and completing guided creation with two
or three reverse apps. Original cards, geometry, displayed workspaces and focus
were restored. The install and UI reports are `test-results/three-install.json`
and `test-results/three-menu.json`; no application data was changed.

The final unfold refinement was installed with another backup at
`~/.local/state/hyprflip/container-update-20260921-121750/`. No cards were
registered at the start of that update; its before/after state, focus and
displayed workspaces matched. Earlier recovery metadata was retained rather
than replaying a card that was no longer registered on the live desktop.

## Transition modes and Chill integration (2026-09-21)

The seven-mode build adds Flip, Vertical flip, Slide, Fade, Dissolve, Portal and
Instant. Dissolve and Portal are experimental. The native picker previews a
round trip before saving a plain mode preference. The Omachill 1.2 adapter adds
workspace protection, selected-app handoff and bounded holds for plugin updates.

Validation on Hyprland 0.56.2 / GCC 16.2.1:

- C++ core checks and **40 Python selection/installer tests** passed.
- **15 transition checks** passed on a GPU-rendered 3840×2160@60 output at
  scale 1.5, in landscape and rotated portrait. Three panes on each face were
  tested with forward/reverse motion, round-trip previews, disabled animation,
  reload, close and unload interruptions. Instant was checked on both outputs.
- Warm median frame intervals were **16.69–16.75 ms**. Per-case 95th percentile
  CPU render submission was **1.26–2.07 ms**; warm face capture was
  **7.43–7.76 ms** once per turn. These are CPU/render-cycle measurements, not
  GPU execution or scanout latency. Screenshot capture was outside timed runs.
- **7 compatibility checks** passed with Portal, including a Wayland/XWayland
  pair, popups/modals, output transforms 0/1/3 at scale 1.6 and Hyprglass.
- The **18 native lifecycle checks** and **5 upgrade/rollback checks** passed.
- **8 Chill workflow checks** passed: ordinary floater geometry restoration,
  cancellation, creation, manual/automatic Chill, app open/close, card movement,
  reload, failed remote import recovery, lease expiry and updates with Auto
  Chill enabled. Upgrade holds survive Lua reloads via an instance-specific
  runtime file; normal window events do not read that file.

The host crash at 12:49 on September 21 was an expired hy3 layout target:
`Hy3Node::as_target()` threw `Attempted to upgrade an expired Hy3Node target`
while `Hy3Layout::newTarget()` mapped a new window. Creating a native group,
changing to hy3, ungrouping and opening a new window reproduced the exception
in a disposable compositor. The provider now prunes expired leaves before
lookup/insertion/geometry traversal and ignores expired windows in iteration.
The pinned upstream checkout remains untouched; CMake builds checked source
copies. **Three repeated migration/floating/container regression checks passed.**
The real desktop was restarted out of Hyprland safe mode with its intact normal
Lua configuration and the tested provider fix.

Reproduce the new checks in a fresh disposable session:

```sh
./scripts/build-containers
python tests/nested_session.py --directory /tmp/hf-check
# In a second terminal, with the same built ABI:
python tests/stale_targets.py /tmp/hf-check/session.json
python tests/transitions.py /tmp/hf-check/session.json --captures
python tests/compatibility.py /tmp/hf-check/session.json \
  --plugin build/containers/core/hyprflip.so --transition portal \
  --hyprglass /path/to/hyprglass.so --output /tmp/hf-check/compat
python integrations/omachill/prepare-source.py /path/to/omachill/chillmode.lua /tmp/chill-hyprflip.lua
python tests/chill_workflows.py /tmp/hf-check/session.json --engine /tmp/chill-hyprflip.lua
```

Render artifacts and metrics for this run are in `/tmp/hf-modes/`, with native
lifecycle and Chill results in `/tmp/hf-final/`. The two orientation contact
sheets were inspected together; pane geometry, orientation and reveal fields
were coherent across the card.

The live Omarchy menu passed **3 end-to-end checks**: a folded card created
from two chilled test apps, Portal preview followed by Escape without changing
the saved mode, and Use Fade surviving a reload with the card protected from
Auto Chill. The native menu and Portal/Hyprglass captures were inspected in the
confirmation pass. Test apps were closed and the original cards, selected
workspaces, focus and Flip preference restored.

The tested core/provider, picker and Omachill source/installed adapter were
installed. Hyprflip, hy3 and Hyprglass loaded together with no configuration
errors. The Omarchy shell needed a relaunch before picker installation; its
real menu flows passed. The shell later hit its default two-second IPC timeout
intermittently; the picker and installer now allow five seconds for shell IPC,
with an eight-second subprocess deadline. The native menu test already used
that five-second allowance. Recovery records are under
`~/.local/state/hyprflip/transition-install-20260921-135016/`, compositor-library
backups under `container-update-20260921-135017/`, and picker/config backups under
`guided-setup-20260921-135345-238757/` in the same state directory.
