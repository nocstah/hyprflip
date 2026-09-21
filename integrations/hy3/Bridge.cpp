// SPDX-License-Identifier: GPL-3.0-only
// Compiled into hy3, not into the MIT Hyprflip module. Uses hy3's own tree
// operations; the registry holds weak references, never a second layout tree.
#include "ContainerABI.hpp"
#include "globals.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/state/WorkspaceState.hpp>
#include <map>

namespace {
using namespace Hyprflip;
struct Card {
    WP<Hy3Node> node;
    bool unfolded = false;
};
std::map<uint64_t, Card> cards;
uint64_t nextID = 1;

PHLWINDOW window(uintptr_t id) {
    for (const auto &w : Desktop::windowState()->windows())
        if (reinterpret_cast<uintptr_t>(w.get()) == id && w->m_isMapped)
            return w;
    return nullptr;
}
uintptr_t address(PHLWINDOW w) { return reinterpret_cast<uintptr_t>(w.get()); }
Hy3Node *node(uintptr_t id) {
    auto w = window(id);
    if (!w || w->m_isFloating || w->m_group)
        return nullptr;
    auto layout = hy3InstanceForWorkspace(w->m_workspace);
    return layout ? layout->getNodeFromWindow(w.get()) : nullptr;
}
Hy3GroupNode *root(uint64_t id) {
    auto it = cards.find(id);
    if (it == cards.end() || !it->second.node || !it->second.node->is_group())
        return nullptr;
    return &it->second.node->as_group();
}
bool belongs(Hy3Node &n) {
    for (const auto &[id, card] : cards)
        if (card.node)
            for (auto &ancestor : n.ancestors())
                if (&ancestor == card.node.get())
                    return true;
    return false;
}
bool supports(uintptr_t id) {
    auto n = node(id);
    return n && n->is_target() && !belongs(*n);
}
void update(Hy3Layout *layout, bool instant = true) {
    layout->recalcGeometry(instant);
    layout->root->updateTabBarRecursive();
    layout->updateGroupBorderColors();
}
Hy3Node *face(Hy3GroupNode &r, uint32_t side) {
    if (side > 1 || r.children.size() != 2)
        return nullptr;
    return (side ? r.children.back() : r.children.front()).get();
}
bool inspect(uint64_t id, ContainerSnapshot *out) {
    auto r = root(id);
    if (!r || !r->parent || r->children.size() != 2)
        return false;
    const bool unfolded = cards.at(id).unfolded;
    if (unfolded ? !r->isSplit() : !r->isTab())
        return false;
    ContainerSnapshot result;
    result.unfolded = unfolded;
    for (uint32_t side = 0; side < 2; ++side) {
        auto f = face(*r, side);
        if (r->focused_child == f)
            result.active = side;
        auto add = [&](Hy3Node &n) {
            if (!n.is_target() || !n.valid())
                return false;
            auto w = n.as_window();
            if (!w || !w->m_isMapped || w->m_isFloating || w->m_group ||
                hy3InstanceForWorkspace(w->m_workspace) != r->Hy3Node::layout())
                return false;
            result.windows[side][result.count[side]++] = address(w);
            return true;
        };
        if (f->is_target()) {
            if (!add(*f))
                return false;
        } else {
            auto &split = f->as_group();
            if (!split.isSplit() || split.children.empty() || split.children.size() > CONTAINER_MAX_PANES)
                return false;
            for (const auto &child : split.children)
                if (!add(*child))
                    return false;
        }
        auto &focused = f->getFocusedNode(true);
        if (!focused.is_target())
            return false;
        result.focused[side] = address(focused.as_window());
    }
    const auto &box = r->visualBox;
    result.x = box.x;
    result.y = box.y;
    result.width = box.w;
    result.height = box.h;
    if (out)
        *out = result;
    return true;
}
bool applySelection(uint64_t id, uint32_t side, bool focus, bool instant) {
    if (side > 1 || !inspect(id, nullptr))
        return false;
    auto r = root(id);
    auto f = face(*r, side);
    r->focused_child = f;
    r->group_focused = false;
    auto &leaf = f->getFocusedNode(true);
    if (focus)
        leaf.markFocused();
    update(r->Hy3Node::layout(), instant);
    if (focus)
        leaf.focus(false, Desktop::FOCUS_REASON_KEYBIND);
    return true;
}
bool select(uint64_t id, uint32_t side, bool focus) { return applySelection(id, side, focus, true); }
uint64_t create(uintptr_t front, uintptr_t back) {
    if (front == back || !supports(front) || !supports(back))
        return 0;
    auto a = node(front), b = node(back);
    auto layout = a->layout();
    if (layout != b->layout())
        return 0;
    // Extract before wrapping: collapse may simplify the source's ancestors,
    // but both leaf nodes retain their identities.
    auto moved = b->parent->extractAndMerge(*b, nullptr, CollapsePolicy::InvalidOnly);
    a->wrap(Hy3GroupLayout::Tabbed, GroupEphemeralityOption::Standard, false);
    auto &r = a->parent->as_group();
    r.insertChild(std::move(moved));
    r.locked = true;
    const auto id = nextID++;
    cards.emplace(id, Card{r.self});
    select(id, 0, true);
    return id;
}
bool attach(uint64_t id, uintptr_t child, uint32_t side, bool vertical) {
    ContainerSnapshot state;
    if (side > 1 || !inspect(id, &state) || state.count[side] >= CONTAINER_MAX_PANES || !supports(child))
        return false;
    auto r = root(id);
    auto n = node(child);
    auto layout = r->Hy3Node::layout();
    if (n->layout() != layout)
        return false;
    auto moved = n->parent->extractAndMerge(*n, nullptr, CollapsePolicy::InvalidOnly);
    auto f = face(*r, side);
    // A single-child split left by hy3 after a close is reused.
    if (f->is_target()) {
        f->wrap(vertical ? Hy3GroupLayout::SplitV : Hy3GroupLayout::SplitH, GroupEphemeralityOption::Standard, false);
        f = face(*r, side);
    }
    auto &split = f->as_group();
    // An existing row/column keeps its direction and relative pane weights.
    // The H/V choice only establishes a split when adding the second app.
    if (state.count[side] == 1)
        split.setLayout(vertical ? Hy3GroupLayout::SplitV : Hy3GroupLayout::SplitH);
    split.locked = true;
    split.insertChild(std::move(moved));
    select(id, side, true);
    return true;
}
bool dissolve(uint64_t id) {
    auto r = root(id);
    if (r && r->parent) {
        auto layout = r->Hy3Node::layout();
        r->locked = false;
        // Only undo locks and tabbing owned by the card. Existing enclosing
        // groups and externally added children stay in the hy3 tree.
        for (const auto &f : r->children)
            if (f->is_group())
                f->as_group().locked = false;
        if (r->isTab())
            r->setLayout(Hy3GroupLayout::SplitH);
        r->collapseParents(CollapsePolicy::SingleNodeGroups);
        update(layout);
    }
    return cards.erase(id) != 0;
}
bool release(uint64_t id, uintptr_t child) {
    ContainerSnapshot state;
    if (!inspect(id, &state))
        return false;
    int side = -1;
    for (unsigned s = 0; s < 2; ++s)
        for (unsigned i = 0; i < state.count[s]; ++i)
            if (state.windows[s][i] == child)
                side = int(s);
    if (side < 0)
        return false;
    // Releasing the last pane on a side dissolves the two-sided card.
    if (state.count[side] == 1)
        return dissolve(id);
    auto r = root(id);
    auto layout = r->Hy3Node::layout();
    auto n = node(child);
    auto moved = n->parent->extractAndMerge(*n, nullptr, CollapsePolicy::InvalidOnly);
    // Insert beside the entire card, never inside the opposite face.
    auto &parent = r->parent->as_group();
    parent.insertChild(std::next(parent.findChild(*r)), std::move(moved));
    update(layout);
    n->focus(false, Desktop::FOCUS_REASON_KEYBIND);
    return true;
}
bool restoreSelection(uint64_t id, const ContainerSnapshot &state, bool focus) {
    auto r = root(id);
    if (!r || r->children.size() != 2)
        return false;
    for (uint32_t side = 0; side < 2; ++side) {
        auto f = face(*r, side);
        if (f->is_group()) {
            auto remembered = node(state.focused[side]);
            if (remembered && remembered->parent.get() == f) {
                f->as_group().focused_child = remembered;
                f->as_group().group_focused = false;
            }
        }
    }
    return applySelection(id, state.active, focus, false);
}
bool fits(uint64_t id) {
    ContainerSnapshot state;
    if (!inspect(id, &state))
        return false;
    for (uint32_t side = 0; side < 2; ++side)
        for (uint32_t i = 0; i < state.count[side]; ++i) {
            auto w = window(state.windows[side][i]);
            if (!w)
                return false;
            const auto size = w->size(Desktop::View::IGeometric::GEOMETRIC_GOAL);
            const auto min = w->minSize(), max = w->maxSize();
            if ((min && (size.x < min->x || size.y < min->y)) || (max && (size.x > max->x || size.y > max->y)))
                return false;
        }
    return true;
}
bool edit(uint64_t id, uintptr_t child, ContainerEdit operation) {
    ContainerSnapshot before;
    if (!inspect(id, &before))
        return false;
    uint32_t side = 2, index = 0;
    for (uint32_t s = 0; s < 2; ++s)
        for (uint32_t i = 0; i < before.count[s]; ++i)
            if (before.windows[s][i] == child) { side = s; index = i; }
    if (side > 1 || before.count[side] < 2 ||
        (operation == ContainerEdit::OtherSide && before.count[1 - side] >= CONTAINER_MAX_PANES))
        return false;
    if (operation != ContainerEdit::Horizontal && operation != ContainerEdit::Vertical &&
        operation != ContainerEdit::Balance && operation != ContainerEdit::OtherSide)
        return false;
    auto r = root(id);
    auto layout = r->Hy3Node::layout();
    auto n = node(child);
    auto &source = face(*r, side)->as_group();
    std::array<Hy3GroupLayout, 2> axes;
    std::map<uintptr_t, float> weights;
    for (uint32_t s = 0; s < 2; ++s) {
        auto f = face(*r, s);
        axes[s] = f->is_group() ? f->as_group().layout : Hy3GroupLayout::SplitH;
        for (uint32_t i = 0; i < before.count[s]; ++i)
            weights[before.windows[s][i]] = f->is_group() ? node(before.windows[s][i])->size_ratio : 1.F;
    }
    auto selection = before;
    bool wrapped = false;
    if (operation == ContainerEdit::OtherSide) {
        auto destination = face(*r, 1 - side);
        if (destination->is_target()) {
            wrapped = true;
            destination->wrap(before.width >= before.height ? Hy3GroupLayout::SplitH : Hy3GroupLayout::SplitV,
                              GroupEphemeralityOption::Standard, false);
            destination = face(*r, 1 - side);
        }
        auto &target = destination->as_group();
        source.collapseExpansions();
        target.collapseExpansions();
        auto moved = source.extractChildRaw(*n);
        // Preserve the remaining panes' relative sizes, including very unequal
        // splits. Subtracting the same weight from every pane can go negative.
        float total = 0;
        for (const auto &c : source.children) total += c->size_ratio;
        for (const auto &c : source.children) c->size_ratio *= source.children.size() / total;
        moved->size_ratio = 1.F;
        target.insertChild(std::move(moved));
        target.locked = true;
        selection.active = 1 - side;
        selection.focused[1 - side] = child;
        selection.focused[side] = address(source.getFocusedNode(true).as_window());
    } else if (operation == ContainerEdit::Balance) {
        for (const auto &c : source.children) c->size_ratio = 1.F;
    } else {
        source.setLayout(operation == ContainerEdit::Vertical ? Hy3GroupLayout::SplitV : Hy3GroupLayout::SplitH);
    }
    update(layout, false);
    if (fits(id))
        return restoreSelection(id, selection, true);
    // Roll back in place. Do not dissolve/recreate the card, collapse ancestors
    // or leave a pane outside it when application size limits reject a change.
    if (operation == ContainerEdit::OtherSide) {
        auto moved = n->parent->as_group().extractChildRaw(*n);
        source.insertChild(std::next(source.children.begin(), index), std::move(moved));
        if (wrapped) {
            auto &wrapper = face(*r, 1 - side)->as_group();
            auto original = wrapper.extractChildRaw(wrapper.children.begin());
            r->replaceChild(r->findChild(wrapper), std::move(original));
        }
    }
    for (uint32_t s = 0; s < 2; ++s) {
        auto f = face(*r, s);
        if (f->is_group()) {
            f->as_group().setLayout(axes[s]);
            for (uint32_t i = 0; i < before.count[s]; ++i)
                node(before.windows[s][i])->size_ratio = weights.at(before.windows[s][i]);
        }
    }
    restoreSelection(id, before, true);
    return false;
}
bool workspace(uint64_t id, uint32_t destination, bool follow) {
    ContainerSnapshot state;
    if (!destination || destination > INT32_MAX || !inspect(id, &state))
        return false;
    auto r = root(id);
    auto layout = r->Hy3Node::layout();
    auto origin = layout->workspace();
    auto target = State::workspaceState()->query().id(destination).run();
    if (!target)
        target = State::workspaceState()->create(destination, origin->monitorID(), std::to_string(destination));
    if (!target || !hy3InstanceForWorkspace(target))
        return false;
    if (target == origin)
        return true;
    // Select the container only inside this synchronous tree operation, then
    // return keyboard focus to the remembered real application immediately.
    r->markFocused();
    layout->moveNodeToWorkspace(origin.get(), std::to_string(destination), follow, false);
    // Workspace activation can temporarily focus its first visible window.
    // Restore each face's remembered pane before returning application focus.
    if (!restoreSelection(id, state, follow))
        return false;
    if (!follow) {
        // Never leave keyboard focus on a window now living on another
        // workspace. The source tree retains its nearest remaining selection.
        PHLWINDOW next;
        if (auto n = layout->getWorkspaceFocusedNode(origin.get(), true); n && n->is_target() && n->valid())
            next = n->as_window();
        if (!next)
            for (const auto &w : Desktop::windowState()->windows())
                if (w->m_workspace == origin && w->m_isMapped && !w->isHidden()) {
                    next = w;
                    break;
                }
        Desktop::focusState()->fullWindowFocus(next, Desktop::FOCUS_REASON_KEYBIND);
        Desktop::focusState()->rawMonitorFocus(origin->m_monitor.lock());
    }
    return true;
}
bool move(uint64_t id, uint32_t direction) {
    ShiftDirection shift;
    switch (direction) {
    case 'l':
        shift = ShiftDirection::Left;
        break;
    case 'r':
        shift = ShiftDirection::Right;
        break;
    case 'u':
        shift = ShiftDirection::Up;
        break;
    case 'd':
        shift = ShiftDirection::Down;
        break;
    default:
        return false;
    }
    ContainerSnapshot state;
    if (!inspect(id, &state))
        return false;
    auto r = root(id);
    // At an outer edge, hy3's structural move can create an invisible wrapper
    // that consumes the next opposite move. Window-style arrow keys should
    // simply stop there and reorder only towards an existing neighbor.
    if (!r->findNeighbor(shift))
        return true;
    r->Hy3Node::layout()->shiftNode(*r, shift, false, true);
    return restoreSelection(id, state, true);
}
bool unfold(uint64_t id, bool enabled) {
    ContainerSnapshot state;
    if (!inspect(id, &state))
        return false;
    if (bool(state.unfolded) == enabled)
        return true;
    auto r = root(id);
    auto layout = r->Hy3Node::layout();
    if (!enabled) {
        cards.at(id).unfolded = false;
        r->setLayout(Hy3GroupLayout::Tabbed);
        return restoreSelection(id, state, true);
    }
    // Reuse the faces and their ratios. A three-app row needs room across the
    // card, so stack faces; for a three-app column, put faces side by side.
    // Mixed orientations keep the footprint heuristic. Application limits can
    // still select the alternate axis below.
    auto preferred = state.width >= state.height ? Hy3GroupLayout::SplitH : Hy3GroupLayout::SplitV;
    bool threeAcross = false, threeDown = false;
    for (uint32_t side = 0; side < 2; ++side)
        if (state.count[side] == 3) {
            threeAcross |= face(*r, side)->as_group().layout == Hy3GroupLayout::SplitH;
            threeDown |= face(*r, side)->as_group().layout == Hy3GroupLayout::SplitV;
        }
    if (threeAcross != threeDown)
        preferred = threeAcross ? Hy3GroupLayout::SplitV : Hy3GroupLayout::SplitH;
    const auto alternate = preferred == Hy3GroupLayout::SplitH ? Hy3GroupLayout::SplitV : Hy3GroupLayout::SplitH;
    cards.at(id).unfolded = true;
    for (const auto axis : {preferred, alternate}) {
        r->setLayout(axis);
        update(layout, false);
        if (fits(id))
            return restoreSelection(id, state, true);
    }
    cards.at(id).unfolded = false;
    r->setLayout(Hy3GroupLayout::Tabbed);
    restoreSelection(id, state, true);
    return false;
}
void animating(uint64_t id, bool enabled) {
    auto r = root(id);
    if (!r || !r->tab_bar)
        return;
    // hy3's tab bar lives outside individual window render passes. Hide only
    // this card's bar during motion; keep its space reserved to avoid a reflow.
    if (enabled)
        r->tab_bar->hidden = true;
    else
        r->updateTabBar(true);
    g_pHyprRenderer->damageBox(r->visualBox);
}
const ContainerAPI api{CONTAINER_ABI_VERSION,
                       sizeof(ContainerAPI),
                       uint64_t(std::chrono::steady_clock::now().time_since_epoch().count()),
                       supports,
                       create,
                       inspect,
                       select,
                       attach,
                       release,
                       dissolve,
                       workspace,
                       move,
                       unfold,
                       edit,
                       animating};
} // namespace

extern "C" __attribute__((visibility("default"))) const Hyprflip::ContainerAPI *hyprflip_hy3_bridge_v4() {
    return &api;
}

extern "C" void hy3_original_plugin_exit();
APICALL EXPORT void PLUGIN_EXIT() {
    // Hyprland retains the previous frame's pass until beginRender(). A
    // Hy3TabPassElement's deleter must not survive dlclose of this module.
    g_pHyprRenderer->m_renderPass.removeAllOfType("Hy3TabPassElement");
    cards.clear();
    hy3_original_plugin_exit();
}
