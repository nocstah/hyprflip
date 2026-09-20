#include "Controller.hpp"
#include <algorithm>
#include <format>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/protocols/core/DataDevice.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <limits>
#include <sstream>

namespace Hyprflip {
using Clock = std::chrono::steady_clock;
using namespace Desktop::View;
namespace {
std::string address(PHLWINDOW w) {
    return w ? std::format("\"0x{:x}\"", reinterpret_cast<uintptr_t>(w.get())) : "null";
}
std::string quote(const std::string &value) {
    std::string out = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') {
            out += '\\';
            out += c;
        } else if (c < 32)
            out += std::format("\\u{:04x}", c);
        else
            out += c;
    }
    return out + '"';
}
bool fits(PHLWINDOW w, Vector2D size) {
    auto min = w->minSize(), max = w->maxSize();
    return (!min || (size.x >= min->x && size.y >= min->y)) && (!max || (size.x <= max->x && size.y <= max->y));
}
bool sameBox(const CBox &a, const CBox &b) {
    return std::abs(a.x - b.x) < 1 && std::abs(a.y - b.y) < 1 && std::abs(a.w - b.w) < 1 && std::abs(a.h - b.h) < 1;
}
} // namespace

Controller::Controller(HANDLE handle, Settings settings)
    : m_handle(handle), m_settings(std::move(settings)), m_shader(std::make_shared<FlipShader>()) {
    // Only a watchdog for outputs that stop presenting (e.g. DPMS). Motion is
    // sampled by the output's render cycle, never by an independent timer.
    m_timer = makeShared<CEventLoopTimer>(std::nullopt, [this](SP<CEventLoopTimer>, void *) { finish(); }, nullptr);
    g_pEventLoopManager->addTimer(m_timer);
    auto &e = Event::bus()->m_events;
    m_listeners.emplace_back(e.render.preChecks.listen([this](PHLMONITOR m) { onFrame(m); }));
    m_listeners.emplace_back(e.render.stage.listen([this](eRenderStage stage) {
        // Scheduling here sets the compositor's pending-frame flag. Scheduling
        // only before rendering can be consumed by the current commit.
        if (stage == RENDER_POST && m_turn && g_pHyprRenderer->m_renderData.pMonitor == m_turn->monitor)
            if (auto monitor = m_turn->monitor.lock())
                monitor->scheduleFrame();
    }));
    m_listeners.emplace_back(e.window.close.listen([this](PHLWINDOW w) { onClose(w); }));
    m_listeners.emplace_back(e.window.destroy.listen([this](PHLWINDOWREF) { deferReconcile(); }));
    m_listeners.emplace_back(e.window.active.listen([this](PHLWINDOW w, Desktop::eFocusReason) { onFocus(w); }));
    m_listeners.emplace_back(e.window.moveToWorkspace.listen([this](PHLWINDOW, PHLWORKSPACE) {
        if (!m_mutating)
            finish();
        deferReconcile();
    }));
    m_listeners.emplace_back(e.window.fullscreen.listen([this](PHLWINDOW) {
        if (!m_mutating)
            finish();
    }));
    m_listeners.emplace_back(e.window.floating.listen([this](PHLWINDOW) {
        if (!m_mutating)
            finish();
    }));
    m_listeners.emplace_back(e.workspace.active.listen([this](PHLWORKSPACE) {
        if (!m_mutating)
            finish();
    }));
    m_listeners.emplace_back(e.monitor.preRemoved.listen([this](PHLMONITOR) { finish(); }));
    m_listeners.emplace_back(e.monitor.layoutChanged.listen([this]() { finish(); }));
    m_listeners.emplace_back(e.config.preReload.listen([this]() {
        finish();
        m_marked.reset();
    }));
    m_listeners.emplace_back(g_pSessionLockManager->m_events.lock.listen([this]() { finish(false); }));
    m_listeners.emplace_back(
        e.input.mouse.button.listen([this](const IPointer::SButtonEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.mouse.axis.listen([this](const IPointer::SAxisEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.touch.down.listen([this](const ITouch::SDownEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.tablet.tip.listen([this](const CTablet::STipEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.keyboard.key.listen([this](const IKeyboard::SKeyEvent &key, Event::SCallbackInfo &) {
            if (key.state != WL_KEYBOARD_KEY_STATE_PRESSED)
                return;
            if (m_turn && m_turn->triggerKey != key.keycode)
                finish();
            m_eventKey = key.keycode;
            m_keyLater = g_pEventLoopManager->doLaterLock([this]() { m_eventKey.reset(); });
        }));
}

Controller::~Controller() {
    m_stopping = true;
    m_listeners.clear();
    m_reconcileLater.reset();
    m_keyLater.reset();
    finish();
    if (m_timer) {
        m_timer->cancel();
        g_pEventLoopManager->removeTimer(m_timer);
        m_timer.reset();
    }
    for (auto &pair : m_pairs)
        if (auto g = pair.group.lock())
            g->setLocked(pair.previousLock);
    m_pairs.clear();
    m_marked.reset();
    m_shader.reset();
}

Controller::Pair *Controller::find(PHLWINDOW w) {
    auto it = std::ranges::find_if(m_pairs, [&](const Pair &p) { return p.windows[0] == w || p.windows[1] == w; });
    return it == m_pairs.end() ? nullptr : &*it;
}
Controller::Pair *Controller::find(uint64_t id) {
    auto it = std::ranges::find_if(m_pairs, [&](const Pair &p) { return p.id == id; });
    return it == m_pairs.end() ? nullptr : &*it;
}
bool Controller::valid(const Pair &p) const {
    auto a = p.windows[0].lock(), b = p.windows[1].lock();
    auto g = p.group.lock();
    return a && b && a->m_isMapped && b->m_isMapped && g && g->size() == 2 && a->m_group == g && b->m_group == g &&
           g->has(a) && g->has(b);
}
void Controller::reconcile() {
    if (m_mutating)
        return;
    if (m_marked && !m_marked->m_isMapped)
        m_marked.reset();
    for (auto &p : m_pairs)
        if (!valid(p)) {
            if (m_turn && m_turn->pairID == p.id)
                finish(false);
            if (auto g = p.group.lock())
                g->setLocked(p.previousLock);
        }
    std::erase_if(m_pairs, [this](const Pair &p) { return !valid(p); });
}
void Controller::deferReconcile() {
    if (m_stopping)
        return;
    m_reconcileLater = g_pEventLoopManager->doLaterLock([this]() { reconcile(); });
}
void Controller::onClose(PHLWINDOW w) {
    if (m_marked == w)
        m_marked.reset();
    if (m_turn && (m_turn->windows[0] == w || m_turn->windows[1] == w))
        finish(false);
    deferReconcile();
}
void Controller::onFocus(PHLWINDOW w) {
    if (m_mutating)
        return;
    if (m_turn) {
        auto p = find(m_turn->pairID);
        if (!p || !valid(*p))
            finish(false);
        else if (w != p->group->current())
            finish();
        else {
            const auto expected = p->windows[m_turn->source ^ unsigned(m_turn->timeline.secondSide())];
            if (w != expected)
                finish(false);
        }
    }
    deferReconcile();
}
void Controller::settleInput() {
    if (!m_mutating)
        finish();
}
void Controller::damage(const Pair &p) {
    for (const auto &ref : p.windows)
        if (auto w = ref.lock()) {
            g_pHyprRenderer->damageWindow(w, true);
            if (w->m_monitor)
                w->m_monitor->scheduleFrame();
        }
}
void Controller::select(Pair &p, unsigned index) {
    if (!valid(p))
        return;
    const bool old = m_mutating;
    m_mutating = true;
    p.group->setCurrent(p.windows[index].lock());
    for (unsigned i = 0; i < 2; ++i)
        p.windows[i]->alpha(WINDOW_ALPHA_LAYOUT)->setValueAndWarp(i == index ? 1.F : 0.F);
    m_mutating = old;
}
void Controller::detach() {
    if (!m_turn)
        return;
    for (unsigned i = 0; i < 2; ++i)
        if (auto w = m_turn->windows[i].lock()) {
            auto *ours = m_turn->transformers[i];
            std::erase_if(w->m_transformers, [ours](const auto &t) { return t.get() == ours; });
            if (m_turn->suppressedGlass[i]) {
                w->m_ruleApplicator->m_tagKeeper.applyTag("-hyprglass_disabled");
                w->m_ruleApplicator->propertiesChanged(Desktop::Rule::RULE_PROP_TAG);
            }
            g_pHyprRenderer->damageWindow(w, true);
            if (w->m_monitor)
                w->m_monitor->scheduleFrame();
        }
}
void Controller::finish(bool applyDestination) {
    if (!m_turn)
        return;
    if (applyDestination)
        if (auto p = find(m_turn->pairID))
            select(*p, m_turn->source ^ unsigned(m_turn->timeline.destination()));
    detach();
    m_turn.reset();
    m_timer->updateTimeout(std::nullopt);
}
bool Controller::inputBusy() const {
    const auto grab = g_pSeatManager->m_seatGrab;
    return g_pSessionLockManager->isSessionLocked() || (grab && (grab->m_keyboard || grab->m_pointer)) ||
           PROTO::data->dndActive() || g_pInputManager->isConstrained() || g_pInputManager->hasHeldButtons();
}
std::string Controller::unavailable(PHLWINDOW w) const {
    if (!w || !w->m_isMapped)
        return "Focus a normal application window first.";
    if (w->m_group)
        return "Unpair or remove this window from its existing group first.";
    if (w->m_pinned)
        return "Unpin the window before pairing it.";
    if (w->m_groupRules & GROUP_DENY)
        return "This window's rules prohibit grouping.";
    if (w->isX11OverrideRedirect() || w->isModal())
        return "Pair normal application windows, not transient or modal windows.";
    if (Fullscreen::controller()->isFullscreen(w))
        return "Leave fullscreen before creating a pair.";
    if (w->m_xdgSurface && w->m_xdgSurface->m_toplevel &&
        (w->m_xdgSurface->m_toplevel->m_parent || w->m_xdgSurface->m_toplevel->anyChildModal()))
        return "Close the modal dialog before pairing.";
    return {};
}
std::string Controller::animationFallback(PHLWINDOW a, PHLWINDOW b) const {
    static auto animations = CConfigValue<Config::BOOL>("animations:enabled");
    if (!m_settings.enabled->value() || !*animations || m_settings.duration->value() == 0)
        return "Animations disabled";
    for (const auto &w : {a, b}) {
        if (!w->m_monitor || !w->m_workspace || !w->m_workspace->m_visible)
            return "Workspace not visible";
        if (w->popupsCount() > 0)
            return "Popup open";
        if (w->m_xdgSurface && w->m_xdgSurface->m_toplevel && w->m_xdgSurface->m_toplevel->anyChildModal())
            return "Modal dialog open";
        const auto surface = w->resource();
        if (!surface || !surface->m_current.texture || surface->m_current.size.x < 1 || surface->m_current.size.y < 1)
            return "Surface not ready";
        if (w->positionAnimation()->isBeingAnimated() || w->sizeAnimation()->isBeingAnimated() ||
            w->m_workspace->m_renderOffset->isBeingAnimated())
            return "Geometry animation in progress";
    }
    if (a->m_monitor != b->m_monitor || a->m_workspace != b->m_workspace ||
        !sameBox(a->geometricBox(IGeometric::GEOMETRIC_CURRENT), b->geometricBox(IGeometric::GEOMETRIC_CURRENT)))
        return "Window geometry differs";
    return {};
}

Result Controller::mark() {
    auto w = Desktop::focusState()->window();
    if (auto error = unavailable(w); !error.empty())
        return {false, error};
    if (inputBusy())
        return {false, "Finish the active grab or drag before pairing."};
    m_marked = w;
    return {true, "First side marked. Focus another window and run pair."};
}
Result Controller::pair() {
    auto a = m_marked.lock(), b = Desktop::focusState()->window();
    if (!a)
        return {false, "Mark the first window before pairing."};
    if (a == b)
        return {false, "Focus a different window for the second side."};
    for (const auto &w : {a, b})
        if (auto error = unavailable(w); !error.empty())
            return {false, error};
    if (inputBusy())
        return {false, "Finish the active grab or drag before pairing."};
    if (a->m_workspace != b->m_workspace)
        return {false, "Move both windows to the same workspace before pairing."};
    if (a->m_isFloating != b->m_isFloating)
        return {false, "Both windows must be tiled, or both floating."};
    const auto minA = a->minSize().value_or(Vector2D{1, 1}), minB = b->minSize().value_or(Vector2D{1, 1});
    const auto maxA = a->maxSize().value_or(Vector2D{1e9, 1e9}), maxB = b->maxSize().value_or(Vector2D{1e9, 1e9});
    if (std::max(minA.x, minB.x) > std::min(maxA.x, maxB.x) || std::max(minA.y, minB.y) > std::min(maxA.y, maxB.y))
        return {false, "These windows have incompatible size limits."};
    if (a->m_isFloating && !fits(b, a->size(IGeometric::GEOMETRIC_GOAL)))
        return {false, "Resize the first window so the second window fits before pairing."};
    finish();
    m_mutating = true;
    auto g = CGroup::create({a});
    if (!b->canBeGroupedInto(g)) {
        g->destroy();
        m_mutating = false;
        return {false, "Hyprland's group locks or window rules prevent this pairing."};
    }
    g->add(b);
    g->setCurrent(a);
    if (!fits(a, a->size(IGeometric::GEOMETRIC_GOAL)) || !fits(b, a->size(IGeometric::GEOMETRIC_GOAL))) {
        g->destroy();
        m_mutating = false;
        return {false, "The combined tile cannot satisfy both windows' size limits."};
    }
    const bool previousLock = g->locked();
    g->setLocked(true);
    m_pairs.push_back({m_nextID++, {a, b}, g, previousLock});
    select(m_pairs.back(), 0);
    Desktop::focusState()->fullWindowFocus(a, Desktop::FOCUS_REASON_KEYBIND);
    m_mutating = false;
    m_marked.reset();
    damage(m_pairs.back());
    return {true, "Paired. Flip to reveal the other side."};
}
Result Controller::adopt(const std::string &front, const std::string &back) {
    // An installer can reattach metadata after replacing this library. Resolve
    // addresses against live windows; never dereference an IPC-supplied pointer.
    PHLWINDOW a, b;
    for (const auto &w : Desktop::windowState()->windows()) {
        if (address(w) == quote(front))
            a = w;
        if (address(w) == quote(back))
            b = w;
    }
    if (!a || !b || a == b || !a->m_isMapped || !b->m_isMapped)
        return {false, "Adopt requires two different live window addresses."};
    if (find(a) || find(b))
        return {false, "A window already belongs to a Hyprflip pair."};
    auto g = a->m_group;
    if (!g || b->m_group != g || g->size() != 2 || !g->has(a) || !g->has(b))
        return {false, "Adopt requires the two members of one existing native group."};
    m_pairs.push_back({m_nextID++, {a, b}, g, g->locked()});
    g->setLocked(true);
    return {true, "ok"};
}
Result Controller::flip() {
    auto w = Desktop::focusState()->window();
    auto p = find(w);
    if (!p || !valid(*p))
        return {false, "This window has no reverse side. Use mark, then pair."};
    if (inputBusy())
        return {false, "Finish the active grab or drag before flipping."};
    if (m_turn && m_turn->pairID == p->id) {
        m_turn->timeline.reverse();
        return {true, "ok"};
    }
    finish();
    const unsigned source = p->windows[0] == p->group->current() ? 0 : 1;
    auto a = p->windows[source].lock(), b = p->windows[1 - source].lock();
    if (!fits(b, a->size(IGeometric::GEOMETRIC_GOAL)))
        return {false, "The other side no longer fits this size. Resize the pair before flipping."};
    if (auto reason = animationFallback(a, b); !reason.empty()) {
        select(*p, 1 - source);
        damage(*p);
        m_lastFallback = "Instant switch: " + reason;
        return {true, "ok"};
    }
    auto pose = std::make_shared<Pose>();
    pose->perspective = m_settings.perspective->value();
    pose->retreat = m_settings.retreat->value();
    m_turn.emplace(Turn{p->id,
                        source,
                        Timeline(double(m_settings.duration->value())),
                        Clock::now(),
                        pose,
                        {},
                        p->windows,
                        a->geometricBox(IGeometric::GEOMETRIC_GOAL),
                        a->m_monitor,
                        a->m_workspace,
                        m_eventKey});
    for (unsigned i = 0; i < 2; ++i) {
        const auto w = p->windows[i].lock();
        // Hyprglass 1.0 draws its background outside the transformed pass.
        // Its public opt-out tag prevents a stationary rectangle behind the
        // card. Preserve an existing opt-out; restore only tags we introduced.
        if (!w->m_ruleApplicator->m_tagKeeper.isTagged("hyprglass_disabled") &&
            std::ranges::any_of(w->m_windowDecorations,
                                [](const auto &deco) { return deco->getDisplayName() == "HyprGlass"; })) {
            m_turn->suppressedGlass[i] = w->m_ruleApplicator->m_tagKeeper.applyTag("+hyprglass_disabled");
            w->m_ruleApplicator->propertiesChanged(Desktop::Rule::RULE_PROP_TAG);
        }
        w->resetMotionBlur();
        auto t = makeUnique<FlipTransformer>(p->windows[i].lock(), pose, m_shader);
        m_turn->transformers[i] = t.get();
        p->windows[i]->m_transformers.emplace_back(std::move(t));
    }
    select(*p, source);
    m_lastFallback.clear();
    damage(*p);
    m_timer->updateTimeout(std::chrono::milliseconds(250));
    return {true, "ok"};
}
Result Controller::unpair() {
    if (inputBusy())
        return {false, "Finish the active grab or drag before unpairing."};
    auto p = find(Desktop::focusState()->window());
    if (!p)
        return {false, "This window is not a Hyprflip pair."};
    finish();
    const auto id = p->id;
    auto g = p->group.lock();
    m_mutating = true;
    if (g) {
        g->setLocked(p->previousLock);
        g->destroy();
    }
    m_mutating = false;
    std::erase_if(m_pairs, [id](const Pair &pair) { return pair.id == id; });
    return {true, "Unpaired. Both windows are available separately."};
}

void Controller::onFrame(PHLMONITOR monitor) {
    if (!m_turn || monitor != m_turn->monitor)
        return;
    auto p = find(m_turn->pairID);
    if (!p || !valid(*p)) {
        finish(false);
        reconcile();
        return;
    }
    auto current = p->group->current();
    if (current != p->windows[m_turn->source ^ unsigned(m_turn->timeline.secondSide())]) {
        finish(false);
        return;
    }
    if (m_turn->pose->failed) {
        m_lastFallback = m_turn->pose->error;
        notify({false, "Flip rendering failed; switched normally. " + m_lastFallback});
        finish();
        return;
    }
    if (current->m_monitor != m_turn->monitor || current->m_workspace != m_turn->workspace ||
        !current->m_workspace->m_visible ||
        !sameBox(current->geometricBox(IGeometric::GEOMETRIC_GOAL), m_turn->geometry) || current->popupsCount() > 0 ||
        inputBusy()) {
        finish();
        return;
    }
    auto now = Clock::now();
    m_turn->timeline.advance(std::chrono::duration<double, std::milli>(now - m_turn->last).count());
    m_turn->last = now;
    m_turn->pose->angle = float(m_turn->timeline.angle()) * (m_turn->source == 0 ? 1.F : -1.F);
    const auto destination = m_turn->source ^ unsigned(m_turn->timeline.secondSide());
    if (p->group->current() != p->windows[destination])
        select(*p, destination);
    damage(*p);
    if (m_turn->timeline.finished()) {
        finish();
        return;
    }
    m_timer->updateTimeout(std::chrono::milliseconds(250));
}
Result Controller::action(const std::string &action) {
    reconcile();
    if (action == "mark")
        return mark();
    if (action == "pair")
        return pair();
    if (action.starts_with("adopt ")) {
        std::istringstream arguments(action.substr(6));
        std::string front, back, extra;
        if (!(arguments >> front >> back) || arguments >> extra)
            return {false, "Use adopt <front-address> <back-address>."};
        return adopt(front, back);
    }
    if (action == "flip")
        return flip();
    if (action == "unpair")
        return unpair();
    if (action == "cancel") {
        m_marked.reset();
        return {true, "Pairing cancelled."};
    }
    if (action == "finish") {
        finish();
        return {true, "ok"};
    }
    return {false, "Unknown action. Use mark, pair, cancel, flip, unpair, finish, or status."};
}
void Controller::notify(const Result &r) {
    if (!m_settings.notifications->value() || r.message == "ok")
        return;
    HyprlandAPI::addNotification(m_handle, "Hyprflip: " + r.message, CHyprColor(r.ok ? 0xff87c7a1 : 0xffed997b), 3500);
}
std::string Controller::status() {
    reconcile();
    std::string json = "{\"version\":\"0.1.1\",\"marked\":" + address(m_marked.lock()) +
                       ",\"animating\":" + (m_turn ? "true" : "false") +
                       ",\"progress\":" + std::format("{}", m_turn ? m_turn->timeline.progress() : 0) +
                       ",\"last_fallback\":" + quote(m_lastFallback) + ",\"pairs\":[";
    bool first = true;
    for (const auto &p : m_pairs) {
        if (!first)
            json += ',';
        first = false;
        json += std::format("{{\"id\":{},\"front\":{},\"back\":{},\"current\":{}}}", p.id, address(p.windows[0].lock()),
                            address(p.windows[1].lock()), address(p.group->current()));
    }
    return json + "]}";
}
} // namespace Hyprflip
