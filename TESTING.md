# Validation

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
