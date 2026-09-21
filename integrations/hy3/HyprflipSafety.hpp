// SPDX-License-Identifier: GPL-3.0-only
#pragma once
struct Hy3Node;
// Native target replacement can outlive hy3's weak target. Remove only dead
// leaves and their empty ancestors before a new lookup or geometry traversal.
bool hyprflipPruneExpiredTargets(Hy3Node* root);
