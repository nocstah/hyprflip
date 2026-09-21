// SPDX-License-Identifier: GPL-3.0-only
#include "HyprflipSafety.hpp"
#include "Hy3Node.hpp"
#include <cmath>

bool hyprflipPruneExpiredTargets(Hy3Node* root) {
    if (!root || !root->is_group()) return false;
    auto& group = root->as_group();
    bool removed = false;
    for (auto it = group.children.begin(); it != group.children.end();) {
        auto current = it++;
        auto* child = current->get();
        const bool pruned = hyprflipPruneExpiredTargets(child);
        if ((child->is_target() && !child->valid()) ||
            (pruned && child->is_group() && child->as_group().children.empty())) {
            // Raw extraction updates the non-owning focused_child and parent
            // links without traversing the target that has already expired.
            group.extractChildRaw(current);
            removed = true;
        }
    }
    if (!removed) return false;
    if (group.children.empty()) {
        group.expand_focused = ExpandFocusType::NotExpanded;
        return true;
    }
    double total = 0;
    for (auto& child : group.children) total += child->size_ratio;
    if (std::isfinite(total) && total > 0)
        for (auto& child : group.children)
            child->size_ratio *= double(group.children.size()) / total;
    return true;
}
