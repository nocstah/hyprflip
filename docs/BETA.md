# Default Omarchy beta test

We are looking for a few people using Omarchy's default **dwindle** layout to
try [Hyprflip 0.3.0-rc.2](https://github.com/nocstah/hyprflip/releases/tag/v0.3.0-rc.2).
No hy3 installation or layout change is needed. This preview targets
**Hyprland 0.56.2** with matching headers and compiler.

## Install

Check `hyprctl version`, then follow the [requirements](INSTALL.md#requirements).
From a terminal in your Hyprland session:

```sh
git clone --branch v0.3.0-rc.2 https://github.com/nocstah/hyprflip.git
cd hyprflip
make test
python3 scripts/install.py --dry-run
python3 scripts/install.py
python3 scripts/install-setup.py
```

The helper uses Omarchy's existing menus. The optional
[OmaCards panel](https://github.com/nocstah/omacards) adds bar controls. Existing
users should follow the [upgrade instructions](INSTALL.md); save and ungroup
active native cards before updating the core.

## Try one card

Use three disposable terminal windows, or apps whose work you have saved.
All shortcuts below use **Super+Ctrl+Alt**.

1. Focus the front app, press **O**, and select the other two apps for the back.
2. Press **F** to flip. Focus either back app, flip twice, and check that focus
   returns to the app you were using.
3. Press **O** to unfold and again to fold. Try your usual laptop resolution
   and scale. Faces may get unequal space to respect app size limits.
4. Press **C** to edit: change a split direction, remove an app and add it back.
   The removed app should remain open.
5. Save the card with a name. Open **L** and select it; the existing card should
   be focused without duplicating any apps.
6. Save any work, close those test apps, and open the saved card again from **L**.
   Apps with supported launchers should reopen on their saved workspace.
7. Float, move and resize the card, then tile it again. Check that both faces
   keep their membership and can still flip.

If app constraints make unfolding impossible, the card should remain folded
and usable. Report unexpected refusal with the apps and display size; do not
change the default desktop layout to work around it.

## Send feedback

[Open an issue](https://github.com/nocstah/hyprflip/issues/new?template=bug_report.yml)
with a short result, including successful installs:

```text
Omarchy version:
Hyprland version/commit:
Hyprflip tag/commit:
Default dwindle, without hy3: yes / no
Display resolution and scale:
Apps tested:
Install: pass / blocked at command ...
Create / flip / unfold / edit: ...
Save and reopen existing / closed apps: ...
Float, resize and tile again: ...
Anything confusing or unexpected:
```

Current evidence includes a fresh home with stock Omarchy configuration and
real menus, plus nested compositor and live-desktop checks. A fresh OS install
and reports from independent users are still needed before 0.3.0 becomes stable.
