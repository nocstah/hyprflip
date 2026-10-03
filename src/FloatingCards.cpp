#include "FloatingCards.hpp"
#include "SplitLayout.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <hyprland/src/config/values/types/CssGapValue.hpp>
#include <hyprland/src/config/shared/workspace/WorkspaceRuleManager.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/ViewHitTester.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/layout/space/Space.hpp>
#include <hyprland/src/layout/target/Target.hpp>
#include <hyprland/src/layout/target/WindowGroupTarget.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
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
HANDLE plugin = nullptr;
CFunctionHook *focusHook = nullptr, *hitHook = nullptr;

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
    double divider = FULLSCREEN_DIVIDER;

    double gap(bool vertical) const {
        // Fullscreen panes meet at a thin divider that CardFrames paints.
        if (bare()) return divider;
        if (gapOverride >= 0) return gapOverride;
        static auto value = CConfigValue<Config::IComplexConfigValue>("general:gaps_in");
        const auto workspace = group ? group->m_target->workspace() : faces[0].empty() || !faces[0][0] ? nullptr : faces[0][0]->m_workspace;
        auto rule = Config::workspaceRuleMgr()->getWorkspaceRuleFor(workspace);
        auto g = rule.and_then([](auto r) { return r.m_gapsIn; })
                     .value_or(*static_cast<Config::CCssGapData *>(value.ptr()));
        return std::max<int64_t>(0, vertical ? g.m_top + g.m_bottom : g.m_left + g.m_right);
    }

    // Hyprland keeps one fullscreen member: the group's current window. The
    // whole visible card then fills that member's fullscreen area.
    PHLWINDOW fullscreen() const {
        for (const auto &[_, p] : targets)
            if (auto w = p->window(); w && Fullscreen::controller()->isFullscreen(w))
                return w;
        return nullptr;
    }
    // Set while this card hands fullscreen to another member. Hyprland clears
    // the old member before setting the new one; keep the fullscreen layout
    // across that gap so apps never receive their tiled size mid-transfer.
    std::optional<CBox> held;
    bool bare() const { return held || fullscreen(); }
    // Borders, rounding and shadows would double up at the divider. Remove
    // them at layout priority, so explicit window rules still win.
    // A card fullscreen (Controller's fullscreen action) fills the screen
    // without telling apps, so browsers keep their toolbars. Hyprland keeps
    // app and compositor fullscreen in sync unless syncFullscreen is off.
    bool flat = false, quiet = false;
    static void style(PHLWINDOW w, bool flat, bool quiet) {
        auto &rules = *w->m_ruleApplicator;
        constexpr auto LAYOUT = Desktop::Types::PRIORITY_LAYOUT;
        if (flat) {
            rules.borderSize().set(0, LAYOUT);
            rules.rounding().set(0, LAYOUT);
            rules.noShadow().set(true, LAYOUT);
        } else {
            rules.borderSize().unset(LAYOUT);
            rules.rounding().unset(LAYOUT);
            rules.noShadow().unset(LAYOUT);
        }
        if (quiet)
            rules.syncFullscreen().set(false, LAYOUT);
        else
            rules.syncFullscreen().unset(LAYOUT);
        w->updateDecorationValues();
    }
    void restyle(bool nextFlat, bool nextQuiet) {
        if (flat == nextFlat && quiet == nextQuiet)
            return;
        flat = nextFlat;
        quiet = nextQuiet;
        for (const auto &[_, p] : targets)
            if (auto w = p->window())
                style(w, flat, quiet);
    }
    void current(PHLWINDOW w) {
        const auto previous = held;
        held = fullscreenBox();
        group->setCurrent(w);
        held = previous;
    }
    // Joining or leaving a fullscreen group moves Hyprland's fullscreen onto
    // the wrong window before the pane target exists. Leave fullscreen with
    // the layout held, change membership, then return on the focused pane.
    template <class F> bool keepFullscreen(F change) {
        auto window = fullscreen();
        if (!window)
            return change();
        const auto modes = Fullscreen::controller()->getFullscreenModes(window);
        const auto previous = held;
        held = fullscreenBox();
        Fullscreen::controller()->setFullscreenMode(window, Fullscreen::FSMODE_NONE, Fullscreen::FSMODE_NONE);
        const bool ok = change();
        auto next = alive && group ? focused[active].lock() : nullptr;
        if (next && group->current() != next)
            current(next);
        if (next)
            Fullscreen::controller()->setFullscreenMode(next, modes.internal, modes.client);
        held = previous;
        return ok;
    }
    std::optional<CBox> fullscreenBox() const {
        if (held)
            return held;
        auto w = fullscreen();
        if (!w || !w->m_workspace || !w->m_workspace->m_monitor || !w->m_workspace->m_space)
            return {};
        if (Fullscreen::controller()->getFullscreenModes(w).internal == Fullscreen::FSMODE_MAXIMIZED)
            return w->m_workspace->m_space->workArea(w->m_isFloating);
        return w->m_workspace->m_monitor->logicalBox();
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
            if (faces[side].size() >= 3)
                (vertical[side] ? columns : rows) = true;
        return rows && !columns;
    }
    struct FaceLimits {
        Vector2D minimum{1, 1};
        Vector2D maximum{1e9, 1e9};
    };
    std::array<FaceLimits, 2> faceLimits() const {
        std::array<FaceLimits, 2> limits;
        for (unsigned s = 0; s < 2; ++s) {
            for (unsigned i = 0; i < faces[s].size(); ++i) {
                if (!faces[s][i])
                    continue;
                const double border = 2. * faces[s][i]->getRealBorderSize();
                auto min = faces[s][i]->minSize().value_or(Vector2D{40, 40}) + Vector2D{border, border};
                auto max = faces[s][i]->maxSize().value_or(Vector2D{1e9, 1e9}) + Vector2D{border, border};
                if (vertical[s]) {
                    min.y /= ratios[s][i];
                    max.y /= ratios[s][i];
                } else {
                    min.x /= ratios[s][i];
                    max.x /= ratios[s][i];
                }
                limits[s].minimum.x = std::max(limits[s].minimum.x, min.x);
                limits[s].minimum.y = std::max(limits[s].minimum.y, min.y);
                limits[s].maximum.x = std::min(limits[s].maximum.x, max.x);
                limits[s].maximum.y = std::min(limits[s].maximum.y, max.y);
            }
            const double gaps = gap(vertical[s]) * (faces[s].size() - 1);
            (vertical[s] ? limits[s].minimum.y : limits[s].minimum.x) += gaps;
            (vertical[s] ? limits[s].maximum.y : limits[s].maximum.x) += gaps;
        }
        return limits;
    }
    CBox faceBox(CBox box, unsigned s) const {
        // Card frames are hidden while fullscreen, so the header space is too.
        const double top = bare() ? 0 : header;
        box.y += top;
        box.h = std::max(1., box.h - top);
        if (unfolded) {
            const auto limits = faceLimits();
            const double gutter = gap(unfoldVertical);
            const double available = std::max(1., (unfoldVertical ? box.h : box.w) - gutter);
            const auto range = [&](unsigned side) {
                return ExtentRange{unfoldVertical ? limits[side].minimum.y : limits[side].minimum.x,
                                   unfoldVertical ? limits[side].maximum.y : limits[side].maximum.x};
            };
            const double first = balancedSplit(available, range(0), range(1)).value_or(available / 2);
            const double extent = s == 0 ? first : available - first;
            if (unfoldVertical) {
                box.h = extent;
                if (s)
                    box.y += first + gutter;
            } else {
                box.w = extent;
                if (s)
                    box.x += first + gutter;
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
        const auto limits = faceLimits();
        const double top = bare() ? 0 : header;
        const auto first = limits[0].minimum, second = limits[1].minimum;
        return {unfolded && !unfoldVertical ? std::ceil(first.x) + std::ceil(second.x) + gap(false)
                                            : std::max(first.x, second.x),
                (unfolded && unfoldVertical ? std::ceil(first.y) + std::ceil(second.y) + gap(true)
                                            : std::max(first.y, second.y)) +
                    top};
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
        for (unsigned s = 0; s < 2; ++s)
            for (auto &ref : faces[s])
                if (auto w = ref.lock()) {
                    const bool shown = unfolded || s == active;
                    w->setInputBlocked(INPUT_BLOCK_GROUP_INACTIVE, !shown);
                    w->alpha(WINDOW_ALPHA_LAYOUT)->setValueAndWarp(shown ? 1.F : 0.F);
                }
    }
    // Focus raises only the focused window's own target, which is a pane
    // inside the card. Raise every app of a floating card together (hidden
    // face first, focused app last), so a turn never passes behind another
    // window that sits between its faces.
    void raise() {
        if (!alive || !group || !group->m_target->floating())
            return;
        std::vector<PHLWINDOW> order;
        for (unsigned s : {active ^ 1u, active})
            for (auto &ref : faces[s])
                if (auto w = ref.lock(); w && w != focused[active].lock())
                    order.push_back(w);
        if (auto w = focused[active].lock())
            order.push_back(w);
        for (const auto &w : order)
            Desktop::windowState()->raise(w);
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
        if (flat || quiet)
            style(w, false, false);
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
    // While fullscreen, every member lays out inside the fullscreen area,
    // whichever box a caller passes (the layout's tile, or Hyprland's group
    // fullscreen transfer, which reuses another member's pane).
    const auto full = c->fullscreenBox();
    CBox outer = full ? *full : box.visualBox.empty() ? box.logicalBox : box.visualBox;
    if (floating() && !full && !c->adjusting) {
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
    auto pane = c->paneBox(outer, *side, index);
    const bool fullscreen = Fullscreen::controller()->isFullscreen(w);
    // Tiled window targets inset their visual slot by the window's border.
    // Floating targets accept a content rectangle directly. Use the same slot
    // interpretation here so the empty gap is identical in both modes.
    if (floating() && !fullscreen)
        pane.expand(-w->getRealBorderSize());
    // Hyprland ignores fullscreen geometry it did not queue itself. This pane
    // is the fullscreen member's place in the card, so let it through.
    if (fullscreen)
        Fullscreen::controller()->m_windowPosSettingQueued = true;
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
    c->current(c->focused[side].lock());
    c->visibility();
    c->raise();
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
    const bool fullscreen = c->bare();
    auto box = fullscreen ? *c->fullscreenBox() : c->group->m_target->position();
    // A fullscreen card keeps its fullscreen area; a floating one grows to fit.
    const bool floating = c->group->m_target->floating() && !fullscreen;
    if (floating) {
        auto min = c->minimum();
        box.w = std::max(box.w, min.x);
        box.h = std::max(box.h, min.y);
    }
    // A tiled incoming window still occupies its own layout slot. Grouping
    // removes that slot and can enlarge the card, so Controller::attach checks
    // the resulting pane sizes and rolls back if they do not fit.
    if ((floating || fullscreen) && !c->fits(box)) {
        c->faces[side].pop_back();
        c->ratios[side] = oldRatios;
        c->vertical[side] = oldVertical;
        return false;
    }
    return c->keepFullscreen([&] {
        c->changing = true;
        c->group->add(w);
        auto p = PaneTarget::create(w->m_target, c);
        c->targets[address] = p;
        w->m_target = p;
        if (c->flat || c->quiet)
            Card::style(w, c->flat, c->quiet);
        c->focused[side] = w;
        c->active = side;
        c->changing = false;
        c->decos();
        if (floating)
            c->group->m_target->setPositionGlobal({.logicalBox = box, .visualBox = {}});
        c->refresh();
        select(id, side, true);
        return true;
    });
}
bool release(uint64_t id, uintptr_t address) {
    auto c = get(id);
    auto w = resolve(address);
    auto s = c ? c->side(w) : std::nullopt;
    if (!s || !c->valid())
        return false;
    if (c->faces[*s].size() == 1)
        return dissolve(id);
    return c->keepFullscreen([&] {
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
    });
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
        if (c->group->m_target->floating() && !c->bare()) {
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
    if (c->group->m_target->floating() && !c->bare()) {
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
    if (!c->fits(c->bare() ? *c->fullscreenBox() : c->group->m_target->position())) {
        *it = old;
        return false;
    }
    return c->keepFullscreen([&] {
        c->changing = true;
        c->group->add(next);
        auto p = PaneTarget::create(next->m_target, c);
        c->targets[incoming] = p;
        next->m_target = p;
        if (c->flat || c->quiet)
            Card::style(next, c->flat, c->quiet);
        c->restore(old);
        c->group->remove(old);
        if (c->focused[*s] == old)
            c->focused[*s] = next;
        c->changing = false;
        c->decos();
        c->refresh();
        select(id, c->active, true);
        return true;
    });
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
    return create(s, w->m_isFloating);
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
uint64_t create(const ContainerSnapshot &snapshot, bool floating) {
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
    if (front->m_isFloating != floating)
        g_layoutManager->changeFloatingMode(front->layoutTarget());
    c->group = CGroup::create({front});
    for (auto &face : c->faces)
        for (auto &ref : face) {
            auto w = ref.lock();
            if (w != front) {
                if (!w->canBeGroupedInto(c->group)) {
                    c->dissolve();
                    return 0;
                }
                c->group->add(w);
            }
            auto p = PaneTarget::create(w->m_target, c);
            c->targets[addr(w)] = p;
            w->m_target = p;
        }
    c->group->setLocked(true);
    c->changing = false;
    c->decos();
    auto id = nextID++;
    cards.emplace(id, c);
    if (floating)
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
            // Pointer focus bypasses fullWindowFocus. Keep fullscreen on the
            // focused pane so the fullscreen toggle acts on the whole card.
            if (auto current = c->fullscreen(); current && current != w && c->valid())
                c->current(w);
            c->visibility();
            c->raise();
            return;
        }
}
namespace {
// Hyprland treats focusing a non-fullscreen window under fullscreen as leaving
// or stealing fullscreen (misc:on_focus_under_fullscreen). Inside one card,
// hand fullscreen to the pane first: the group transfer keeps the card whole.
void share(PHLWINDOW w) {
    if (!w || !w->m_workspace)
        return;
    for (auto &[_, c] : cards)
        if (c->side(w)) {
            auto current = c->fullscreen();
            if (c->valid() && !c->changing && current && current != w)
                c->current(w);
            return;
        }
}
using FullWindowFocus = void (*)(Desktop::CFocusState *, PHLWINDOW, Desktop::eFocusReason, SP<CWLSurfaceResource>, bool);
void focusWithin(Desktop::CFocusState *self, PHLWINDOW w, Desktop::eFocusReason reason, SP<CWLSurfaceResource> surface,
                 bool cycle) {
    share(w);
    reinterpret_cast<FullWindowFocus>(focusHook->m_original)(self, w, reason, surface, cycle);
}
// Under fullscreen, Hyprland sends the pointer to the fullscreen window
// wherever it is. In a fullscreen card, send it to the pane under the pointer.
using WindowAt = PHLWINDOW (*)(const Desktop::CViewHitTester *, const Vector2D &, uint16_t, PHLWINDOW);
PHLWINDOW windowWithin(const Desktop::CViewHitTester *self, const Vector2D &pos, uint16_t properties, PHLWINDOW ignore) {
    auto found = reinterpret_cast<WindowAt>(hitHook->m_original)(self, pos, properties, ignore);
    if (!found || found->m_isFloating || !Fullscreen::controller()->isFullscreen(found))
        return found;
    for (auto &[_, c] : cards)
        if (c->side(found)) {
            if (!c->valid())
                return found;
            for (unsigned s = 0; s < 2; ++s)
                for (auto &ref : c->faces[s])
                    if (auto w = ref.lock(); w && w != ignore && (c->unfolded || s == c->active) && w->acceptsInput() &&
                                             w->getWindowBoxUnified(properties).containsPoint(pos))
                        return w;
            return found;
        }
    return found;
}
CFunctionHook *hook(void *handle, const std::string &name, const std::string &owner, void *replacement) {
    for (const auto &match : HyprlandAPI::findFunctionsByName(handle, name))
        if (match.demangled.find(owner + "::" + name) != std::string::npos) {
            auto result = HyprlandAPI::createFunctionHook(handle, match.address, replacement);
            if (result && !result->hook()) {
                HyprlandAPI::removeFunctionHook(handle, result);
                result = nullptr;
            }
            return result;
        }
    return nullptr;
}
} // namespace
void install(void *handle) {
    plugin = handle;
    focusHook = hook(handle, "fullWindowFocus", "CFocusState", reinterpret_cast<void *>(&focusWithin));
    hitHook = hook(handle, "windowAt", "CViewHitTester", reinterpret_cast<void *>(&windowWithin));
}
bool focusShared() { return focusHook && hitHook; }
void fullscreened(PHLWINDOW w) {
    // A pane fullscreened directly may not be the group's current window.
    // Make it current so layouts see the card as fullscreen.
    for (auto &[_, c] : cards)
        if (auto s = c->side(w)) {
            if (c->valid())
                c->restyle(c->bare(), c->quiet && c->bare());
            if (c->valid() && !c->changing && Fullscreen::controller()->isFullscreen(w) && c->group->current() != w) {
                c->focused[*s] = w;
                c->active = *s;
                c->current(w);
                c->visibility();
            }
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
bool setStyle(uint64_t id, double header, double gap, double divider) {
    auto c = get(id);
    if (!c || !c->valid() || !std::isfinite(header) || header < 0 || header > 64 || !std::isfinite(gap) || gap < -1 ||
        gap > 128 || !std::isfinite(divider) || divider < 0 || divider > 16)
        return false;
    if (c->header != header || c->gapOverride != gap || c->divider != divider) {
        c->header = header;
        c->gapOverride = gap;
        c->divider = divider;
        c->refresh();
    }
    return true;
}
bool place(uint64_t id, CBox box) {
    auto c = get(id);
    if (!c || !c->valid() || !c->group->m_target->floating() || c->bare() || box.w < 1 || box.h < 1)
        return false;
    const auto min = c->minimum();
    box.w = std::max(box.w, min.x);
    box.h = std::max(box.h, min.y);
    c->group->m_target->setPositionGlobal({.logicalBox = box, .visualBox = {}});
    c->refresh();
    return true;
}
bool fullscreen(uint64_t id) {
    auto c = get(id);
    if (!c || !c->valid())
        return false;
    if (auto window = c->fullscreen()) {
        Fullscreen::controller()->setFullscreenMode(window, Fullscreen::FSMODE_NONE, Fullscreen::FSMODE_NONE);
        return true;
    }
    auto w = c->focused[c->active].lock();
    if (!w)
        return false;
    // Quiet first: with sync on, Hyprland would tell the app it is fullscreen.
    c->restyle(c->flat, true);
    if (c->group->current() != w)
        c->current(w);
    Fullscreen::controller()->setFullscreenMode(w, Fullscreen::FSMODE_FULLSCREEN, Fullscreen::FSMODE_NONE);
    if (!c->fullscreen())
        c->restyle(c->flat, false);
    return c->fullscreen() != nullptr;
}
void shutdown() {
    for (auto *h : {focusHook, hitHook})
        if (h)
            HyprlandAPI::removeFunctionHook(plugin, h);
    focusHook = hitHook = nullptr;
    for (auto &[_, c] : cards)
        c->dissolve();
    cards.clear();
}
} // namespace Hyprflip::FloatingCards
