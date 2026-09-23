#include "Controller.hpp"
#include "FloatingCards.hpp"
#include <algorithm>
#include <charconv>
#include <dlfcn.h>
#include <format>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/algorithm/Algorithm.hpp>
#include <hyprland/src/layout/algorithm/TiledAlgorithm.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/plugins/PluginSystem.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/protocols/core/DataDevice.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <limits>
#include <cctype>
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
    m_timer = makeShared<CEventLoopTimer>(std::nullopt, [this](SP<CEventLoopTimer>, void *) {
        m_peek.reset();
        finish();
    }, nullptr);
    g_pEventLoopManager->addTimer(m_timer);
    m_frames = std::make_unique<CardFrames>([this]() { return frameViews(); }, [this](uint64_t id) {
        // A button is a click on release. Leave the input dispatch stack before
        // changing layout/focus, and resolve the card again in case it closed.
        m_frameLater = g_pEventLoopManager->doLaterLock([this, id]() {
            if (m_stopping || inputBusy()) return;
            const auto p = find(id);
            const auto s = p ? state(*p) : std::nullopt;
            if (!s) return;
            if (!s->contains(Desktop::focusState()->window()))
                Desktop::focusState()->fullWindowFocus(s->focused[s->active], Desktop::FOCUS_REASON_CLICK);
            const auto result = action(s->unfolded ? "unfold" : "flip");
            if (!result.ok) notify(result);
        });
    });
    m_drop = std::make_unique<CardDrop>([this](PHLWINDOW w) { return dropOffers(w); },
        [this](PHLWINDOWREF w, CardDropOffer offer) {
            m_dropLater = g_pEventLoopManager->doLaterLock([this, w, offer]() {
                if (m_stopping || inputBusy() || g_layoutManager->dragController()->target()) return;
                const auto result = dropAttach(w.lock(), offer);
                reconcile();
                if (!result.ok) notify(result);
            });
        });
    auto &e = Event::bus()->m_events;
    m_listeners.emplace_back(e.render.preChecks.listen([this](PHLMONITOR m) {
        m_renderingMonitor = m;
        onFrame(m);
    }));
    m_listeners.emplace_back(e.render.stage.listen([this](eRenderStage stage) {
        // Scheduling here sets the compositor's pending-frame flag. Scheduling
        // only before rendering can be consumed by the current commit. The
        // renderer clears renderData.pMonitor in endRender(), before POST.
        if (stage == RENDER_POST && m_turn && m_renderingMonitor == m_turn->monitor)
            if (auto monitor = m_turn->monitor.lock())
                monitor->scheduleFrame();
    }));
    m_listeners.emplace_back(e.window.close.listen([this](PHLWINDOW w) { onClose(w); }));
    m_listeners.emplace_back(e.window.destroy.listen([this](PHLWINDOWREF) { deferReconcile(); }));
    m_listeners.emplace_back(e.window.active.listen([this](PHLWINDOW w, Desktop::eFocusReason) { onFocus(w); }));
    m_listeners.emplace_back(e.window.moveToWorkspace.listen([this](PHLWINDOW, PHLWORKSPACE) {
        if (!m_mutating) {
            m_peek.reset();
            finish();
        }
        deferReconcile();
    }));
    m_listeners.emplace_back(e.window.fullscreen.listen([this](PHLWINDOW) {
        if (!m_mutating) m_peek.reset();
        if (!m_mutating && m_turn) {
            auto p = find(m_turn->pairID);
            // hy3 fullscreen belongs to an application, not the two-tab card.
            // Keep that application's visible face when fullscreen interrupts.
            finish(!p || !p->containerID);
        }
    }));
    m_listeners.emplace_back(e.window.floating.listen([this](PHLWINDOW) {
        if (!m_mutating) {
            m_peek.reset();
            finish();
        }
    }));
    m_listeners.emplace_back(e.workspace.active.listen([this](PHLWORKSPACE) {
        if (!m_mutating) {
            m_peek.reset();
            finish();
        }
    }));
    m_listeners.emplace_back(e.monitor.preRemoved.listen([this](PHLMONITOR) { m_peek.reset(); finish(); }));
    m_listeners.emplace_back(e.monitor.layoutChanged.listen([this]() { m_peek.reset(); finish(); }));
    m_listeners.emplace_back(e.config.preReload.listen([this]() {
        m_peek.reset();
        finish();
        m_marked.reset();
    }));
    m_listeners.emplace_back(e.config.reloaded.listen([this]() { deferReconcile(); }));
    m_listeners.emplace_back(g_pSessionLockManager->m_events.lock.listen([this]() { m_peek.reset(); finish(false); }));
    m_listeners.emplace_back(
        e.input.mouse.button.listen([this](const IPointer::SButtonEvent &event, Event::SCallbackInfo &info) {
            if (!m_frames->button(event, info)) settleInput();
        }));
    m_listeners.emplace_back(
        e.input.mouse.axis.listen([this](const IPointer::SAxisEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.touch.down.listen([this](const ITouch::SDownEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.tablet.tip.listen([this](const CTablet::STipEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.keyboard.key.listen([this](const IKeyboard::SKeyEvent &key, Event::SCallbackInfo &) {
            // Observe the physical key release, even when modifiers were
            // released first. No release binding or background helper is needed.
            if (key.state == WL_KEYBOARD_KEY_STATE_RELEASED && m_peek && m_peek->triggerKey == key.keycode) {
                endPeek();
                return;
            }
            if (key.state != WL_KEYBOARD_KEY_STATE_PRESSED)
                return;
            if (m_peek && m_peek->triggerKey != key.keycode) m_peek.reset();
            if (m_turn && m_turn->triggerKey != key.keycode)
                finish();
            m_eventKey = key.keycode;
            m_keyLater = g_pEventLoopManager->doLaterLock([this]() { m_eventKey.reset(); });
        }));
}

Controller::~Controller() {
    m_stopping = true;
    m_peek.reset();
    m_listeners.clear();
    m_reconcileLater.reset();
    m_keyLater.reset();
    m_frameLater.reset();
    m_dropLater.reset();
    m_drop.reset();
    finish();
    m_frames.reset();
    if (m_timer) {
        m_timer->cancel();
        g_pEventLoopManager->removeTimer(m_timer);
        m_timer.reset();
    }
    for (auto &pair : m_pairs) {
        discardContainer(pair);
        if (auto g = pair.group.lock())
            g->setLocked(pair.previousLock);
    }
    m_pairs.clear();
    FloatingCards::shutdown();
    m_marked.reset();
    m_shader.reset();
}

Controller::Pair *Controller::find(PHLWINDOW w) {
    auto it = std::ranges::find_if(m_pairs, [&](const Pair &p) {
        auto s = state(p);
        return s && s->contains(w);
    });
    return it == m_pairs.end() ? nullptr : &*it;
}
Controller::Pair *Controller::find(uint64_t id) {
    auto it = std::ranges::find_if(m_pairs, [&](const Pair &p) { return p.id == id; });
    return it == m_pairs.end() ? nullptr : &*it;
}
bool Controller::State::contains(PHLWINDOW w) const {
    return w && (std::ranges::find(faces[0], w) != faces[0].end() || std::ranges::find(faces[1], w) != faces[1].end());
}
std::vector<PHLWINDOWREF> Controller::State::windows() const {
    std::vector<PHLWINDOWREF> result;
    for (const auto &face : faces)
        for (const auto &w : face)
            result.emplace_back(w);
    return result;
}
const ContainerAPI *Controller::provider(uint64_t epoch) const {
    if (epoch == FloatingCards::EPOCH) return FloatingCards::api();
    // Never retain a function pointer across an event or provider unload.
    for (auto plugin : g_pPluginSystem->getAllPlugins()) {
        if (plugin->m_name != "hy3")
            continue;
        auto entry = reinterpret_cast<ContainerEntry>(dlsym(plugin->m_handle, CONTAINER_SYMBOL));
        if (!entry)
            continue;
        const auto api = entry();
        if (api && api->version == CONTAINER_ABI_VERSION && api->size == sizeof(ContainerAPI) &&
            (!epoch || epoch == api->epoch))
            return api;
    }
    return nullptr;
}
void Controller::discardContainer(const Pair &p) {
    if (p.containerID)
        if (auto api = provider(p.providerEpoch))
            api->dissolve(p.containerID);
}
std::optional<Controller::State> Controller::state(const Pair &p) const {
    State result;
    if (p.containerID) {
        const auto api = provider(p.providerEpoch);
        ContainerSnapshot snapshot;
        if (!api || !api->inspect(p.containerID, &snapshot) || snapshot.active > 1)
            return std::nullopt;
        for (unsigned s = 0; s < 2; ++s) {
            if (snapshot.count[s] < 1 || snapshot.count[s] > CONTAINER_MAX_PANES)
                return std::nullopt;
            for (unsigned i = 0; i < snapshot.count[s]; ++i) {
                PHLWINDOW found;
                for (const auto &w : Desktop::windowState()->windows())
                    if (reinterpret_cast<uintptr_t>(w.get()) == snapshot.windows[s][i]) {
                        found = w;
                        break;
                    }
                if (!found || !found->m_isMapped)
                    return std::nullopt;
                result.faces[s].push_back(found);
                result.ratios[s][i] = snapshot.ratios[s][i];
                if (reinterpret_cast<uintptr_t>(found.get()) == snapshot.focused[s])
                    result.focused[s] = found;
            }
            if (!result.focused[s])
                return std::nullopt;
            result.vertical[s] = snapshot.vertical[s];
        }
        result.active = snapshot.active;
        result.unfolded = snapshot.unfolded;
        result.geometry = {snapshot.x, snapshot.y, snapshot.width, snapshot.height};
        return result;
    }
    auto a = p.windows[0].lock(), b = p.windows[1].lock();
    auto g = p.group.lock();
    if (!a || !b || !a->m_isMapped || !b->m_isMapped || !g || g->size() != 2 || a->m_group != g || b->m_group != g ||
        !g->has(a) || !g->has(b))
        return std::nullopt;
    result.faces = {{{a}, {b}}};
    result.focused = {a, b};
    result.active = g->current() == a ? 0 : 1;
    result.geometry = a->geometricBox(IGeometric::GEOMETRIC_GOAL);
    return result;
}
bool Controller::valid(const Pair &p) const { return state(p).has_value(); }
bool Controller::inContainer() {
    reconcile();
    const auto p = find(Desktop::focusState()->window());
    return p && p->containerID;
}
void Controller::reconcile() {
    if (m_mutating)
        return;
    if (m_marked && !m_marked->m_isMapped)
        m_marked.reset();
    for (auto &p : m_pairs)
        if (!valid(p)) {
            if (m_peek && m_peek->pairID == p.id) m_peek.reset();
            if (m_turn && m_turn->pairID == p.id)
                finish(false);
            if (auto g = p.group.lock())
                g->setLocked(p.previousLock);
            discardContainer(p);
        }
    std::erase_if(m_pairs, [this](const Pair &p) { return !valid(p); });
    syncFrames();
}
void Controller::syncFrames() {
    if (!m_frames || m_mutating || m_stopping) return;
    m_mutating = true;
    std::vector<PHLWINDOWREF> native;
    const double header = m_settings.cardFrame->value() ? CardFrames::headerHeight() : 0;
    const double gap = m_settings.cardGap->value();
    for (auto &pair : m_pairs) {
        bool ready = false;
        if (!pair.containerID) {
            ready = true;
            if (header) for (const auto &window : pair.windows) native.push_back(window);
        } else if (pair.providerEpoch == FloatingCards::EPOCH) {
            ready = FloatingCards::setStyle(pair.containerID, header, gap);
        } else if (provider(pair.providerEpoch)) {
            for (auto plugin : g_pPluginSystem->getAllPlugins()) {
                if (plugin->m_name != "hy3") continue;
                using SetFrame = bool (*)(uint64_t, double);
                using SetStyle = bool (*)(uint64_t, double, double);
                const auto style = reinterpret_cast<SetStyle>(dlsym(plugin->m_handle, "hyprflip_hy3_card_style_v1"));
                const auto set = reinterpret_cast<SetFrame>(dlsym(plugin->m_handle, "hyprflip_hy3_card_frame_v1"));
                ready = style ? style(pair.containerID, header, gap) : set && set(pair.containerID, header);
                break;
            }
        }
        pair.frame = header > 0 && ready;
    }
    m_frames->nativeHeaders(native);
    m_mutating = false;
    m_frames->refresh();
}
std::vector<CardFrameView> Controller::frameViews() const {
    std::vector<CardFrameView> result;
    for (const auto &pair : m_pairs) {
        if (!pair.frame) continue;
        auto s = state(pair);
        if (!s) continue;
        CardFrameView view;
        view.id = pair.id;
        view.active = s->active;
        view.unfolded = s->unfolded;
        view.animating = m_turn && m_turn->pairID == pair.id;
        for (unsigned side = 0; side < 2; ++side) view.count[side] = s->faces[side].size();
        view.windows = s->windows();
        result.push_back(std::move(view));
    }
    return result;
}
std::vector<CardDropOffer> Controller::dropOffers(PHLWINDOW window) const {
    std::vector<CardDropOffer> offers;
    if (m_stopping || m_mutating || m_turn || !m_settings.dragToAdd->value() || !unavailable(window).empty())
        return offers;
    for (const auto &p : m_pairs)
        if (const auto s = state(p); s && s->contains(window)) return offers;
    for (const auto &p : m_pairs) {
        if (!p.containerID) continue;
        const auto s = state(p);
        if (!s) continue;
        const auto workspace = s->focused[s->active]->m_workspace;
        if (!workspace || !workspace->m_visible || workspace->m_isSpecialWorkspace ||
            Fullscreen::controller()->hasFullscreen(workspace) || window->m_workspace != workspace ||
            workspace->m_renderOffset->isBeingAnimated()) continue;
        for (unsigned side = 0; side < 2; ++side) {
            if (!s->unfolded && side != s->active) continue;
            CardDropOffer offer;
            offer.id = p.id;
            offer.side = side;
            offer.count = s->faces[side].size();
            offer.vertical = s->vertical[side];
            offer.members = s->windows();
            bool any = false;
            for (const auto &w : s->faces[side]) {
                auto box = w->geometricBox(IGeometric::GEOMETRIC_CURRENT).expand(w->getRealBorderSize());
                if (w->isHidden() || w->alpha(WINDOW_ALPHA_LAYOUT)->value() < .01F) continue;
                if (!any) offer.box = box;
                else {
                    const double x = std::min(offer.box.x, box.x), y = std::min(offer.box.y, box.y);
                    offer.box = {x, y, std::max(offer.box.x + offer.box.w, box.x + box.w) - x,
                                      std::max(offer.box.y + offer.box.h, box.y + box.h) - y};
                }
                any = true;
            }
            if (!any) continue;
            if (offer.count >= CONTAINER_MAX_PANES) offer.refusal = std::to_string(CONTAINER_MAX_PANES) + " apps already";
            offers.push_back(std::move(offer));
        }
    }
    return offers;
}
Result Controller::dropAttach(PHLWINDOW window, const CardDropOffer &offer) {
    if (!m_settings.dragToAdd->value() || inputBusy()) return {false, "Adding the app was cancelled."};
    if (!unavailable(window).empty() || find(window)) return {false, "The app changed during the drag. Try again."};
    auto p = find(offer.id);
    auto before = p ? state(*p) : std::nullopt;
    if (!p || !p->containerID || !before || before->windows() != offer.members || offer.side > 1 ||
        (!before->unfolded && before->active != offer.side) ||
        window->m_workspace != before->focused[offer.side]->m_workspace)
        return {false, "The card changed during the drag. Try again."};
    if (before->faces[offer.side].size() >= CONTAINER_MAX_PANES)
        return {false, "This side already has five apps. Remove an app before adding another."};
    if (Fullscreen::controller()->hasFullscreen(window->m_workspace))
        return {false, "Leave fullscreen before adding an app."};
    const auto marked = m_marked;
    const bool floating = window->m_isFloating;
    const auto box = window->geometricBox(IGeometric::GEOMETRIC_GOAL);
    const bool chilled = window->m_ruleApplicator->m_tagKeeper.isTagged("chillmode");
    // Keep the existing card workspace protected while the incoming app changes
    // float mode. This is the same public handoff used by the guided picker.
    if (chilled) {
        const auto command = "if chillmode and chillmode.handoff then assert(chillmode.handoff(" + address(window) + ")) end";
        HyprlandAPI::invokeHyprctlCommand("eval", command);
        window->m_ruleApplicator->m_tagKeeper.applyTag("-chillmode");
        window->m_ruleApplicator->propertiesChanged(Desktop::Rule::RULE_PROP_TAG);
    }
    if (p->providerEpoch != FloatingCards::EPOCH && window->m_isFloating)
        g_layoutManager->changeFloatingMode(window->layoutTarget());
    Desktop::focusState()->fullWindowFocus(before->focused[offer.side], Desktop::FOCUS_REASON_CLICK);
    m_marked = window;
    const auto result = attach(offer.vertical);
    m_marked = marked;
    if (result.ok) return {true, "ok"};
    // Restore the dropped app to the place where normal dragging left it.
    // Existing membership, face axis and pane proportions survive refusal.
    if (window->m_isMapped && !find(window)) {
        if (window->m_isFloating != floating) g_layoutManager->changeFloatingMode(window->layoutTarget());
        if (floating) {
            window->layoutTarget()->setPositionGlobal({.logicalBox = box, .visualBox = {}});
            window->layoutTarget()->warpPositionSize();
        }
        if (chilled) {
            window->m_ruleApplicator->m_tagKeeper.applyTag("+chillmode");
            window->m_ruleApplicator->propertiesChanged(Desktop::Rule::RULE_PROP_TAG);
        }
        // A provider may have attached then released the candidate while
        // checking the final geometry. Restore the original split precisely.
        if (auto api = provider(p->providerEpoch))
            for (unsigned side = 0; side < 2; ++side) {
                std::array<uintptr_t, CONTAINER_MAX_PANES> windows{};
                for (unsigned i = 0; i < before->faces[side].size(); ++i)
                    windows[i] = reinterpret_cast<uintptr_t>(before->faces[side][i].get());
                api->arrange(p->containerID, side, before->vertical[side], before->faces[side].size(),
                             windows.data(), before->ratios[side].data());
            }
        Desktop::focusState()->fullWindowFocus(window, Desktop::FOCUS_REASON_CLICK);
    }
    return result;
}
void Controller::deferReconcile() {
    if (m_stopping)
        return;
    m_reconcileLater = g_pEventLoopManager->doLaterLock([this]() { reconcile(); });
}
void Controller::onClose(PHLWINDOW w) {
    if (m_peek && std::ranges::find(m_peek->windows, w) != m_peek->windows.end()) m_peek.reset();
    if (m_marked == w)
        m_marked.reset();
    if (m_turn && std::ranges::find(m_turn->windows, w) != m_turn->windows.end())
        finish(false);
    const bool mutating = m_mutating;
    m_mutating = true;
    FloatingCards::closing(w);
    m_mutating = mutating;
    deferReconcile();
}
void Controller::onFocus(PHLWINDOW w) {
    if (m_mutating)
        return;
    FloatingCards::focused(w);
    if (m_peek) {
        m_peek.reset();
        finish(false); // An explicit focus change always wins over the return.
    }
    if (m_turn) {
        auto p = find(m_turn->pairID);
        auto s = p ? state(*p) : std::nullopt;
        if (!s)
            finish(false);
        else if (!s->contains(w))
            finish();
        else if (s->active != (m_turn->source ^ unsigned(m_turn->timeline.secondSide())))
            finish(false);
    }
    deferReconcile();
}
void Controller::settleInput() {
    if (!m_mutating) {
        m_peek.reset();
        finish();
    }
}
void Controller::damage(const Pair &p) {
    auto s = state(p);
    if (!s)
        return;
    for (const auto &ref : s->windows())
        if (auto w = ref.lock()) {
            g_pHyprRenderer->damageWindow(w, true);
            if (w->m_monitor)
                w->m_monitor->scheduleFrame();
        }
}
void Controller::select(Pair &p, unsigned index, bool focus) {
    auto s = state(p);
    if (!s || index > 1)
        return;
    const bool old = m_mutating;
    m_mutating = true;
    if (p.containerID) {
        if (auto api = provider(p.providerEpoch))
            api->select(p.containerID, index, focus && s->contains(Desktop::focusState()->window()));
    } else {
        p.group->setCurrent(p.windows[index].lock());
        for (unsigned i = 0; i < 2; ++i)
            p.windows[i]->alpha(WINDOW_ALPHA_LAYOUT)->setValueAndWarp(i == index ? 1.F : 0.F);
    }
    m_mutating = old;
}
void Controller::detach() {
    if (!m_turn)
        return;
    for (unsigned i = 0; i < m_turn->windows.size(); ++i)
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
    if (auto p = find(m_turn->pairID); p && p->containerID)
        if (auto api = provider(p->providerEpoch))
            api->animating(p->containerID, false);
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
    if (find(w))
        return {false, "Release this window from its Hyprflip card before marking it."};
    if (auto error = unavailable(w); !error.empty())
        return {false, error};
    if (inputBusy())
        return {false, "Finish the active grab or drag before pairing."};
    m_marked = w;
    return {true, "Window marked. Focus another window to pair, or a card face to attach."};
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
    if (find(a) || find(b))
        return {false, "A window already belongs to a Hyprflip card. Use attach to add a pane."};
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
    if (auto api = a->m_isFloating ? FloatingCards::api() : provider(); api && api->supports(reinterpret_cast<uintptr_t>(a.get())) &&
                               api->supports(reinterpret_cast<uintptr_t>(b.get()))) {
        const auto id = api->create(reinterpret_cast<uintptr_t>(a.get()), reinterpret_cast<uintptr_t>(b.get()));
        if (id) {
            m_pairs.push_back({m_nextID++, {}, {}, false, id, api->epoch});
            const auto created = state(m_pairs.back());
            bool fitsAll = created.has_value();
            if (created)
                for (const auto &w : created->windows())
                    fitsAll &= fits(w.lock(), w->size(IGeometric::GEOMETRIC_GOAL));
            if (!fitsAll) {
                discardContainer(m_pairs.back());
                m_pairs.pop_back();
                m_mutating = false;
                return {false, "The card cannot satisfy both windows' size limits."};
            }
            m_marked.reset();
        }
        m_mutating = false;
        return {id != 0, id ? "Card created. Flip sides, or mark another window and attach it to a face."
                            : "Could not create the hy3 card."};
    }
    if (!a->m_isFloating && a->m_workspace->m_space->algorithm()->tiledAlgo()->layoutName() == "hy3") {
        m_mutating = false;
        return {false,
                "The hy3 container provider is unavailable or incompatible. Rebuild both experimental libraries."};
    }
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
bool Controller::canReturnPeek() const {
    if (!m_peek || inputBusy() || !m_peek->workspace || !m_peek->workspace->m_visible || !m_peek->monitor ||
        !m_peek->monitor->m_dpmsStatus)
        return false;
    const auto p = std::ranges::find_if(m_pairs, [this](const Pair &p) { return p.id == m_peek->pairID; });
    const auto s = p == m_pairs.end() ? std::nullopt : state(*p);
    if (!s || s->unfolded || !s->contains(Desktop::focusState()->window()) ||
        !sameBox(s->geometry, m_peek->geometry) || s->windows() != m_peek->windows)
        return false;
    for (const auto &ref : s->windows()) {
        auto w = ref.lock();
        if (!w || w->m_workspace != m_peek->workspace || w->m_monitor != m_peek->monitor ||
            w->popupsCount() || Fullscreen::controller()->isFullscreen(w)) return false;
    }
    return true;
}
Result Controller::peek() {
    if (m_peek) return {true, "ok"};
    if (m_turn) return {false, "Let the turn finish before peeking."};
    auto p = find(Desktop::focusState()->window());
    auto s = p ? state(*p) : std::nullopt;
    if (!s) return {false, "Focus an app in a Hyprflip card before peeking."};
    if (s->unfolded) return {false, "Both sides are already visible. Fold the card with O before peeking."};
    Peek pending{p->id, s->active, m_eventKey, s->focused[s->active]->m_workspace,
                 s->focused[s->active]->m_monitor, s->geometry, s->windows()};
    auto result = flip();
    if (result.ok) m_peek = std::move(pending);
    return result;
}
Result Controller::endPeek() {
    if (!m_peek) return {true, "ok"};
    const auto pending = *m_peek;
    const bool returnable = canReturnPeek();
    m_peek.reset();
    if (!returnable) return {true, "ok"};
    if (m_turn && m_turn->pairID == pending.pairID) {
        if ((m_turn->source ^ unsigned(m_turn->timeline.destination())) != pending.source)
            m_turn->timeline.reverse();
        return {true, "ok"};
    }
    auto p = find(pending.pairID);
    auto s = p ? state(*p) : std::nullopt;
    return s && s->active != pending.source ? flip() : Result{true, "ok"};
}
Result Controller::flip(std::optional<Transition> preview) {
    auto w = Desktop::focusState()->window();
    auto p = find(w);
    if (!p || !valid(*p))
        return {false, "This window has no reverse side. Use mark, then pair."};
    if (inputBusy())
        return {false, "Finish the active grab or drag before flipping."};
    if (m_turn && m_turn->pairID == p->id) {
        m_turn->previewReturn = false;
        if (preview) return {false, "Wait for this turn to finish before previewing another transition."};
        m_turn->timeline.reverse();
        return {true, "ok"};
    }
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    const unsigned source = s->active;
    const auto mode = preview.value_or(transition(m_settings.transition->value()).value_or(Transition::Flip));
    if (s->unfolded) {
        if (preview) return {false, "Fold the card with O before previewing a transition."};
        for (const auto &ref : s->windows())
            if (Fullscreen::controller()->isFullscreen(ref.lock()))
                return {false, "Leave fullscreen before folding this container."};
        auto api = provider(p->providerEpoch);
        m_mutating = true;
        const bool ok = api && api->unfold(p->containerID, false) && api->select(p->containerID, 1 - source, true);
        m_mutating = false;
        return {ok, ok ? "ok" : "The layout could not fold this card."};
    }
    auto a = s->focused[source], b = s->focused[1 - source];
    if (!p->containerID && !fits(b, a->size(IGeometric::GEOMETRIC_GOAL)))
        return {false, "The other side no longer fits this size. Resize the pair before flipping."};
    std::string reason;
    if (p->containerID) {
        for (const auto &ref : s->windows()) {
            auto member = ref.lock();
            if (Fullscreen::controller()->isFullscreen(member))
                return {false, "Leave fullscreen before flipping this container."};
            if (!fits(member, member->size(IGeometric::GEOMETRIC_GOAL)))
                return {false, "A pane no longer fits its application's size limits. Resize the card before flipping."};
            if (reason.empty())
                reason = animationFallback(member, member);
        }
    } else
        reason = animationFallback(a, b);
    if (!reason.empty() || mode == Transition::Instant) {
        // A preview of Instant leaves the card where it started.
        if (preview) return {true, "ok"};
        select(*p, 1 - source);
        damage(*p);
        m_lastFallback = reason.empty() ? "" : "Instant switch: " + reason;
        return {true, "ok"};
    }
    auto pose = std::make_shared<Pose>();
    pose->mode = mode;
    pose->direction = source == 0 ? 1.F : -1.F;
    pose->leader = s->focused[source];
    pose->perspective = m_settings.perspective->value();
    pose->retreat = m_settings.retreat->value();
    if (p->containerID)
        pose->containerBox = s->geometry;
    m_turn.emplace(Turn{p->id,
                        source,
                        Timeline(double(m_settings.duration->value())),
                        Clock::now(),
                        pose,
                        {},
                        s->windows(),
                        s->geometry,
                        a->m_monitor,
                        a->m_workspace,
                        m_eventKey,
                        {},
                        {}});
    m_turn->transformers.resize(m_turn->windows.size());
    m_turn->suppressedGlass.resize(m_turn->windows.size());
    m_turn->previewReturn = preview.has_value();
    m_captureMs = 0;
    for (unsigned i = 0; i < m_turn->windows.size(); ++i) {
        const auto w = m_turn->windows[i].lock();
        m_turn->windowGeometry.push_back(w->geometricBox(IGeometric::GEOMETRIC_GOAL));
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
    }
    select(*p, source);
    if (p->containerID)
        if (auto api = provider(p->providerEpoch))
            api->animating(p->containerID, true);
    if (snapshots(mode)) {
        const auto started = Clock::now();
        auto monitor = a->m_monitor.lock();
        // Four native-sized RGBA buffers is the peak capture budget: two
        // faces, one temporary pane and one reusable transition output.
        if (!monitor || !g_pHyprRenderer->glBackend() ||
            monitor->m_pixelSize.x * monitor->m_pixelSize.y * 16 > 256 * 1024 * 1024) {
            pose->error = "Snapshot transition exceeds the 256 MiB buffer budget";
        } else {
            m_mutating = true;
            for (unsigned side = 0; side < 2; ++side) {
                select(*p, source ^ side, false);
                pose->faces[side] = m_shader->captureFace(s->faces[source ^ side], monitor, pose->error);
                if (!pose->faces[side]) break;
            }
            select(*p, source);
            m_mutating = false;
        }
        m_captureMs = std::chrono::duration<double, std::milli>(Clock::now() - started).count();
        if (!pose->faces[0] || !pose->faces[1]) {
            m_lastFallback = "Instant switch: " + pose->error;
            finish(!preview);
            return {true, "ok"};
        }
        m_turn->last = Clock::now(); // capture time is not part of motion progress
    }
    for (unsigned i = 0; i < m_turn->windows.size(); ++i) {
        auto w = m_turn->windows[i].lock();
        auto t = makeUnique<FlipTransformer>(w, pose, m_shader);
        m_turn->transformers[i] = t.get();
        w->m_transformers.emplace_back(std::move(t));
    }
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
    discardContainer(*p);
    if (g) {
        g->setLocked(p->previousLock);
        g->destroy();
    }
    m_mutating = false;
    std::erase_if(m_pairs, [id](const Pair &pair) { return pair.id == id; });
    return {true, "Unpaired. All windows are available in the layout."};
}

Result Controller::attach(bool vertical) {
    if (inputBusy())
        return {false, "Finish the active grab or drag before attaching."};
    auto w = m_marked.lock();
    if (auto error = unavailable(w); !error.empty())
        return {false, error};
    if (find(w))
        return {false, "The marked window already belongs to a card."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus a card created on the experimental hy3 layout, then attach the marked window."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    if (s->faces[s->active].size() >= CONTAINER_MAX_PANES)
        return {false, "This side already has five apps. Remove an app before adding another."};
    for (const auto &member : s->windows())
        if (Fullscreen::controller()->isFullscreen(member.lock()))
            return {false, "Leave fullscreen before attaching to this container."};
    if ((w->m_isFloating && p->providerEpoch != FloatingCards::EPOCH) || w->m_workspace != s->focused[s->active]->m_workspace)
        return {false, "Tile the marked window on the same workspace before attaching it."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    bool ok = api && api->attach(p->containerID, reinterpret_cast<uintptr_t>(w.get()), s->active, vertical);
    if (ok) {
        const auto attached = state(*p);
        bool fitsAll = attached.has_value();
        if (attached)
            for (const auto &ref : attached->windows())
                fitsAll &= fits(ref.lock(), ref->size(IGeometric::GEOMETRIC_GOAL));
        if (!fitsAll) {
            api->release(p->containerID, reinterpret_cast<uintptr_t>(w.get()));
            Desktop::focusState()->fullWindowFocus(s->focused[s->active], Desktop::FOCUS_REASON_KEYBIND);
            m_mutating = false;
            return {false, "This split is too small for the applications. Resize the card or try the other axis."};
        }
    }
    m_mutating = false;
    if (ok)
        m_marked.reset();
    return {ok, ok ? "Pane attached to this face." : "The layout could not attach this window."};
}
Result Controller::replacePane(const std::string &arguments) {
    std::istringstream input(arguments);
    std::string outgoing, incoming, extra;
    if (!(input >> outgoing >> incoming) || input >> extra)
        return {false, "Use replace <current-app-address> <replacement-address>."};
    if (inputBusy())
        return {false, "Finish the active grab or drag before replacing an app."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus an app in a Hyprflip container first."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Open the card menu again."};
    PHLWINDOW old, next;
    for (const auto &w : s->faces[s->active])
        if (address(w) == quote(outgoing)) old = w;
    for (const auto &w : Desktop::windowState()->windows())
        if (address(w) == quote(incoming)) next = w;
    if (!old)
        return {false, "The app to replace is no longer on this side."};
    if (auto error = unavailable(next); !error.empty())
        return {false, error};
    if (find(next) || next->m_group)
        return {false, "The replacement already belongs to a card or group."};
    if ((next->m_isFloating && p->providerEpoch != FloatingCards::EPOCH) || next->m_workspace != old->m_workspace)
        return {false, "Tile the replacement on the card workspace first."};
    for (const auto &w : s->windows())
        if (Fullscreen::controller()->isFullscreen(w.lock()))
            return {false, "Leave fullscreen before replacing an app."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    const bool ok = api && api->replace(p->containerID, reinterpret_cast<uintptr_t>(old.get()),
                                        reinterpret_cast<uintptr_t>(next.get()));
    m_mutating = false;
    if (ok && m_marked == next) m_marked.reset();
    reconcile();
    return {ok, ok ? "ok" : "The apps do not fit in those positions. The original card was kept."};
}
Result Controller::release() {
    if (inputBusy())
        return {false, "Finish the active grab or drag before releasing."};
    auto w = Desktop::focusState()->window();
    auto p = find(w);
    if (!p)
        return {false, "This window is not in a Hyprflip card."};
    if (!p->containerID)
        return unpair();
    finish();
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    const bool ok = api && api->release(p->containerID, reinterpret_cast<uintptr_t>(w.get()));
    m_mutating = false;
    reconcile();
    return {ok, ok ? "Window released into the layout." : "The layout could not release this window."};
}
Result Controller::workspace(uint32_t destination, bool follow) {
    if (!destination || destination > INT32_MAX)
        return {false, "Use workspace <number> with a positive workspace number."};
    if (inputBusy())
        return {false, "Finish the active grab or drag before moving the card."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus an experimental hy3 card to move it as a unit."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    for (const auto& window : Desktop::windowState()->windows())
        if (window->m_isMapped && window->m_isFloating && window->m_workspace &&
            window->m_workspace->m_id == destination &&
            window->m_ruleApplicator->m_tagKeeper.isTagged("chillmode"))
            return {false, "Turn off Chill mode on workspace " + std::to_string(destination) +
                           " before moving the card there. The card stayed in place."};
    for (const auto &w : s->windows())
        if (Fullscreen::controller()->isFullscreen(w.lock()))
            return {false, "Leave fullscreen before moving this container."};
    auto api = provider(p->providerEpoch);
    m_movingWorkspace = destination;
    m_mutating = true;
    const bool ok = api && api->workspace(p->containerID, destination, follow);
    m_mutating = false;
    m_movingWorkspace.reset();
    reconcile();
    return {ok, ok ? "ok" : "The destination workspace must use hy3."};
}
bool Controller::protectsWorkspace(uint32_t workspace) const {
    if (!workspace || m_stopping) return false;
    if (m_movingWorkspace == workspace) return true;
    for (const auto& [token, reservation] : m_reservations)
        if (reservation.workspace == workspace && reservation.until > Clock::now()) return true;
    for (const auto& pair : m_pairs) {
        if (!pair.containerID) continue;
        const auto card = state(pair);
        if (card && card->focused[0] && card->focused[0]->m_workspace &&
            card->focused[0]->m_workspace->m_id == workspace) return true;
    }
    return false;
}
Result Controller::move(char direction) {
    if (inputBusy())
        return {false, "Finish the active grab or drag before moving the card."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus a Hyprflip container to move it as a unit."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    for (const auto &w : s->windows())
        if (Fullscreen::controller()->isFullscreen(w.lock()))
            return {false, "Leave fullscreen before moving this container."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    const bool ok = api && api->move(p->containerID, direction);
    m_mutating = false;
    reconcile();
    return {ok, ok ? "ok" : "The layout could not move this card."};
}
Result Controller::unfold() {
    if (inputBusy())
        return {false, "Finish the active grab or drag before unfolding the card."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus a Hyprflip container to show both faces together."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    for (const auto &w : s->windows())
        if (Fullscreen::controller()->isFullscreen(w.lock()))
            return {false, "Leave fullscreen before unfolding this container."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    const bool ok = api && api->unfold(p->containerID, !s->unfolded);
    m_mutating = false;
    reconcile();
    return {ok, ok ? "ok" : "Both faces need more room. Enlarge the card before unfolding."};
}

Result Controller::editContainer(ContainerEdit operation, const std::string &target) {
    if (inputBusy())
        return {false, "Finish the active grab or drag before changing the layout."};
    auto w = Desktop::focusState()->window();
    auto p = find(w);
    if (!p || !p->containerID)
        return {false, "Focus an app in a Hyprflip container first."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Open the card menu again."};
    w = s->focused[s->active];
    if (!target.empty()) {
        w = nullptr;
        for (const auto &member : s->faces[s->active])
            if (address(member) == quote(target)) w = member;
        if (!w)
            return {false, "That app is no longer on this side. Open the card menu again."};
    }
    for (const auto &member : s->windows())
        if (Fullscreen::controller()->isFullscreen(member.lock()))
            return {false, "Leave fullscreen before changing the card layout."};
    if (s->faces[s->active].size() < 2)
        return {false, "This side needs at least two apps. Add an app from the card menu first."};
    if (operation == ContainerEdit::OtherSide && s->faces[1 - s->active].size() >= CONTAINER_MAX_PANES)
        return {false, "The other side already has five apps. Remove an app there first."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    const bool ok = api && api->edit(p->containerID, reinterpret_cast<uintptr_t>(w.get()), operation);
    m_mutating = false;
    reconcile();
    return {ok, ok ? "ok" : "The apps need more room for that layout. Enlarge the card and try again."};
}

Result Controller::arrangeFace(const std::string &arguments) {
    std::istringstream input(arguments);
    std::string axis, token;
    std::array<uintptr_t, CONTAINER_MAX_PANES> windows{};
    std::array<double, CONTAINER_MAX_PANES> ratios{};
    uint32_t count = 0;
    if (!(input >> axis) || (axis != "horizontal" && axis != "vertical"))
        return {false, "Use arrange <horizontal|vertical> <address:ratio> ..."};
    while (input >> token) {
        const auto colon = token.find(':');
        if (count == CONTAINER_MAX_PANES || !token.starts_with("0x") || colon == std::string::npos || colon <= 2)
            return {false, "Invalid pane order or proportions."};
        const auto [addressEnd, addressError] = std::from_chars(token.data() + 2, token.data() + colon, windows[count], 16);
        const auto [ratioEnd, ratioError] = std::from_chars(token.data() + colon + 1, token.data() + token.size(), ratios[count]);
        if (addressError != std::errc{} || addressEnd != token.data() + colon || ratioError != std::errc{} ||
            ratioEnd != token.data() + token.size() || !std::isfinite(ratios[count]) || ratios[count] <= 0)
            return {false, "Invalid pane order or proportions."};
        ++count;
    }
    if (!count || inputBusy())
        return {false, "Finish the active grab or drag before restoring the face."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus an app in a Hyprflip container first."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Open the card menu again."};
    for (const auto &member : s->windows())
        if (Fullscreen::controller()->isFullscreen(member.lock()))
            return {false, "Leave fullscreen before restoring the card layout."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    const bool ok = api && api->arrange(p->containerID, s->active, axis == "vertical", count, windows.data(), ratios.data());
    m_mutating = false;
    reconcile();
    return {ok, ok ? "ok" : "The face changed or its apps need more room. Enlarge the card and try again."};
}

void Controller::onFrame(PHLMONITOR monitor) {
    if (m_peek && !canReturnPeek()) m_peek.reset();
    if (!m_turn || monitor != m_turn->monitor)
        return;
    auto p = find(m_turn->pairID);
    auto s = p ? state(*p) : std::nullopt;
    if (!s) {
        finish(false);
        reconcile();
        return;
    }
    auto current = s->focused[s->active];
    if (s->active != (m_turn->source ^ unsigned(m_turn->timeline.secondSide()))) {
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
        !current->m_workspace->m_visible || !sameBox(s->geometry, m_turn->geometry) || current->popupsCount() > 0 ||
        inputBusy()) {
        finish();
        return;
    }
    for (unsigned i = 0; i < m_turn->windows.size(); ++i) {
        auto w = m_turn->windows[i].lock();
        if (!w || !w->m_isMapped || w->m_monitor != m_turn->monitor || w->m_workspace != m_turn->workspace ||
            !sameBox(w->geometricBox(IGeometric::GEOMETRIC_GOAL), m_turn->windowGeometry[i]) || w->popupsCount()) {
            finish();
            return;
        }
    }
    auto now = Clock::now();
    m_turn->timeline.advance(std::chrono::duration<double, std::milli>(now - m_turn->last).count());
    m_turn->last = now;
    m_turn->pose->angle = float(m_turn->timeline.angle()) * (m_turn->source == 0 ? 1.F : -1.F);
    m_turn->pose->progress = m_turn->timeline.progress();
    m_turn->pose->dirty = true;
    const auto destination = m_turn->source ^ unsigned(m_turn->timeline.secondSide());
    if (s->active != destination)
        select(*p, destination);
    m_turn->pose->leader = s->focused[destination];
    if (p->containerID)
        if (auto api = provider(p->providerEpoch))
            api->animating(p->containerID, true);
    damage(*p);
    if (m_turn->timeline.finished()) {
        if (m_turn->previewReturn) {
            m_turn->previewReturn = false;
            m_turn->timeline.reverse();
        } else {
            finish();
            return;
        }
    }
    m_timer->updateTimeout(std::chrono::milliseconds(250));
}
Result Controller::floating() {
    if (inputBusy()) return {false, "Finish the active drag before changing the card mode."};
    auto p = find(Desktop::focusState()->window());
    if (!p) return {false, "Choose a card first."};
    finish();
    auto current = state(*p);
    if (!current) return {false, "This card changed. Open Cards again."};
    for (const auto &w : current->windows())
        if (Fullscreen::controller()->isFullscreen(w.lock())) return {false, "Leave fullscreen before changing the card mode."};
    m_mutating = true;
    if (p->providerEpoch == FloatingCards::EPOCH) {
        const bool ok = FloatingCards::toggle(p->containerID);
        m_mutating = false;
        return {ok, ok ? "ok" : "The card could not change mode."};
    }
    ContainerSnapshot snapshot;
    snapshot.active = current->active; snapshot.unfolded = current->unfolded;
    snapshot.x = current->geometry.x; snapshot.y = current->geometry.y;
    snapshot.width = current->geometry.w; snapshot.height = current->geometry.h;
    for (unsigned side = 0; side < 2; ++side) {
        snapshot.count[side] = current->faces[side].size();
        snapshot.focused[side] = reinterpret_cast<uintptr_t>(current->focused[side].get());
        snapshot.vertical[side] = current->vertical[side];
        for (unsigned i = 0; i < current->faces[side].size(); ++i) {
            snapshot.windows[side][i] = reinterpret_cast<uintptr_t>(current->faces[side][i].get());
            snapshot.ratios[side][i] = current->ratios[side][i] > 0 ? current->ratios[side][i] : 1. / current->faces[side].size();
        }
    }
    if (!FloatingCards::canCreate(snapshot)) {
        m_mutating = false;
        return {false, "These apps have incompatible size limits. The current card was kept."};
    }
    if (p->containerID) discardContainer(*p);
    else if (auto g = p->group.lock()) {g->setLocked(p->previousLock);g->destroy();}
    const auto id = FloatingCards::create(snapshot);
    if (id) {
        p->containerID = id; p->providerEpoch = FloatingCards::EPOCH;
        p->group.reset(); p->windows = {};
    }
    m_mutating = false;
    reconcile();
    return {id != 0, id ? "Card floats as one unit. Drag or resize any app." : "These apps cannot fit a floating card. They remain open."};
}
Result Controller::action(const std::string &action) {
    const auto result = dispatch(action);
    reconcile();
    return result;
}
Result Controller::dispatch(const std::string &action) {
    reconcile();
    if (action == "floating") return floating();
    std::erase_if(m_reservations, [](const auto& entry) { return entry.second.until <= Clock::now(); });
    if (action.starts_with("reserve ")) {
        std::istringstream args(action.substr(8));
        uint32_t workspace = 0, seconds = 60;
        std::string token, extra;
        if (!(args >> workspace >> token) || !workspace || workspace > INT32_MAX || token.size() > 64 ||
            !std::ranges::all_of(token, [](unsigned char c) { return std::isalnum(c) || c == '-' || c == '_'; }))
            return {false, "Use reserve <workspace> <token> [seconds]."};
        if (args >> extra) {
            const auto [end, error] = std::from_chars(extra.data(), extra.data() + extra.size(), seconds);
            if (error != std::errc{} || end != extra.data() + extra.size() || !seconds || seconds > 120)
                return {false, "A workspace reservation lasts between 1 and 120 seconds."};
            if (args >> extra) return {false, "Use reserve <workspace> <token> [seconds]."};
        }
        m_reservations[token] = {workspace, Clock::now() + std::chrono::seconds(seconds)};
        return {true, "ok"};
    }
    if (action.starts_with("unreserve ")) {
        m_reservations.erase(action.substr(10));
        return {true, "ok"};
    }
    if (action == "peek") return peek();
    if (action == "peek end") return endPeek();
    // Any explicit card operation replaces the temporary peek interaction.
    m_peek.reset();
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
    if (action.starts_with("preview ")) {
        auto mode = transition(action.substr(8));
        if (!mode) return {false, "Choose flip, vertical, slide, fade, dissolve, portal or instant."};
        return flip(mode);
    }
    if (action == "unpair")
        return unpair();
    if (action == "attach" || action == "attach horizontal")
        return attach(false);
    if (action == "attach vertical")
        return attach(true);
    if (action == "release")
        return release();
    if (action.starts_with("replace "))
        return replacePane(action.substr(8));
    if (action == "unfold")
        return unfold();
    if (action == "other_side")
        return editContainer(ContainerEdit::OtherSide);
    if (action.starts_with("other_side "))
        return editContainer(ContainerEdit::OtherSide, action.substr(11));
    if (action == "layout horizontal")
        return editContainer(ContainerEdit::Horizontal);
    if (action == "layout vertical")
        return editContainer(ContainerEdit::Vertical);
    if (action == "layout balance")
        return editContainer(ContainerEdit::Balance);
    if (action.starts_with("arrange "))
        return arrangeFace(action.substr(8));
    if (action.starts_with("move ")) {
        const auto direction = action.substr(5);
        if (direction == "left" || direction == "right" || direction == "up" || direction == "down" ||
            direction == "l" || direction == "r" || direction == "u" || direction == "d")
            return move(direction.front());
        return {false, "Use move <left|right|up|down>."};
    }
    if (action.starts_with("workspace ")) {
        auto value = std::string_view(action).substr(10);
        const bool follow = !value.ends_with(" silent");
        if (!follow)
            value.remove_suffix(7);
        uint32_t destination = 0;
        auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), destination);
        if (error != std::errc{} || end != value.data() + value.size())
            return {false, "Use workspace <number> with a positive workspace number."};
        return workspace(destination, follow);
    }
    if (action == "cancel") {
        m_marked.reset();
        return {true, "Pairing cancelled."};
    }
    if (action == "finish") {
        finish();
        return {true, "ok"};
    }
    return {false, "Unknown action. Use mark, pair, attach [horizontal|vertical], replace <old> <new>, release, unfold, "
                   "layout <horizontal|vertical|balance>, other_side, "
                   "workspace <number> [silent], move <left|right|up|down>, cancel, "
                   "flip, peek [end], unpair, finish, or status."};
}
void Controller::notify(const Result &r) {
    if (!m_settings.notifications->value() || r.message == "ok")
        return;
    HyprlandAPI::addNotification(m_handle, "Hyprflip: " + r.message, CHyprColor(r.ok ? 0xff87c7a1 : 0xffed997b), 3500);
}
std::string Controller::status() {
    reconcile();
    std::string json = "{\"version\":\"" HYPRFLIP_VERSION "\",\"marked\":" + address(m_marked.lock()) +
                       ",\"transition\":" + quote(std::string(name(transition(m_settings.transition->value()).value_or(Transition::Flip)))) +
                       ",\"transition_modes\":[\"flip\",\"vertical\",\"slide\",\"fade\",\"dissolve\",\"portal\",\"instant\"]" +
                       ",\"capture_ms\":" + std::format("{}", m_captureMs) +
                       ",\"card_frame\":" + (m_settings.cardFrame->value() ? "true" : "false") +
                       ",\"card_gap\":" + std::to_string(m_settings.cardGap->value()) +
                       ",\"drag_to_add\":" + (m_settings.dragToAdd->value() ? "true" : "false") +
                       ",\"drop_targets\":" + (m_drop ? m_drop->status() : "[]") +
                       ",\"animating\":" + (m_turn ? "true" : "false") +
                       ",\"peek_available\":true,\"peeking\":" + (m_peek ? "true" : "false") +
                       ",\"progress\":" + std::format("{}", m_turn ? m_turn->timeline.progress() : 0) +
                       ",\"last_fallback\":" + quote(m_lastFallback) + ",\"pairs\":[";
    bool first = true;
    for (const auto &p : m_pairs) {
        if (p.containerID)
            continue;
        if (!first)
            json += ',';
        first = false;
        json += std::format("{{\"id\":{},\"front\":{},\"back\":{},\"current\":{}}}", p.id, address(p.windows[0].lock()),
                            address(p.windows[1].lock()), address(p.group->current()));
    }
    json += "],\"containers\":[";
    first = true;
    for (const auto &p : m_pairs) {
        if (!p.containerID)
            continue;
        auto s = state(p);
        if (!s)
            continue;
        if (!first)
            json += ',';
        first = false;
        json +=
            std::format("{{\"id\":{},\"active\":{},\"unfolded\":{},\"current\":{},\"box\":[{},{},{},{}],\"faces\":[",
                        p.id, s->active, s->unfolded ? "true" : "false", address(s->focused[s->active]), s->geometry.x,
                        s->geometry.y, s->geometry.w, s->geometry.h);
        for (unsigned side = 0; side < 2; ++side) {
            if (side)
                json += ',';
            json += '[';
            bool firstWindow = true;
            for (const auto &w : s->faces[side]) {
                if (!firstWindow)
                    json += ',';
                firstWindow = false;
                json += address(w);
            }
            json += ']';
        }
        json += "],\"native_group\":" + std::string(p.providerEpoch == FloatingCards::EPOCH ? "true" : "false") + ",\"floating\":" + std::string(s->focused[s->active]->m_isFloating ? "true" : "false") + ",\"layouts\":[";
        for (unsigned side = 0; side < 2; ++side) {
            if (side) json += ',';
            json += "{\"axis\":" + quote(s->vertical[side] ? "vertical" : "horizontal") +
                    ",\"focused\":" + address(s->focused[side]) + ",\"ratios\":[";
            for (unsigned i = 0; i < s->faces[side].size(); ++i) {
                if (i) json += ',';
                json += std::format("{}", s->ratios[side][i]);
            }
            json += "]}";
        }
        json += "]}";
    }
    const bool available = provider();
    return json + "],\"card_frames\":" + (m_frames ? m_frames->status() : "[]") +
           ",\"floating_cards\":true,\"workspace_protection\":true,\"container_provider\":" + (available ? "true" : "false") +
           ",\"layout_controls\":" + (available ? "true" : "false") +
           ",\"repair_cards\":" + (available ? "true" : "false") +
           ",\"pane_replacement\":" + (available ? "true" : "false") +
           ",\"container_max_panes\":" + std::to_string(available ? CONTAINER_MAX_PANES : 0) + "}";
}
} // namespace Hyprflip
