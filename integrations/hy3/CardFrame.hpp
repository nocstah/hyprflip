// SPDX-License-Identifier: GPL-3.0-only
#pragma once
class Hy3Node;
// Zero leaves an ordinary hy3 group untouched. Positive values replace the
// owned card's tab strip with space for Hyprflip's compact controls.
double hyprflipCardHeader(const Hy3Node *node);
// Applies only inside an owned card. Negative inherits the workspace gaps.
double hyprflipCardGap(const Hy3Node *node);
