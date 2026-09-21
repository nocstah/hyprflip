# Desktop crash during a live update

At 15:41:26 Asia/Bangkok on 2026-09-21, the desktop compositor (PID 898916,
Hyprland 0.56.2) received SIGSEGV while processing `plugin unload` for the
installed Hyprflip core. Its crash handler subsequently aborted. The updater
had backed up the installation but had not copied the candidate libraries or
run the setup installer.

## Evidence

The symbolized main-thread stack reaches:

```text
Hyprflip::Controller::~Controller
  hy3 bridge dissolve → update → Hy3Layout::recalcGeometry
  Hy3Node::recalcSizePosRecursive
  Layout::CWindowTarget::updatePos
  Desktop::View::CWindow::updateWindowDecos
  stale unique-pointer deletion callback
```

The pending decoration's callback was `0x7fcce45aa7c0`; its virtual-table pointer
was `0x7fcce45fb390`. In the preserved Hyprglass library (build ID
`414e96f509ff1295e080e0b1a0baf339c08c4be8`):

- The `CUniquePointer<CGlassDecoration>` deletion callback is at `0x397c0`.
- `vtable for CGlassDecoration` is at `0x8a380`; the object uses its address
  point 16 bytes later.

Both independently reconstruct the same former library base,
`0x7fcce4571000`. That image was no longer mapped: the stale addresses fell
inside a font mapping. A different Hyprglass image was still loaded elsewhere,
and its build ID no longer matched the library on disk when GDB read the core.
The installed Hyprglass file also changed during this session.

This supports a stale Hyprglass decoration surviving a prior plugin
unload/reload. Hyprflip card dissolution triggered its pending deletion. The
precise removal/queueing bug in Hyprglass has not been reproduced in isolation;
there is no evidence that saved-card or peek code ran in this crash. The
updater leaves Hyprglass loaded throughout its own replacement sequence.

There was no OOM event around the crash. A subsequent safe-mode compositor
also crashed during Aquamarine DRM-backend shutdown; that separate stack did
not involve Hyprflip. A normal desktop session was running afterward.

## Recovery and follow-up

The installed core and provider still match their pre-update backups. The setup
helper and shortcuts were not updated. Session-specific reconstruction metadata
is at `~/.local/state/hyprflip/container-update-20260921-154126/recovery.json`.
It records WhatsApp + Telegram opposite Gmail on workspace 2. Old window
addresses cannot be replayed after a compositor restart; the apps must be
matched again. Unsaved application content is not part of this metadata.

The updater now restores previous library files even when IPC disappears during
rollback, and reports focus-cleanup failures without replacing the original
exception. A simulated compositor-loss test verifies this behavior.

Further live installation was withheld pending coordination of the concurrent
Hyprglass changes. Fix and verify decoration cleanup before hot-replacing that
plugin. The six disposable upgrade checks passed with the preserved Hyprglass
build, including forced focus interference and rollback; they did not exercise
concurrent Hyprglass replacement.

Local diagnostic records: `/tmp/hyprflip-unload-crash-info.txt`,
`/tmp/hyprflip-unload-gdb.txt`, `/tmp/hyprflip-decoration-gdb.txt`, and
`/tmp/hyprflip-saved-install-final.log`. Both temporary core extracts were
deleted after inspection.
