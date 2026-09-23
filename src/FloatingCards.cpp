#include "FloatingCards.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <hyprland/src/config/values/types/CssGapValue.hpp>
#include <hyprland/src/config/shared/workspace/WorkspaceRuleManager.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/layout/space/Space.hpp>
#include <hyprland/src/layout/target/Target.hpp>
#include <hyprland/src/layout/target/WindowGroupTarget.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <hyprland/src/state/WorkspaceState.hpp>
#include <map>
#include <memory>
#include <numeric>

namespace Hyprflip::FloatingCards {
using namespace Desktop::View;
using namespace Layout;
namespace {
struct Card;
std::map<uint64_t, std::shared_ptr<Card>> cards;
uint64_t nextID = 1;
PHLWINDOW resolve(uintptr_t address) {
    for (const auto &w : Desktop::windowState()->windows())
        if (reinterpret_cast<uintptr_t>(w.get()) == address && w->m_isMapped)
            return w;
    return nullptr;
}
uintptr_t addr(PHLWINDOW w) { return reinterpret_cast<uintptr_t>(w.get()); }

// Only the core-owned CGroup target enters a layout. This adapter turns its
// outer geometry into a pane rectangle, then delegates to the original target.
// Retaining the original is essential: restore it before ungrouping/unloading.
class PaneTarget final : public ITarget {
  public:
    SP<ITarget> original;
    std::weak_ptr<Card> card;
    static SP<PaneTarget> create(SP<ITarget> original, const std::shared_ptr<Card> &card) {
        auto p = makeShared<PaneTarget>();
        p->original = original;
        p->card = card;
        p->m_self = p;
        p->m_space = original->space();
        p->m_ghostSpace = true;
        return p;
    }
    eTargetType type() override { return TARGET_TYPE_WINDOW; }
    PHLWINDOW window() const override { return original->window(); }
    CBox position() const override { return original->position(); }
    void setPositionGlobal(const STargetBox &, uint8_t) override;
    void recalc() override;
    void assignToSpace(const SP<CSpace> &space, std::optional<Vector2D> focal = {}) override {
        // Native group removal can happen outside our dispatcher. Hand back the
        // real window target before it can enter any layout on its own.
        auto w = window();
        if (w && w->m_target.get() == this)
            w->m_target = original;
        original->assignToSpace(space, focal);
        m_space = space;
    }
    void setSpaceGhost(const SP<CSpace> &space) override {
        m_space = space;
        m_ghostSpace = true;
        original->setSpaceGhost(space);
    }
    bool floating() override { return original->floating(); }
    void setFloating(bool value) override { original->setFloating(value); }
    std::expected<SGeometryRequested, eGeometryFailure> desiredGeometry() override;
    std::optional<Vector2D> minSize() override { return original->minSize(); }
    std::optional<Vector2D> maxSize() override { return original->maxSize(); }
    void damageEntire() override { original->damageEntire(); }
    void warpPositionSize() override { original->warpPositionSize(); }
    void onUpdateSpace() override { original->onUpdateSpace(); }
};
struct Card {
    std::array<std::vector<PHLWINDOWREF>, 2> faces;
    std::array<PHLWINDOWREF, 2> focused;
    std::array<bool, 2> vertical{};
    std::array<std::vector<double>, 2> ratios;
    std::map<uintptr_t, SP<PaneTarget>> targets;
    SP<CGroup> group;
    unsigned active = 0;
    bool unfolded = false, unfoldVertical = false, alive = true, adjusting = false, changing = false;
    CBox initial;
    double header = 0;
    double gapOverride = -1;

    double gap(bool vertical) const {
        if (gapOverride >= 0) return gapOverride;
        static auto value = CConfigValue<Config::IComplexConfigValue>("general:gaps_in");
        const auto workspace = group ? group->m_target->workspace() : faces[0].empty() || !faces[0][0] ? nullptr : faces[0][0]->m_workspace;
        auto rule = Config::workspaceRuleMgr()->getWorkspaceRuleFor(workspace);
        auto g = rule.and_then([](auto r) { return r.m_gapsIn; })
                     .value_or(*static_cast<Config::CCssGapData *>(value.ptr()));
        return std::max<int64_t>(0, vertical ? g.m_top + g.m_bottom : g.m_left + g.m_right);
    }

    std::optional<unsigned> side(PHLWINDOW w) const {
        for (unsigned s = 0; s < 2; ++s)
            if (std::ranges::find(faces[s], w) != faces[s].end())
                return s;
        return {};
    }
    bool valid() const {
        if (!alive || !group || faces[0].empty() || faces[1].empty() || group->size() != targets.size())
            return false;
        for (const auto &[_, p] : targets) {
            auto w = p->window();
            if (!w || !w->m_isMapped || w->m_group != group || w->m_target != p)
                return false;
        }
        return true;
    }
    bool preferVerticalUnfold() const {
        bool rows = false, columns = false;
        for (unsigned side = 0; side < 2; ++side)
            if (faces[side].size() >= 3) (vertical[side] ? columns : rows) = true;
        return rows && !columns;
    }
    CBox faceBox(CBox box, unsigned s) const {
        box.y += header;
        box.h = std::max(1., box.h - header);
        if (unfolded) {
            if (unfoldVertical) {
                box.h = std::max(1., (box.h - gap(true)) / 2);
                box.y += s * (box.h + gap(true));
            } else {
                box.w = std::max(1., (box.w - gap(false)) / 2);
                box.x += s * (box.w + gap(false));
            }
        }
        return box;
    }
    CBox paneBox(CBox outer, unsigned s, unsigned index) const {
        auto box = faceBox(outer, s);
        const auto n = faces[s].size();
        const double space = std::max(1., (vertical[s] ? box.h : box.w) - gap(vertical[s]) * (n - 1));
        double start = 0;
        for (unsigned i = 0; i < index; ++i)
            start += ratios[s][i] * space + gap(vertical[s]);
        const double extent = ratios[s][index] * space;
        if (vertical[s]) {
            box.y += std::round(start);
            box.h = std::round(start + extent) - std::round(start);
        } else {
            box.x += std::round(start);
            box.w = std::round(start + extent) - std::round(start);
        }
        return box;
    }
    Vector2D minimum() const {
        std::array<Vector2D, 2> sizes{};
        for (unsigned s = 0; s < 2; ++s) {
            for (unsigned i = 0; i < faces[s].size(); ++i) {
                if (!faces[s][i])
                    continue;
                auto min = faces[s][i]->minSize().value_or(Vector2D{40, 40});
                const auto border = faces[s][i]->getRealBorderSize();
                min += Vector2D{2. * border, 2. * border};
                sizes[s].x = std::max(sizes[s].x, vertical[s] ? min.x : min.x / ratios[s][i]);
                sizes[s].y = std::max(sizes[s].y, vertical[s] ? min.y / ratios[s][i] : min.y);
            }
            (vertical[s] ? sizes[s].y : sizes[s].x) += gap(vertical[s]) * (faces[s].size() - 1);
        }
        const double width = std::max(sizes[0].x, sizes[1].x), height = std::max(sizes[0].y, sizes[1].y);
        return {unfolded && !unfoldVertical ? 2 * width + gap(false) : width,
                (unfolded && unfoldVertical ? 2 * height + gap(true) : height) + header};
    }
    bool fits(CBox box) const {
        for (unsigned s = 0; s < 2; ++s)
            for (unsigned i = 0; i < faces[s].size(); ++i) {
                if (!faces[s][i])
                    return false;
                auto size = paneBox(box, s, i).size();
                const auto border = faces[s][i]->getRealBorderSize();
                size -= Vector2D{2. * border, 2. * border};
                auto min = faces[s][i]->minSize().value_or(Vector2D{1, 1});
                auto max = faces[s][i]->maxSize().value_or(Vector2D{1e9, 1e9});
                if (size.x < min.x || size.y < min.y || size.x > max.x || size.y > max.y)
                    return false;
            }
        return true;
    }
    void visibility() {
        if (!alive || changing)
            return;
        PHLWINDOW fullscreen;
        for (const auto &[_, p] : targets)
            if (auto w = p->window(); w && Fullscreen::controller()->isFullscreen(w))
                fullscreen = w;
        for (unsigned s = 0; s < 2; ++s)
            for (auto &ref : faces[s])
                if (auto w = ref.lock()) {
                    const bool shown = fullscreen ? w == fullscreen : unfolded || s == active;
                    w->setInputBlocked(INPUT_BLOCK_GROUP_INACTIVE, !shown);
                    w->alpha(WINDOW_ALPHA_LAYOUT)->setValueAndWarp(shown ? 1.F : 0.F);
                }
    }
    void decos() {
        for (const auto &[_, p] : targets)
            if (auto w = p->window()) {
                std::vector<IHyprWindowDecoration *> remove;
                for (const auto &d : w->m_windowDecorations)
                    if (d->getDecorationType() == DECORATION_GROUPBAR)
                        remove.push_back(d.get());
                for (auto d : remove)
                    w->removeWindowDeco(d);
            }
    }
    void refresh() {
        if (!alive || !group || changing)
            return;
        // Edits may have updated the group's logical box. Let the tiled
        // algorithm restore its visual slot (including outer/neighbor gaps)
        // before splitting it into panes.
        if (!group->m_target->floating() && group->m_target->space())
            group->m_target->space()->recalculate();
        else
            group->m_target->recalc();
        visibility();
        for (const auto &[_, p] : targets) {
            p->warpPositionSize();
            p->damageEntire();
        }
    }
    void restore(PHLWINDOW w) {
        auto it = targets.find(addr(w));
        if (it == targets.end())
            return;
        if (w->m_target == it->second)
            w->m_target = it->second->original;
        targets.erase(it);
    }
    void dissolve() {
        if (!alive)
            return;
        alive = false;
        auto copy = targets;
        for (auto &[_, p] : copy)
            if (auto w = p->window())
                restore(w);
        if (group && group->size()) {
            group->setLocked(false);
            group->destroy();
        }
        group.reset();
    }
    ~Card() { dissolve(); }
};
void PaneTarget::setPositionGlobal(const STargetBox &box, uint8_t flags) {
    auto c = card.lock();
    auto w = window();
    if (!c || !c->alive || !w || w->m_group != c->group || c->changing) {
        original->setPositionGlobal(box, flags);
        return;
    }
    auto side = c->side(w);
    if (!side)
        return;
    CBox outer = box.visualBox.empty() ? box.logicalBox : box.visualBox;
    if (floating() && !Fullscreen::controller()->isFullscreen(w) && !c->adjusting) {
        auto min = c->minimum();
        if (outer.w < min.x || outer.h < min.y) {
            c->adjusting = true;
            outer.w = std::max(outer.w, min.x);
            outer.h = std::max(outer.h, min.y);
            c->group->m_target->setPositionGlobal({.logicalBox = outer, .visualBox = {}}, flags);
            c->adjusting = false;
            return;
        }
    }
    auto index = std::ranges::find(c->faces[*side], w) - c->faces[*side].begin();
    auto pane = Fullscreen::controller()->isFullscreen(w) ? outer : c->paneBox(outer, *side, index);
    // Tiled window targets inset their visual slot by the window's border.
    // Floating targets accept a content rectangle directly. Use the same slot
    // interpretation here so the empty gap is identical in both modes.
    if (floating() && !Fullscreen::controller()->isFullscreen(w))
        pane.expand(-w->getRealBorderSize());
    m_box = {pane, pane};
    original->setPositionGlobal(m_box, flags);
    c->visibility();
}
void PaneTarget::recalc() {
    if (auto c = card.lock(); c && c->alive && c->group && !c->changing)
        c->group->m_target->recalc();
    else
        original->recalc();
}
std::expected<SGeometryRequested, eGeometryFailure> PaneTarget::desiredGeometry() {
    if (auto c = card.lock(); c && c->alive) {
        auto box = c->group ? c->group->m_target->position() : c->initial;
        if (box.w < 1 || box.h < 1)
            box = c->initial;
        return SGeometryRequested{box.size(), box.pos()};
    }
    auto box = original->position();
    return SGeometryRequested{box.size().clamp({40, 40}), box.pos()};
}
std::shared_ptr<Card> get(uint64_t id) {
    auto it = cards.find(id);
    return it == cards.end() ? nullptr : it->second;
}
bool supports(uintptr_t address) {
    auto w = resolve(address);
    return w && !w->m_group && w->m_workspace && !w->m_workspace->m_isSpecialWorkspace &&
           !Fullscreen::controller()->isFullscreen(w);
}
bool inspect(uint64_t id, ContainerSnapshot *out) {
    auto c = get(id);
    if (!c || !out || !c->valid())
        return false;
    *out = {};
    out->active = c->active;
    out->unfolded = c->unfolded;
    auto box = c->group->m_target->position();
    out->x = box.x;
    out->y = box.y;
    out->width = box.w;
    out->height = box.h;
    for (unsigned s = 0; s < 2; ++s) {
        out->count[s] = c->faces[s].size();
        out->focused[s] = addr(c->focused[s].lock());
        out->vertical[s] = c->vertical[s];
        for (unsigned i = 0; i < c->faces[s].size(); ++i) {
            out->windows[s][i] = addr(c->faces[s][i].lock());
            out->ratios[s][i] = c->ratios[s][i];
        }
    }
    return true;
}
bool select(uint64_t id, uint32_t side, bool focus) {
    auto c = get(id);
    if (!c || !c->valid() || side > 1)
        return false;
    c->active = side;
    c->group->setCurrent(c->focused[side].lock());
    c->visibility();
    if (focus)
        Desktop::focusState()->fullWindowFocus(c->focused[side].lock(), Desktop::FOCUS_REASON_KEYBIND);
    return true;
}
bool dissolve(uint64_t id) {
    auto c = get(id);
    if (!c)
        return false;
    c->dissolve();
    cards.erase(id);
    return true;
}
bool attach(uint64_t id, uintptr_t address, uint32_t side, bool vertical) {
    auto c = get(id);
    auto w = resolve(address);
    if (!c || !c->valid() || !supports(address) || side > 1 || c->faces[side].size() >= CONTAINER_MAX_PANES ||
        w->m_workspace != c->group->m_target->workspace())
        return false;
    auto oldRatios = c->ratios[side];
    auto oldVertical = c->vertical[side];
    c->faces[side].push_back(w);
    const double addedShare = 1. / c->faces[side].size();
    for (auto &weight : c->ratios[side]) weight *= 1. - addedShare;
    c->ratios[side].push_back(addedShare);
    if (oldRatios.size() == 1) c->vertical[side] = vertical;
    auto box = c->group->m_target->position();
    auto min = c->minimum();
    if (c->group->m_target->floating()) {
        box.w = std::max(box.w, min.x);
        box.h = std::max(box.h, min.y);
    }
    if (!c->fits(box)) {
        c->faces[side].pop_back();
        c->ratios[side] = oldRatios;
        c->vertical[side] = oldVertical;
        return false;
    }
    c->changing = true;
    c->group->add(w);
    auto p = PaneTarget::create(w->m_target, c);
    c->targets[address] = p;
    w->m_target = p;
    c->focused[side] = w;
    c->active = side;
    c->changing = false;
    c->decos();
    c->group->m_target->setPositionGlobal({.logicalBox = box, .visualBox = {}});
    c->refresh();
    select(id, side, true);
    return true;
}
bool release(uint64_t id, uintptr_t address) {
    auto c = get(id);
    auto w = resolve(address);
    auto s = c ? c->side(w) : std::nullopt;
    if (!s || !c->valid())
        return false;
    if (c->faces[*s].size() == 1)
        return dissolve(id);
    c->changing = true;
    c->restore(w);
    c->group->remove(w);
    const auto index = std::ranges::find(c->faces[*s], w) - c->faces[*s].begin();
    c->faces[*s].erase(c->faces[*s].begin() + index);
    c->ratios[*s].erase(c->ratios[*s].begin() + index);
    double total = 0;
    for (const auto weight : c->ratios[*s]) total += weight;
    for (auto &weight : c->ratios[*s]) weight /= total;
    if (c->focused[*s] == w)
        c->focused[*s] = c->faces[*s][0];
    c->changing = false;
    c->refresh();
    select(id, c->active, true);
    return true;
}
bool workspace(uint64_t id, uint32_t destination, bool follow) {
    auto c = get(id);
    if (!c || !c->valid())
        return false;
    auto origin = c->group->m_target->workspace();
    auto target = State::workspaceState()->query().id(destination).run();
    if (!target)
        target = State::workspaceState()->create(destination, origin->monitorID(), std::to_string(destination));
    if (!target)
        return false;
    c->group->m_target->assignToSpace(target->m_space);
    c->refresh();
    if (follow) {
        target->m_monitor->changeWorkspace(target);
        select(id, c->active, true);
    } else
        Desktop::focusState()->fullWindowFocus(origin->getFocusCandidate(), Desktop::FOCUS_REASON_KEYBIND);
    return true;
}
bool move(uint64_t id, uint32_t dir) {
    auto c = get(id);
    if (!c || !c->valid())
        return false;
    if (c->group->m_target->floating()) {
        Vector2D delta{dir == 'r' ? 40. : dir == 'l' ? -40. : 0., dir == 'd' ? 40. : dir == 'u' ? -40. : 0.};
        g_layoutManager->moveTarget(delta, c->group->m_target);
    } else
        g_layoutManager->moveInDirection(c->group->m_target, std::string(1, char(dir)));
    return true;
}
bool unfold(uint64_t id, bool value) {
    auto c = get(id);
    if (!c || !c->valid())
        return false;
    const bool previous = c->unfolded, previousAxis = c->unfoldVertical;
    c->unfolded = value;
    if (value) c->unfoldVertical = c->preferVerticalUnfold();
    auto sizedBox = [&]() {
        auto box = c->group->m_target->position();
        const auto min = c->minimum();
        if (c->group->m_target->floating()) {
            box.w = std::max(box.w, min.x);
            box.h = std::max(box.h, min.y);
        }
        return box;
    };
    auto box = sizedBox();
    if (value && !c->fits(box)) {
        c->unfoldVertical = !c->unfoldVertical;
        box = sizedBox();
    }
    if (!c->fits(box)) {
        c->unfolded = previous;
        c->unfoldVertical = previousAxis;
        return false;
    }
    c->group->m_target->setPositionGlobal({.logicalBox = box, .visualBox = {}});
    c->refresh();
    return true;
}
bool arrange(uint64_t id, uint32_t side, bool vertical, uint32_t count, const uintptr_t *windows,
             const double *ratios) {
    auto c = get(id);
    if (!c || !c->valid() || side > 1 || count != c->faces[side].size() || !windows || !ratios)
        return false;
    auto before = c->faces[side];
    auto old = c->ratios[side];
    auto axis = c->vertical[side];
    std::vector<PHLWINDOWREF> ordered;
    std::vector<double> weights;
    double sum = 0;
    for (unsigned i = 0; i < count; ++i) {
        auto w = resolve(windows[i]);
        if (std::ranges::find(before, w) == before.end() || std::ranges::find(ordered, w) != ordered.end() ||
            !std::isfinite(ratios[i]) || ratios[i] <= 0)
            return false;
        ordered.push_back(w);
        weights.push_back(ratios[i]);
        sum += ratios[i];
    }
    for (auto &weight : weights)
        weight /= sum;
    c->faces[side] = ordered;
    c->ratios[side] = weights;
    c->vertical[side] = vertical;
    auto box = c->group->m_target->position();
    auto min = c->minimum();
    if (c->group->m_target->floating()) {
        box.w = std::max(box.w, min.x);
        box.h = std::max(box.h, min.y);
    }
    if (!c->fits(box)) {
        c->faces[side] = before;
        c->ratios[side] = old;
        c->vertical[side] = axis;
        return false;
    }
    c->group->m_target->setPositionGlobal({.logicalBox = box, .visualBox = {}});
    c->refresh();
    return true;
}
bool edit(uint64_t id, uintptr_t address, ContainerEdit op) {
    auto c = get(id);
    auto w = resolve(address);
    auto side = c ? c->side(w) : std::nullopt;
    if (!side || !c->valid())
        return false;
    if (op == ContainerEdit::OtherSide) {
        auto other = *side ^ 1;
        if (c->faces[*side].size() < 2 || c->faces[other].size() >= CONTAINER_MAX_PANES)
            return false;
        auto faces = c->faces;
        auto ratios = c->ratios;
        std::erase(c->faces[*side], w);
        c->faces[other].push_back(w);
        for (unsigned s = 0; s < 2; ++s)
            c->ratios[s].assign(c->faces[s].size(), 1. / c->faces[s].size());
        if (!c->fits(c->group->m_target->position())) {
            c->faces = faces;
            c->ratios = ratios;
            return false;
        }
        if (c->focused[*side] == w)
            c->focused[*side] = c->faces[*side][0];
        c->focused[other] = w;
        c->refresh();
        return true;
    }
    std::array<uintptr_t, CONTAINER_MAX_PANES> windows{};
    std::array<double, CONTAINER_MAX_PANES> weights{};
    for (unsigned i = 0; i < c->faces[*side].size(); ++i) {
        windows[i] = addr(c->faces[*side][i].lock());
        weights[i] = op == ContainerEdit::Balance ? 1. : c->ratios[*side][i];
    }
    return arrange(id, *side, op == ContainerEdit::Balance ? c->vertical[*side] : op == ContainerEdit::Vertical,
                   c->faces[*side].size(), windows.data(), weights.data());
}
bool replace(uint64_t id, uintptr_t outgoing, uintptr_t incoming) {
    auto c = get(id);
    auto old = resolve(outgoing);
    auto next = resolve(incoming);
    auto s = c ? c->side(old) : std::nullopt;
    if (!s || !c->valid() || !supports(incoming) || next->m_workspace != old->m_workspace)
        return false;
    auto it = std::ranges::find(c->faces[*s], old);
    *it = next;
    if (!c->fits(c->group->m_target->position())) {
        *it = old;
        return false;
    }
    c->changing = true;
    c->group->add(next);
    auto p = PaneTarget::create(next->m_target, c);
    c->targets[incoming] = p;
    next->m_target = p;
    c->restore(old);
    c->group->remove(old);
    if (c->focused[*s] == old)
        c->focused[*s] = next;
    c->changing = false;
    c->decos();
    c->refresh();
    select(id, c->active, true);
    return true;
}
uint64_t pair(uintptr_t a, uintptr_t b) {
    auto w = resolve(a);
    if (!w)
        return 0;
    auto box = w->getWindowMainSurfaceBox();
    ContainerSnapshot s;
    s.count[0] = s.count[1] = 1;
    s.windows[0][0] = a;
    s.windows[1][0] = b;
    s.focused[0] = a;
    s.focused[1] = b;
    s.ratios[0][0] = s.ratios[1][0] = 1;
    s.x = box.x;
    s.y = box.y;
    s.width = box.w;
    s.height = box.h;
    return create(s);
}
void animating(uint64_t, bool) {}
const ContainerAPI API{CONTAINER_ABI_VERSION,
                       sizeof(ContainerAPI),
                       EPOCH,
                       supports,
                       pair,
                       inspect,
                       select,
                       attach,
                       release,
                       dissolve,
                       workspace,
                       move,
                       unfold,
                       edit,
                       arrange,
                       replace,
                       animating};
} // namespace
const ContainerAPI *api() { return &API; }
bool canCreate(const ContainerSnapshot &snapshot) {
    Card proposed;
    proposed.unfolded = snapshot.unfolded;
    for (unsigned s = 0; s < 2; ++s) {
        if (!snapshot.count[s] || snapshot.count[s] > CONTAINER_MAX_PANES)
            return false;
        proposed.vertical[s] = snapshot.vertical[s];
        for (unsigned i = 0; i < snapshot.count[s]; ++i) {
            auto w = resolve(snapshot.windows[s][i]);
            if (!w || !std::isfinite(snapshot.ratios[s][i]) || snapshot.ratios[s][i] <= 0 || proposed.side(w))
                return false;
            proposed.faces[s].push_back(w);
            proposed.ratios[s].push_back(snapshot.ratios[s][i]);
        }
    }
    proposed.unfoldVertical = proposed.preferVerticalUnfold();
    auto minimum = proposed.minimum();
    return proposed.fits(
        {snapshot.x, snapshot.y, std::max(snapshot.width, minimum.x), std::max(snapshot.height, minimum.y)});
}
uint64_t create(const ContainerSnapshot &snapshot) {
    if (!canCreate(snapshot))
        return 0;
    auto c = std::make_shared<Card>();
    c->initial = {snapshot.x, snapshot.y, snapshot.width, snapshot.height};
    c->active = std::min(snapshot.active, 1u);
    c->unfolded = snapshot.unfolded;
    for (unsigned s = 0; s < 2; ++s) {
        if (!snapshot.count[s] || snapshot.count[s] > CONTAINER_MAX_PANES)
            return 0;
        c->vertical[s] = snapshot.vertical[s];
        for (unsigned i = 0; i < snapshot.count[s]; ++i) {
            if (!supports(snapshot.windows[s][i]))
                return 0;
            auto w = resolve(snapshot.windows[s][i]);
            if (c->side(w))
                return 0;
            c->faces[s].push_back(w);
            c->ratios[s].push_back(snapshot.ratios[s][i] > 0 ? snapshot.ratios[s][i] : 1. / snapshot.count[s]);
        }
        double sum = std::accumulate(c->ratios[s].begin(), c->ratios[s].end(), 0.);
        for (auto &r : c->ratios[s])
            r /= sum;
        auto w = resolve(snapshot.focused[s]);
        c->focused[s] = c->side(w) == s ? w : c->faces[s][0].lock();
    }
    c->unfoldVertical = c->preferVerticalUnfold();
    auto min = c->minimum();
    c->initial.w = std::max(c->initial.w, min.x);
    c->initial.h = std::max(c->initial.h, min.y);
    if (!c->fits(c->initial))
        return 0;
    c->changing = true;
    auto front = c->faces[0][0].lock();
    if (!front->m_isFloating)
        g_layoutManager->changeFloatingMode(front->layoutTarget());
    c->group = CGroup::create({front});
    for (auto &face : c->faces)
        for (auto &ref : face) {
            auto w = ref.lock();
            if (w != front)
                c->group->add(w);
            auto p = PaneTarget::create(w->m_target, c);
            c->targets[addr(w)] = p;
            w->m_target = p;
        }
    c->group->setLocked(true);
    c->changing = false;
    c->decos();
    auto id = nextID++;
    cards.emplace(id, c);
    c->group->m_target->setPositionGlobal({.logicalBox = c->initial, .visualBox = {}});
    select(id, c->active, true);
    c->refresh();
    return id;
}
void closing(PHLWINDOW w) {
    for (auto &[id, c] : cards)
        if (auto s = c->side(w)) {
            if (c->faces[*s].size() == 1) {
                dissolve(id);
                return;
            }
            c->changing = true;
            c->restore(w);
            c->group->remove(w, Math::DIRECTION_DEFAULT, CGroup::REMOVE_FROM_GROUP_REASON_UNMAP_WINDOW);
            std::erase(c->faces[*s], w);
            c->ratios[*s].assign(c->faces[*s].size(), 1. / c->faces[*s].size());
            if (c->focused[*s] == w)
                c->focused[*s] = c->faces[*s][0];
            c->changing = false;
            c->refresh();
            return;
        }
}
void focused(PHLWINDOW w) {
    for (auto &[_, c] : cards)
        if (auto s = c->side(w); s && !c->changing) {
            c->focused[*s] = w;
            c->active = *s;
            c->visibility();
            return;
        }
}
bool toggle(uint64_t id) {
    auto c = get(id);
    if (!c || !c->valid())
        return false;
    g_layoutManager->changeFloatingMode(c->group->m_target);
    c->refresh();
    return true;
}
bool setStyle(uint64_t id, double header, double gap) {
    auto c = get(id);
    if (!c || !c->valid() || !std::isfinite(header) || header < 0 || header > 64 || !std::isfinite(gap) || gap < -1 || gap > 128)
        return false;
    if (c->header != header || c->gapOverride != gap) {
        c->header = header;
        c->gapOverride = gap;
        c->refresh();
    }
    return true;
}
void shutdown() {
    for (auto &[_, c] : cards)
        c->dissolve();
    cards.clear();
}
} // namespace Hyprflip::FloatingCards
