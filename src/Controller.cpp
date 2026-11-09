#include "AccentColor.hpp"
#include "Controller.hpp"
#include "FloatingCards.hpp"
#include "Reveal.hpp"
#include <algorithm>
#include <charconv>
#include <dlfcn.h>
#include <filesystem>
#include <unistd.h>
#include <hyprutils/os/Process.hpp>
#include <format>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/algorithm/Algorithm.hpp>
#include <hyprland/src/layout/algorithm/TiledAlgorithm.hpp>
#include <hyprland/src/layout/algorithm/tiled/dwindle/DwindleAlgorithm.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/plugins/PluginSystem.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/protocols/core/DataDevice.hpp>
#include <hyprland/src/protocols/core/Subcompositor.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <limits>
#include <cctype>
#include <linux/input-event-codes.h>
#include <sstream>

namespace Hyprflip {
using Clock = std::chrono::steady_clock;
using namespace Desktop::View;
namespace {
std::string address(PHLWINDOW w) {
    return w ? std::format("\"0x{:x}\"", reinterpret_cast<uintptr_t>(w.get())) : "null";
}
// A workspace the way the card actions take it: a number, name:<name>,
// special or special:<name>. Hyprland's relative forms (+1, e-1, previous)
// depend on the focus, so they are refused.
bool workspaceName(std::string_view text) {
    const auto name = [](std::string_view value) {
        return !value.empty() && value.size() <= 64 &&
               std::ranges::all_of(value, [](unsigned char c) { return std::isalnum(c) || c == '-' || c == '_' || c == '.'; });
    };
    if (text == "special")
        return true;
    if (text.starts_with("special:"))
        return name(text.substr(8));
    if (text.starts_with("name:"))
        return name(text.substr(5));
    uint32_t number = 0;
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), number);
    return error == std::errc{} && end == text.data() + text.size() && number && number <= INT32_MAX;
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
// Says which limit an app's place breaks, naming the app and both sizes.
std::string sizeProblem(PHLWINDOW w, Vector2D size) {
    const std::string name = FloatingCards::appName(w);
    const auto px = [](double v) { return std::to_string(static_cast<long>(std::round(v))); };
    const auto min = w->minSize().value_or(Vector2D{1, 1}), max = w->maxSize().value_or(Vector2D{1e9, 1e9});
    if (size.x < min.x || size.y < min.y)
        return name + " needs at least " + px(min.x) + " x " + px(min.y) + " px, but its place in the card is " +
               px(size.x) + " x " + px(size.y) + ". Make the first window bigger, or open the card on a "
               "workspace with fewer windows.";
    return name + " can be at most " + px(max.x) + " x " + px(max.y) + " px, but its place in the card is " +
           px(size.x) + " x " + px(size.y) + ".";
}
bool sameBox(const CBox &a, const CBox &b) {
    return std::abs(a.x - b.x) < 1 && std::abs(a.y - b.y) < 1 && std::abs(a.w - b.w) < 1 && std::abs(a.h - b.h) < 1;
}
// The window the seat's pointer focus belongs to, read as CardFrames reads it.
// A subsurface or popup stands for its window; layers and locks have none.
PHLWINDOW pointerWindow() {
    auto surface = g_pSeatManager->m_state.pointerFocus.lock();
    for (int depth = 0; depth < 32 && surface && surface->m_role && surface->m_role->role() == SURFACE_ROLE_SUBSURFACE;
         ++depth) {
        const auto subsurface = static_cast<CSubsurfaceRole *>(surface->m_role.get())->m_subsurface.lock();
        surface = subsurface ? subsurface->m_parent.lock() : nullptr;
    }
    const auto owner = CWLSurface::fromResource(surface);
    const auto view = owner ? owner->view() : nullptr;
    if (const auto popup = CPopup::fromView(view)) {
        const auto head = popup->popupHead();
        for (const auto &w : Desktop::windowState()->windows())
            if (head && w->m_popupHead == head)
                return w;
        return nullptr;
    }
    return CWindow::fromView(view);
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
    m_switcher = std::make_unique<FaceSwitcher>(m_shader);
    m_switchTimer = makeShared<CEventLoopTimer>(std::nullopt, [this](SP<CEventLoopTimer>, void *) {
        // Still held after the delay: show the faces. Released already: a tap.
        if (!m_switch || m_switch->open) return;
        if (m_switch->scripted || switchHeld()) openSwitcher();
        else commitSwitch();
    }, nullptr);
    g_pEventLoopManager->addTimer(m_switchTimer);
    FloatingCards::install(handle);
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
    m_listeners.emplace_back(e.render.pre.listen([](PHLMONITOR) { Reveal::frame(); }));
    m_listeners.emplace_back(e.monitor.removed.listen([](PHLMONITOR monitor) { Reveal::monitorGone(monitor); }));
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
    m_listeners.emplace_back(e.window.fullscreen.listen([this](PHLWINDOW w) {
        FloatingCards::fullscreened(w);
        if (!m_mutating) m_peek.reset();
        if (!m_mutating && m_turn) {
            auto p = find(m_turn->pairID);
            // In a two-window group, fullscreen belongs to an application, not
            // the pair. Keep that application's visible face when fullscreen interrupts.
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
            cancelSwitch();
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
            if (m_eatSwitchRelease && event.state == WL_POINTER_BUTTON_STATE_RELEASED) {
                m_eatSwitchRelease = false;
                info.cancelled = true;
                return;
            }
            if (m_switch && m_switch->open && event.state == WL_POINTER_BUTTON_STATE_PRESSED) {
                // A click on a face picks it; anywhere else puts the switcher away.
                info.cancelled = true;
                m_eatSwitchRelease = true;
                const auto face = m_switcher->hit(g_pInputManager->getMouseCoordsInternal());
                if (face && event.button == BTN_LEFT) {
                    m_switch->selected = *face;
                    commitSwitch();
                } else
                    cancelSwitch();
                return;
            }
            if (!m_frames->button(event, info)) settleInput();
        }));
    m_listeners.emplace_back(
        e.input.mouse.axis.listen([this](const IPointer::SAxisEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.touch.down.listen([this](const ITouch::SDownEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.tablet.tip.listen([this](const CTablet::STipEvent &, Event::SCallbackInfo &) { settleInput(); }));
    m_listeners.emplace_back(
        e.input.keyboard.key.listen([this](const IKeyboard::SKeyEvent &key, Event::SCallbackInfo &info) {
            if (m_switch && switcherKey(key)) {
                info.cancelled = true;
                return;
            }
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
    m_switch.reset();
    m_switchLater.reset();
    if (m_switchTimer) {
        m_switchTimer->cancel();
        g_pEventLoopManager->removeTimer(m_switchTimer);
        m_switchTimer.reset();
    }
    m_switcher.reset();
    m_listeners.clear();
    Reveal::shutdown();
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
    if (!w)
        return false;
    for (unsigned s = 0; s < count; ++s)
        if (std::ranges::find(faces[s], w) != faces[s].end())
            return true;
    return false;
}
std::vector<PHLWINDOWREF> Controller::State::windows() const {
    std::vector<PHLWINDOWREF> result;
    for (const auto &face : faces)
        for (const auto &w : face)
            result.emplace_back(w);
    return result;
}
const ContainerAPI *Controller::provider(uint64_t epoch) const {
    // Cards are built by the core itself, on dwindle or floating.
    // Epoch 0 is a plain two-window pair (a Hyprland group): no card engine.
    return epoch == FloatingCards::EPOCH ? FloatingCards::api() : nullptr;
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
        if (!api || !api->inspect(p.containerID, &snapshot) || snapshot.faces < 2 || snapshot.faces > CONTAINER_MAX_FACES ||
            snapshot.active >= snapshot.faces)
            return std::nullopt;
        result.count = snapshot.faces;
        for (unsigned s = 0; s < snapshot.faces; ++s) {
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
size_t Controller::faceSize() {
    reconcile();
    const auto p = find(Desktop::focusState()->window());
    const auto s = p && p->containerID ? state(*p) : std::nullopt;
    return s ? s->faces[s->active].size() : 0;
}
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
    const double divider = m_settings.fullscreenDivider->value();
    for (auto &pair : m_pairs) {
        bool ready = false;
        if (!pair.containerID) {
            ready = true;
            if (header) for (const auto &window : pair.windows) native.push_back(window);
        } else if (pair.providerEpoch == FloatingCards::EPOCH) {
            ready = FloatingCards::setStyle(pair.containerID, header, gap, divider);
        }
        pair.frame = header > 0 && ready;
    }
    m_frames->nativeHeaders(native);
    m_mutating = false;
    m_frames->refresh();
}
std::vector<CardFrameView> Controller::frameViews() const {
    std::vector<CardFrameView> result;
    static auto activeBorder = CConfigValue<Config::IComplexConfigValue>("general:col.active_border");
    const auto border = static_cast<Config::CGradientValueData *>(activeBorder.ptr());
    const auto parsed = parseAccent(m_settings.accentColor->value());
    const auto accent =
        parsed ? CHyprColor(*parsed) : border->m_colors.empty() ? CHyprColor(0xffffffff) : border->m_colors.front();
    std::optional<CHyprColor> ring;
    if (m_settings.accentRing->value())
        ring = accent;
    for (const auto &pair : m_pairs) {
        if (!pair.frame && !ring && !pair.containerID) continue;
        auto s = state(pair);
        if (!s) continue;
        CardFrameView view;
        view.id = pair.id;
        view.frame = pair.frame;
        view.ring = ring;
        if (pair.containerID && m_settings.fullscreenDivider->value() > 0) {
            const auto chosen = parseAccent(m_settings.dividerColor->value());
            view.divider = chosen ? CHyprColor(*chosen) : accent.modifyA(1.F);
            view.dividerWidth = m_settings.fullscreenDivider->value();
        }
        view.active = s->active;
        view.unfolded = s->unfolded;
        view.animating = m_turn && m_turn->pairID == pair.id;
        view.faces = s->count;
        for (unsigned side = 0; side < s->count; ++side) view.count[side] = s->faces[side].size();
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
        // A native card fullscreen on this workspace still accepts apps.
        const bool fullscreenCard = workspace && p.providerEpoch == FloatingCards::EPOCH &&
            s->contains(Fullscreen::controller()->getFullscreenWindow(workspace));
        if (!workspace || !workspace->m_visible || workspace->m_isSpecialWorkspace ||
            (Fullscreen::controller()->hasFullscreen(workspace) && !fullscreenCard) || window->m_workspace != workspace ||
            workspace->m_renderOffset->isBeingAnimated()) continue;
        for (unsigned side = 0; side < s->count; ++side) {
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
    if (!p || !p->containerID || !before || before->windows() != offer.members || offer.side >= before->count ||
        (!before->unfolded && before->active != offer.side) ||
        window->m_workspace != before->focused[offer.side]->m_workspace)
        return {false, "The card changed during the drag. Try again."};
    if (before->faces[offer.side].size() >= CONTAINER_MAX_PANES)
        return {false, "This side already has five apps. Remove an app before adding another."};
    if (Fullscreen::controller()->hasFullscreen(window->m_workspace) &&
        (p->providerEpoch != FloatingCards::EPOCH || !before->contains(Fullscreen::controller()->getFullscreenWindow(window->m_workspace))))
        return {false, "Leave fullscreen before adding an app."};
    const auto marked = m_marked;
    const bool floating = window->m_isFloating;
    const auto box = window->geometricBox(IGeometric::GEOMETRIC_GOAL);
    // A chilled card floats; a chilled app joins it as it is. Otherwise Chill
    // hands the app back to tiling before it joins a tiled card.
    const bool cardChilled = std::ranges::any_of(before->windows(), [](const auto &member) {
        return member->m_ruleApplicator->m_tagKeeper.isTagged("chillmode");
    });
    const bool chilled = !cardChilled && window->m_ruleApplicator->m_tagKeeper.isTagged("chillmode");
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
            for (unsigned side = 0; side < before->count; ++side) {
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
    if (m_switch) {
        // Focus leaving the card puts its switcher away.
        const auto p = find(m_switch->pairID);
        const auto s = p ? state(*p) : std::nullopt;
        if (!s || !s->contains(w)) cancelSwitch();
    }
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
        else if (s->active != m_turn->face(m_turn->timeline.secondSide()))
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
    if (!s || index >= s->count)
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
        if (auto p = find(m_turn->pairID)) {
            const auto destination = m_turn->face(m_turn->timeline.destination());
            remember(*p, m_turn->source, destination);
            select(*p, destination);
        }
    if (auto p = find(m_turn->pairID); p && p->containerID)
        if (auto api = provider(p->providerEpoch))
            api->animating(p->containerID, false);
    detach();
    // A turn shows every face at its focused opacity, undimmed. A card turned
    // by its id while the focus is elsewhere gets no focus change to give its
    // apps their resting look back.
    const auto focused = Desktop::focusState()->window();
    if (std::ranges::none_of(m_turn->windows, [&](const auto &ref) { return ref.lock() == focused; }))
        for (const auto &ref : m_turn->windows)
            if (auto w = ref.lock())
                w->updateDecorationValues();
    m_turn.reset();
    m_timer->updateTimeout(std::nullopt);
}
bool Controller::inputBusy() const { return interactiveBusy(input({})); }
InputState Controller::input(const std::vector<PHLWINDOW> &targets) const {
    const auto grab = g_pSeatManager->m_seatGrab;
    const bool held = g_pInputManager->hasHeldButtons();
    const auto over = held && !targets.empty() ? pointerWindow() : nullptr;
    // A border resize or a mod+drag can begin where no surface takes the
    // pointer focus. Its target is the window (or card) the press began on.
    const auto drag = g_layoutManager->dragController()->target();
    const auto dragged = drag ? drag->window() : nullptr;
    return {.locked = g_pSessionLockManager->isSessionLocked(),
            .grab = grab && (grab->m_keyboard || grab->m_pointer),
            .dnd = PROTO::data->dndActive(),
            .constrained = g_pInputManager->isConstrained(),
            .held = held,
            .heldOverTarget = (over && std::ranges::find(targets, over) != targets.end()) ||
                              (dragged && std::ranges::find(targets, dragged) != targets.end())};
}
bool Controller::scriptBusy(const std::vector<PHLWINDOW> &targets) const { return scriptedBusy(input(targets)); }
std::vector<PHLWINDOW> Controller::members(const Pair &p) const {
    std::vector<PHLWINDOW> result;
    if (const auto s = state(p))
        for (const auto &face : s->faces)
            result.insert(result.end(), face.begin(), face.end());
    return result;
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

Result Controller::mark(const std::string &target) {
    // An address marks without focusing, so a fullscreen card can take an app
    // that focusing would otherwise pull the card out of fullscreen for.
    auto w = Desktop::focusState()->window();
    if (!target.empty()) {
        w = nullptr;
        for (const auto &candidate : Desktop::windowState()->windows())
            if (address(candidate) == quote(target)) w = candidate;
    }
    if (find(w))
        return {false, "Release this window from its Hyprflip card before marking it."};
    if (auto error = unavailable(w); !error.empty())
        return {false, error};
    if (inputBusy())
        return {false, "Finish the active grab or drag before pairing."};
    m_marked = w;
    return {true, "Window marked. Focus another window to pair, or a card face to attach."};
}
Result Controller::pair(bool multiApp) {
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
    const auto &algorithm = a->m_workspace->m_space->algorithm()->tiledAlgo();
    // Built-in layouts use their concrete type. A plain two-window pair on a
    // tiled layout is a Hyprland group, below; cards are the core's own.
    const bool dwindle = dynamic_cast<Layout::Tiled::CDwindleAlgorithm *>(algorithm.get());
    const auto api = a->m_isFloating || (multiApp && dwindle) ? FloatingCards::api() : nullptr;
    if (api && api->supports(reinterpret_cast<uintptr_t>(a.get())) &&
                               api->supports(reinterpret_cast<uintptr_t>(b.get()))) {
        const auto id = api->create(reinterpret_cast<uintptr_t>(a.get()), reinterpret_cast<uintptr_t>(b.get()));
        if (id) {
            m_pairs.push_back({m_nextID++, {}, {}, false, id, api->epoch});
            const auto created = state(m_pairs.back());
            std::string tooSmall = created ? "" : "The card could not be laid out.";
            if (created)
                for (const auto &w : created->windows())
                    if (tooSmall.empty() && !fits(w.lock(), w->size(IGeometric::GEOMETRIC_GOAL)))
                        tooSmall = sizeProblem(w.lock(), w->size(IGeometric::GEOMETRIC_GOAL));
            if (!tooSmall.empty()) {
                discardContainer(m_pairs.back());
                m_pairs.pop_back();
                m_mutating = false;
                return {false, tooSmall};
            }
            m_marked.reset();
        }
        m_mutating = false;
        return {id != 0, id ? "Card created. Flip sides, or mark another window and attach it to a face."
                            : "Could not create the card."};
    }
    if (multiApp) {
        m_mutating = false;
        return {false, "Cards open on a normal dwindle workspace, or float the first window."};
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
        const auto size = a->size(IGeometric::GEOMETRIC_GOAL);
        g->destroy();
        m_mutating = false;
        return {false, sizeProblem(fits(a, size) ? b : a, size)};
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
            w->popupsCount() || (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(w)))
            return false;
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
void Controller::remember(Pair &pair, unsigned shown, unsigned next) {
    if (shown != next) pair.lastFace = shown;
}
bool Controller::switchHeld() const {
    return m_switch && (m_switch->key || g_pInputManager->getModsFromAllKBs() != 0);
}
Result Controller::flipKey() {
    auto p = find(Desktop::focusState()->window());
    if (m_switch) {
        if (p && p->id == m_switch->pairID) {
            // Each further press steps along the faces.
            if (m_eventKey) m_switch->key = m_eventKey;
            m_switch->selected = (m_switch->selected + 1) % m_switch->count;
            if (!m_switch->open) openSwitcher();
            if (m_switch) m_switcher->select(m_switch->selected);
            return {true, "ok"};
        }
        cancelSwitch();
    }
    if (!m_eventKey || !p || !valid(*p) || !m_settings.switcher->value() || (m_turn && m_turn->pairID == p->id))
        return flip();
    const auto s = state(*p);
    if (!s || s->count <= 2 || s->unfolded)
        return flip();
    const unsigned last =
        p->lastFace && *p->lastFace < s->count && *p->lastFace != s->active ? *p->lastFace : s->next();
    m_switch = Switch{p->id, m_eventKey, last, s->count};
    m_switchTimer->updateTimeout(std::chrono::milliseconds(std::max<int64_t>(1, m_settings.switcherDelay->value())));
    return {true, "ok"};
}
bool Controller::switcherKey(const IKeyboard::SKeyEvent &key) {
    if (key.state != WL_KEYBOARD_KEY_STATE_PRESSED) {
        if (m_switch->key == key.keycode) m_switch->key.reset();
        // Modifiers change after this event; decide once it has gone through.
        if (!m_switch->scripted)
            m_switchLater = g_pEventLoopManager->doLaterLock([this]() {
                if (m_switch && !m_switch->scripted && !switchHeld()) commitSwitch();
            });
        return false;
    }
    if (m_switch->key == key.keycode) return false;
    const auto step = [this](int by) {
        m_switch->selected = (m_switch->selected + m_switch->count + by) % m_switch->count;
        if (!m_switch->open) openSwitcher();
        if (m_switch) m_switcher->select(m_switch->selected);
    };
    switch (key.keycode) {
        case KEY_ESC: cancelSwitch(); return true;
        case KEY_ENTER:
        case KEY_KPENTER:
        case KEY_SPACE: commitSwitch(); return true;
        case KEY_LEFT:
        case KEY_UP: step(-1); return true;
        case KEY_RIGHT:
        case KEY_DOWN:
        case KEY_TAB: step(1); return true;
        default: break;
    }
    if (key.keycode >= KEY_1 && key.keycode <= KEY_9) {
        // Digits pick a face, and never reach bindings such as SUPER + 1.
        const unsigned face = key.keycode - KEY_1;
        if (face < m_switch->count) {
            m_switch->selected = face;
            commitSwitch();
        }
        return true;
    }
    return false;
}
void Controller::openSwitcher() {
    auto p = m_switch ? find(m_switch->pairID) : nullptr;
    auto s = p && valid(*p) ? state(*p) : std::nullopt;
    if (!s || s->unfolded || s->count < 2) return cancelSwitch();
    finish();
    s = state(*p);
    const auto monitor = s ? s->focused[s->active]->m_monitor.lock() : nullptr;
    if (!monitor) return cancelSwitch();
    SwitcherView view{.pairID = p->id, .monitor = monitor, .card = s->geometry, .count = s->count,
                      .active = s->active, .selected = m_switch->selected};
    view.captured = s->geometry.copy().translate(-monitor->m_position).scale(monitor->m_scale);
    // Hidden faces do not draw, so the previews are snapshots taken now.
    if (g_pHyprRenderer->glBackend() &&
        monitor->m_pixelSize.x * monitor->m_pixelSize.y * 4 * (s->count + 1) <= 256 * 1024 * 1024) {
        std::string error;
        m_mutating = true;
        for (unsigned face = 0; face < s->count; ++face) {
            select(*p, face, false);
            view.faces.push_back(m_shader->captureFace(s->faces[face], monitor, error));
        }
        select(*p, s->active);
        m_mutating = false;
    }
    m_switch->open = true;
    m_switcher->show(std::move(view));
}
void Controller::commitSwitch() {
    if (!m_switch) return;
    const auto chosen = *m_switch;
    cancelSwitch();
    auto p = find(chosen.pairID);
    const auto s = p && valid(*p) ? state(*p) : std::nullopt;
    if (!s || chosen.selected >= s->count || chosen.selected == s->active) return;
    const auto result = flip(std::nullopt, p, chosen.selected);
    if (!result.ok) notify(result);
}
void Controller::cancelSwitch() {
    m_switch.reset();
    if (m_switchTimer) m_switchTimer->updateTimeout(std::nullopt);
    if (m_switcher) m_switcher->hide();
}
Result Controller::switcherAction(const std::string &arguments) {
    // For scripts and tests: the same switcher, driven without holding keys.
    std::istringstream input(arguments);
    std::string verb, value, extra;
    input >> verb;
    if (verb == "open") {
        auto p = find(Desktop::focusState()->window());
        const auto s = p && valid(*p) ? state(*p) : std::nullopt;
        if (!s || s->count <= 2) return {false, "Focus a card with three or more faces."};
        if (s->unfolded) return {false, "Fold the card with O before switching faces."};
        cancelSwitch();
        const unsigned last =
            p->lastFace && *p->lastFace < s->count && *p->lastFace != s->active ? *p->lastFace : s->next();
        m_switch = Switch{p->id, std::nullopt, last, s->count, false, true};
        openSwitcher();
        return {m_switch.has_value(), m_switch ? "ok" : "The switcher could not open."};
    }
    if (verb == "last") {
        // What a tap of the flip key does on a card with three or more faces.
        auto p = find(Desktop::focusState()->window());
        const auto s = p && valid(*p) ? state(*p) : std::nullopt;
        if (!s) return {false, "Focus a card first."};
        const unsigned last =
            p->lastFace && *p->lastFace < s->count && *p->lastFace != s->active ? *p->lastFace : s->next();
        return flip(std::nullopt, p, last);
    }
    if (!m_switch) return {false, "The face switcher is not open."};
    if (verb == "step") {
        int by = 1;
        if (input >> value) by = value == "back" ? -1 : 1;
        m_switch->selected = (m_switch->selected + m_switch->count + by) % m_switch->count;
        m_switcher->select(m_switch->selected);
        return {true, "ok"};
    }
    if (verb == "pick" && input >> value && !(input >> extra)) {
        unsigned face = 0;
        const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), face);
        if (error != std::errc{} || end != value.data() + value.size() || !face || face > m_switch->count)
            return {false, "Pick a face from 1 to " + std::to_string(m_switch->count) + "."};
        m_switch->selected = face - 1;
        commitSwitch();
        return {true, "ok"};
    }
    if (verb == "commit") { commitSwitch(); return {true, "ok"}; }
    if (verb == "cancel") { cancelSwitch(); return {true, "ok"}; }
    return {false, "Use switcher open, step [back], pick <n>, commit, cancel or last."};
}
Result Controller::endPeek() {
    if (!m_peek) return {true, "ok"};
    const auto pending = *m_peek;
    const bool returnable = canReturnPeek();
    m_peek.reset();
    if (!returnable) return {true, "ok"};
    if (m_turn && m_turn->pairID == pending.pairID) {
        if (m_turn->face(m_turn->timeline.destination()) != pending.source)
            m_turn->timeline.reverse();
        return {true, "ok"};
    }
    auto p = find(pending.pairID);
    auto s = p ? state(*p) : std::nullopt;
    return s && s->active != pending.source ? flip(std::nullopt, p, pending.source) : Result{true, "ok"};
}
Result Controller::flip(std::optional<Transition> preview, Pair *target, std::optional<unsigned> to) {
    auto p = target ? target : find(Desktop::focusState()->window());
    if (!p || !valid(*p))
        return {false, "This window has no reverse side. Use mark, then pair."};
    if (inputBusy())
        return {false, "Finish the active grab or drag before flipping."};
    if (m_turn && m_turn->pairID == p->id && (!to || *to == m_turn->source || *to == m_turn->target)) {
        m_turn->previewReturn = false;
        if (preview) return {false, "Wait for this turn to finish before previewing another transition."};
        if (!to || *to != m_turn->face(m_turn->timeline.destination()))
            m_turn->timeline.reverse();
        return {true, "ok"};
    }
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    const unsigned source = s->active, goal = to.value_or(s->next());
    if (goal >= s->count || goal == source)
        return {false, goal == source ? "This face is already showing." : "This card has no such face."};
    const auto mode = preview.value_or(
        forFaces(transition(m_settings.transition->value()).value_or(Transition::Flip), s->count));
    const float travel = Turn::travel(source, goal, s->count);
    if (s->unfolded) {
        if (preview) return {false, "Fold the card with O before previewing a transition."};
        for (const auto &ref : s->windows())
            if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(ref.lock()))
                return {false, "Leave fullscreen before folding this container."};
        auto api = provider(p->providerEpoch);
        m_mutating = true;
        const bool ok = api && api->unfold(p->containerID, false) && api->select(p->containerID, goal, true);
        if (ok) remember(*p, source, goal);
        m_mutating = false;
        return {ok, ok ? "ok" : "The layout could not fold this card."};
    }
    auto a = s->focused[source], b = s->focused[goal];
    if (!p->containerID && !fits(b, a->size(IGeometric::GEOMETRIC_GOAL)))
        return {false, "The other side no longer fits this size. Resize the pair before flipping."};
    std::string reason;
    if (p->containerID) {
        for (const auto &ref : s->windows()) {
            auto member = ref.lock();
            if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(member))
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
        remember(*p, source, goal);
        select(*p, goal);
        damage(*p);
        m_lastFallback = reason.empty() ? "" : "Instant switch: " + reason;
        return {true, "ok"};
    }
    auto pose = std::make_shared<Pose>();
    pose->mode = mode;
    pose->direction = goal > source ? 1.F : -1.F;
    pose->count = mode == Transition::Strip ? s->count : 2;
    pose->from = float(source);
    pose->travel = travel;
    pose->leader = s->focused[source];
    pose->perspective = m_settings.perspective->value();
    pose->retreat = m_settings.retreat->value();
    if (p->containerID)
        pose->containerBox = s->geometry;
    m_turn.emplace(Turn{p->id,
                        source,
                        // A longer slide takes a little longer, not proportionally.
                        Timeline(double(m_settings.duration->value()) *
                                 (mode == Transition::Strip ? 1.0 + .3 * (std::abs(travel) - 1) : 1.0)),
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
    m_turn->target = goal;
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
        // Hyprglass decorates every window, but draws glass only where it is
        // enabled; other windows keep Hyprland's own blur while turning.
        if (glassy(w)) {
            m_turn->suppressedGlass[i] = w->m_ruleApplicator->m_tagKeeper.applyTag("+hyprglass_disabled");
            w->m_ruleApplicator->propertiesChanged(Desktop::Rule::RULE_PROP_TAG);
        }
        w->resetMotionBlur();
    }
    select(*p, source);
    // Focus moves to the other face only when the turn ends. Until then
    // inactive_opacity and dim_inactive would show the wallpaper through it,
    // so every face turns at its focused opacity, undimmed.
    static auto activeOpacity = CConfigValue<Config::FLOAT>("decoration:active_opacity");
    for (const auto &ref : m_turn->windows)
        if (auto member = ref.lock(); member && !Fullscreen::controller()->isFullscreen(member)) {
            member->alpha(WINDOW_ALPHA_ACTIVE)->setValueAndWarp(
                member->m_ruleApplicator->alpha().valueOrDefault().applyAlpha(*activeOpacity));
            member->m_dimPercent->setValueAndWarp(0);
        }
    if (p->containerID)
        if (auto api = provider(p->providerEpoch))
            api->animating(p->containerID, true);
    if (snapshots(mode)) {
        const auto started = Clock::now();
        auto monitor = a->m_monitor.lock();
        // The peak capture budget is one native-sized RGBA buffer per face,
        // one temporary pane and one reusable transition output.
        const bool ring = mode == Transition::Strip;
        const unsigned captures = ring ? s->count : 2;
        if (!monitor || !g_pHyprRenderer->glBackend() ||
            monitor->m_pixelSize.x * monitor->m_pixelSize.y * 4 * (captures + 2) > 256 * 1024 * 1024) {
            pose->error = "Snapshot transition exceeds the 256 MiB buffer budget";
        } else {
            m_mutating = true;
            for (unsigned slot = 0; slot < captures; ++slot) {
                const auto face = ring ? slot : m_turn->face(slot);
                select(*p, face, false);
                pose->faces[slot] = m_shader->captureFace(s->faces[face], monitor, pose->error);
                if (!pose->faces[slot]) break;
            }
            select(*p, source);
            m_mutating = false;
        }
        m_captureMs = std::chrono::duration<double, std::milli>(Clock::now() - started).count();
        if (std::any_of(pose->faces.begin(), pose->faces.begin() + captures, [](const auto &f) { return !f; })) {
            m_lastFallback = "Instant switch: " + pose->error;
            finish(!preview);
            return {true, "ok"};
        }
        m_turn->last = Clock::now(); // capture time is not part of motion progress
    }
    for (unsigned i = 0; i < m_turn->windows.size(); ++i) {
        auto w = m_turn->windows[i].lock();
        auto t = makeUnique<FlipTransformer>(w, pose, m_shader, m_turn->suppressedGlass[i]);
        m_turn->transformers[i] = t.get();
        w->m_transformers.emplace_back(std::move(t));
    }
    m_lastFallback.clear();
    damage(*p);
    m_timer->updateTimeout(std::chrono::milliseconds(250));
    return {true, "ok"};
}
bool Controller::glassy(PHLWINDOW w) {
    const auto &tags = w->m_ruleApplicator->m_tagKeeper;
    if (tags.isTagged("hyprglass_disabled") ||
        std::ranges::none_of(w->m_windowDecorations,
                             [](const auto &deco) { return deco->getDisplayName() == "HyprGlass"; }))
        return false;
    if (tags.isTagged("hyprglass_enabled"))
        return true;
    // Hyprglass's own option, read in place: the plugin may be reloaded.
    const auto global = Config::mgr()->getConfigValue("plugin:hyprglass:enabled");
    return global.dataptr && global.type && *global.type == typeid(Config::INTEGER) &&
           **reinterpret_cast<Config::INTEGER *const *>(global.dataptr);
}
Result Controller::unpair() {
    if (inputBusy())
        return {false, "Finish the active grab or drag before unpairing."};
    auto p = find(Desktop::focusState()->window());
    if (!p)
        return {false, "This window is not a Hyprflip pair."};
    ungroup(*p);
    return {true, "Unpaired. All windows are available in the layout."};
}
Result Controller::ungroup(Pair &p) {
    finish();
    const auto id = p.id;
    auto g = p.group.lock();
    m_mutating = true;
    discardContainer(p);
    if (g) {
        g->setLocked(p.previousLock);
        g->destroy();
    }
    m_mutating = false;
    std::erase_if(m_pairs, [id](const Pair &pair) { return pair.id == id; });
    return {true, "ok"};
}

Result Controller::attach(bool vertical, bool newFace) {
    if (inputBusy())
        return {false, "Finish the active grab or drag before attaching."};
    auto w = m_marked.lock();
    if (auto error = unavailable(w); !error.empty())
        return {false, error};
    if (find(w))
        return {false, "The marked window already belongs to a card."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID)
        return {false, "Focus a multi-app card created with O, then attach the marked window."};
    finish();
    auto s = state(*p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    if (newFace && s->count >= CONTAINER_MAX_FACES)
        return {false, "This card already has " + std::to_string(CONTAINER_MAX_FACES) + " faces."};
    if (!newFace && s->faces[s->active].size() >= CONTAINER_MAX_PANES)
        return {false, "This side already has five apps. Remove an app before adding another."};
    for (const auto &member : s->windows())
        if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(member.lock()))
            return {false, "Leave fullscreen before attaching to this container."};
    if ((w->m_isFloating && p->providerEpoch != FloatingCards::EPOCH) || w->m_workspace != s->focused[s->active]->m_workspace)
        return {false, "Tile the marked window on the same workspace before attaching it."};
    auto api = provider(p->providerEpoch);
    m_mutating = true;
    // A new face goes after the last one, and the card turns to it.
    const unsigned side = newFace ? s->count : s->active;
    bool ok = api && api->attach(p->containerID, reinterpret_cast<uintptr_t>(w.get()), side, vertical);
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
    if (ok && newFace)
        return {true, "Added as " + faceName(side) + ". Flip to go round the faces."};
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
        if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(w.lock()))
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
        return {false, "Focus a multi-app card to move it as a unit."};
    return moveCard(*p, std::to_string(destination), follow);
}
Result Controller::moveCard(Pair &card, const std::string &destination, bool follow, bool scripted) {
    if (!workspaceName(destination))
        return {false, "Use a workspace number, name:<name>, special or special:<name>."};
    if (scripted ? scriptBusy(members(card)) : inputBusy())
        return {false, "Finish the active grab or drag before moving the card."};
    finish();
    auto s = state(card);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    // 0 for named and special workspaces.
    uint32_t number = 0;
    std::from_chars(destination.data(), destination.data() + destination.size(), number);
    // A native card joins a chilled destination the way a new app does, when
    // Chill (Omachill 1.5+) offers join. Otherwise the move is refused.
    const bool chilled = number && std::ranges::any_of(Desktop::windowState()->windows(), [&](const auto& window) {
        return window->m_isMapped && window->m_isFloating && window->m_workspace && window->m_workspace->m_id == number &&
            window->m_ruleApplicator->m_tagKeeper.isTagged("chillmode");
    });
    const bool joins = chilled &&
        HyprlandAPI::invokeHyprctlCommand("repl", "return tostring(chillmode ~= nil and chillmode.join ~= nil)").starts_with("true");
    if (chilled && !joins)
        return {false, "Turn off Chill mode on workspace " + std::to_string(number) +
                       " before moving the card there. The card stayed in place."};
    for (const auto &w : s->windows())
        if (Fullscreen::controller()->isFullscreen(w.lock()))
            return {false, "Leave fullscreen before moving this container."};
    auto api = provider(card.providerEpoch);
    const auto id = card.id;
    if (number) m_movingWorkspace = number;
    m_mutating = true;
    const bool ok = number ? api && api->workspace(card.containerID, number, follow)
                           : FloatingCards::moveTo(card.containerID, destination, follow);
    m_mutating = false;
    m_movingWorkspace.reset();
    reconcile();
    // reconcile() may drop pairs; look the card up again.
    if (auto *moved = ok && joins ? find(id) : nullptr)
        if (const auto after = state(*moved))
            HyprlandAPI::invokeHyprctlCommand("eval", "if chillmode and chillmode.join then chillmode.join(" +
                                                          address(after->focused[after->active]) + ") end");
    return {ok, ok ? "ok" : "The card could not move to that workspace."};
}
Result Controller::show(Pair &p, unsigned side) {
    if (inputBusy())
        return {false, "Finish the active grab or drag before turning the card."};
    finish();
    auto s = state(p);
    if (!s)
        return {false, "This card changed. Pair its windows again."};
    for (const auto &ref : s->windows())
        if (p.providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(ref.lock()))
            return {false, "Leave fullscreen before turning this container."};
    if (s->unfolded) {
        auto api = provider(p.providerEpoch);
        m_mutating = true;
        const bool ok = api && api->unfold(p.containerID, false);
        m_mutating = false;
        if (!ok)
            return {false, "The layout could not fold this card."};
    } else if (s->active == side)
        return {true, "ok"};
    select(p, side);
    damage(p);
    return {true, "ok"};
}
Result Controller::cardAction(const std::string &arguments) {
    static constexpr auto USAGE = "Use card <id> flip, card <id> show <front|back|face number>, card <id> ungroup or "
                                  "card <id> workspace <number|name:<name>|special[:<name>]> [silent], or "
                                  "card <id or 0x address> hold|leave|reveal [speed from 0.05 to 4].";
    std::istringstream input(arguments);
    std::string text, verb, value, extra;
    uint64_t id = 0;
    if (!(input >> text >> verb))
        return {false, USAGE};
    if (verb == "reveal" || verb == "leave" || verb == "hold") {
        static constexpr auto REVEAL_USAGE = "Use card <id or 0x address> hold, card <id or 0x address> leave or "
                                             "card <id or 0x address> reveal [speed from 0.05 to 4].";
        double speed = 1;
        if (verb == "reveal" && input >> value) {
            const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), speed);
            if (error != std::errc{} || end != value.data() + value.size() || !(speed >= .05 && speed <= 4))
                return {false, "The speed of a reveal is a number from 0.05 to 4, not " + value + "."};
        }
        if (input >> extra)
            return {false, REVEAL_USAGE};
        // A window by its address, or a card by its id: the windows it shows.
        std::vector<PHLWINDOW> windows;
        Reveal::Card whole;
        if (text.starts_with("0x")) {
            uintptr_t wanted = 0;
            const auto [end, error] = std::from_chars(text.data() + 2, text.data() + text.size(), wanted, 16);
            if (error != std::errc{} || end != text.data() + text.size())
                return {false, REVEAL_USAGE};
            for (const auto &w : Desktop::windowState()->windows())
                if (reinterpret_cast<uintptr_t>(w.get()) == wanted && w->m_isMapped)
                    windows.push_back(w);
            if (windows.empty())
                return {false, "No window has address " + text + "."};
        } else {
            const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), id);
            if (error != std::errc{} || end != text.data() + text.size() || !id)
                return {false, REVEAL_USAGE};
            if (m_turn && m_turn->pairID == id)
                finish();
            auto *p = find(id);
            const auto s = p && valid(*p) ? state(*p) : std::nullopt;
            if (!s)
                return {false, "No card has id " + text + ". Read the ids from status."};
            for (unsigned side = 0; side < s->count; ++side)
                if (s->unfolded || side == s->active)
                    windows.insert(windows.end(), s->faces[side].begin(), s->faces[side].end());
            whole = {.whole = true, .extraTop = p->frame ? CardFrames::headerHeight() : 0};
        }
        // A fullscreen window has no tile to come into, so this asks nothing of it: the same batch is then a plain cut.
        if (std::ranges::any_of(windows, [](const auto &w) { return Fullscreen::controller()->isFullscreen(w); }))
            return {true, "ok"};
        if (verb == "reveal") {
            Reveal::reveal(windows, speed, whole);
            return {true, "ok"};
        }
        // A snapshot of a window has no card frame in it unless the frames draw into it.
        m_frames->capture([&]() { verb == "leave" ? Reveal::leave(windows) : Reveal::hold(windows, whole); });
        return {true, "ok"};
    }
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), id);
    if (error != std::errc{} || end != text.data() + text.size() || !id)
        return {false, USAGE};
    auto *p = find(id);
    if (!p || !valid(*p))
        return {false, "No card has id " + text + ". Read the ids from status."};
    if (verb == "flip" && !(input >> extra))
        return flip(std::nullopt, p);
    if (verb == "show" && input >> value && !(input >> extra)) {
        // front and back, or a face by its number from 1: front is 1, back is 2.
        unsigned face = 0;
        const auto [last, bad] = std::from_chars(value.data(), value.data() + value.size(), face);
        const bool number = bad == std::errc{} && last == value.data() + value.size();
        const auto s = state(*p);
        if (value == "front" || value == "back")
            return show(*p, value == "back");
        if (number && s && face >= 1 && face <= s->count)
            return show(*p, face - 1);
        return {false, "Use card <id> show front, back, or a face number from 1 to " + std::to_string(s ? s->count : 2) + "."};
    }
    // Another program takes its card apart, parked or on screen; the focus stays.
    if (verb == "ungroup" && !(input >> extra)) {
        const auto windows = members(*p);
        if (std::ranges::any_of(windows, [](const auto &w) { return Fullscreen::controller()->isFullscreen(w); }))
            return {false, "Leave fullscreen before ungrouping the card."};
        if (scriptBusy(windows))
            return {false, "Finish the active grab or drag before ungrouping the card."};
        return ungroup(*p);
    }
    if (verb == "workspace" && input >> value) {
        const bool silent = bool(input >> extra);
        if (silent && (extra != "silent" || input >> extra))
            return {false, USAGE};
        if (!p->containerID)
            return {false, "Only a multi-app card moves as a unit; move a pair's windows with Hyprland."};
        return moveCard(*p, value, !silent, silent);
    }
    return {false, USAGE};
}
std::optional<CBox> Controller::cardBox(const std::string &window) const {
    if (m_stopping) return std::nullopt;
    for (const auto& pair : m_pairs) {
        const auto card = state(pair);
        if (!card) continue;
        for (const auto& w : card->windows())
            if (address(w.lock()) == quote(window)) return card->geometry;
    }
    return std::nullopt;
}
bool Controller::placeCard(const std::string &window, CBox box) {
    if (m_stopping || m_mutating || inputBusy()) return false;
    for (auto& pair : m_pairs) {
        const auto card = state(pair);
        if (!card || pair.providerEpoch != FloatingCards::EPOCH ||
            std::ranges::none_of(card->windows(), [&](const auto& w) { return address(w.lock()) == quote(window); }))
            continue;
        finish();
        m_mutating = true;
        const bool ok = FloatingCards::place(pair.containerID, box);
        m_mutating = false;
        return ok;
    }
    return false;
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
bool Controller::blocksChill(uint32_t workspace) const {
    if (!workspace || m_stopping) return false;
    if (m_movingWorkspace == workspace) return true;
    for (const auto& [token, reservation] : m_reservations)
        if (reservation.workspace == workspace && reservation.until > Clock::now()) return true;
    for (const auto& pair : m_pairs) {
        if (!pair.containerID) continue;
        const auto card = state(pair);
        if (!card || !card->focused[0] || !card->focused[0]->m_workspace ||
            card->focused[0]->m_workspace->m_id != workspace) continue;
        // Chill floats a native card as one window, both faces sharing its
        // frame. Fullscreen cards stay out of Chill.
        if (pair.providerEpoch != FloatingCards::EPOCH ||
            std::ranges::any_of(card->windows(), [](const auto& w) { return Fullscreen::controller()->isFullscreen(w.lock()); }))
            return true;
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
        if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(w.lock()))
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
        if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(member.lock()))
            return {false, "Leave fullscreen before changing the card layout."};
    if (s->faces[s->active].size() < 2)
        return {false, "This side needs at least two apps. Add an app from the card menu first."};
    if (operation == ContainerEdit::OtherSide && s->faces[s->next()].size() >= CONTAINER_MAX_PANES)
        return {false, s->count > 2 ? "The next face already has five apps. Remove an app there first."
                                    : "The other side already has five apps. Remove an app there first."};
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
        if (p->providerEpoch != FloatingCards::EPOCH && Fullscreen::controller()->isFullscreen(member.lock()))
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
    if (s->active != m_turn->face(m_turn->timeline.secondSide())) {
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
    m_turn->pose->angle = float(m_turn->timeline.angle()) * m_turn->sign();
    m_turn->pose->progress = m_turn->timeline.progress();
    m_turn->pose->dirty = true;
    const auto destination = m_turn->face(m_turn->timeline.secondSide());
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
// Rebuild a native card from the description the installer saved from
// status before reloading the plugin:
//   <tiled|floating> <active> <unfolded> <x> <y> <w> <h>
//   front <horizontal|vertical> <focused> <address:ratio>...
//   back  <horizontal|vertical> <focused> <address:ratio>...
//   [face <horizontal|vertical> <focused> <address:ratio>...]  a third face, then a fourth
Result Controller::restore(const std::string &arguments) {
    std::istringstream input(arguments);
    std::string mode, token;
    ContainerSnapshot snapshot;
    input >> mode;
    const bool quiet = mode == "quiet";
    if (quiet)
        input >> mode;
    if (!(input >> snapshot.active >> snapshot.unfolded >> snapshot.x >> snapshot.y >> snapshot.width >> snapshot.height) ||
        (mode != "tiled" && mode != "floating") || snapshot.active >= CONTAINER_MAX_FACES || snapshot.unfolded > 1)
        return {false, "Use restore [quiet] <tiled|floating> <active> <unfolded> <x> <y> <w> <h> front ... back ... [face ...]"};
    unsigned faces = 2;
    int side = -1;
    std::string address;
    const auto parse = [](const std::string &text, uintptr_t &value) {
        if (!text.starts_with("0x")) return false;
        const auto [end, error] = std::from_chars(text.data() + 2, text.data() + text.size(), value, 16);
        return error == std::errc{} && end == text.data() + text.size();
    };
    while (input >> token) {
        if (token == "front" || token == "back" || token == "face") {
            if (token == "face" && faces >= CONTAINER_MAX_FACES)
                return {false, "A card has at most " + std::to_string(CONTAINER_MAX_FACES) + " faces."};
            side = token == "front" ? 0 : token == "back" ? 1 : faces++;
            std::string axis, focused;
            if (!(input >> axis >> focused) || (axis != "horizontal" && axis != "vertical") ||
                !parse(focused, snapshot.focused[side]))
                return {false, "Each face needs an axis and a focused app address."};
            snapshot.vertical[side] = axis == "vertical";
            continue;
        }
        const auto colon = token.find(':');
        uintptr_t window = 0;
        double ratio = 0;
        if (side < 0 || colon == std::string::npos || snapshot.count[side] >= CONTAINER_MAX_PANES ||
            !parse(token.substr(0, colon), window))
            return {false, "Invalid app in the card description."};
        const auto text = token.substr(colon + 1);
        const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), ratio);
        if (error != std::errc{} || end != text.data() + text.size() || !std::isfinite(ratio) || ratio <= 0)
            return {false, "Invalid app proportion in the card description."};
        snapshot.windows[side][snapshot.count[side]] = window;
        snapshot.ratios[side][snapshot.count[side]++] = ratio;
    }
    snapshot.faces = faces;
    for (unsigned s = 0; s < faces; ++s)
        if (!snapshot.count[s])
            return {false, faces > 2 ? "Every face of a card needs an app." : "A card needs apps on both faces."};
    if (snapshot.active >= faces)
        return {false, "The shown face is not one of the card's faces."};
    std::vector<PHLWINDOW> apps;
    for (unsigned s = 0; s < faces; ++s)
        for (unsigned i = 0; i < snapshot.count[s]; ++i)
            for (const auto &w : Desktop::windowState()->windows())
                if (reinterpret_cast<uintptr_t>(w.get()) == snapshot.windows[s][i]) {
                    if (find(w))
                        return {false, "An app in that card already belongs to another card."};
                    apps.push_back(w);
                }
    if (quiet ? scriptBusy(apps) : inputBusy())
        return {false, "Finish the active grab or drag before restoring a card."};
    if (!FloatingCards::canCreate(snapshot))
        return {false, FloatingCards::fitProblem(snapshot, mode == "floating")};
    // A quiet restore leaves the focus alone, unless it is on one of the card's
    // apps: it then goes to the shown side, never staying on a hidden one.
    const auto focused = reinterpret_cast<uintptr_t>(Desktop::focusState()->window().get());
    bool member = false;
    for (unsigned s = 0; s < faces; ++s)
        for (unsigned i = 0; i < snapshot.count[s]; ++i)
            member |= focused && snapshot.windows[s][i] == focused;
    m_mutating = true;
    const auto id = FloatingCards::create(snapshot, mode == "floating", !quiet || member);
    if (id) m_pairs.push_back({m_nextID++, {}, {}, false, id, FloatingCards::EPOCH});
    m_mutating = false;
    reconcile();
    if (!id) {
        const auto why = FloatingCards::fitProblem(snapshot, mode == "floating");
        return {false, why.empty() ? "The card could not be restored; its apps stay open." : why};
    }
    return {true, "ok"};
}
Result Controller::fullscreen() {
    if (inputBusy()) return {false, "Finish the active grab or drag before changing fullscreen."};
    auto p = find(Desktop::focusState()->window());
    if (!p || !p->containerID || p->providerEpoch != FloatingCards::EPOCH)
        return {false, "Focus an app in a multi-app card to fullscreen the card."};
    finish();
    m_mutating = true;
    const bool ok = FloatingCards::fullscreen(p->containerID);
    m_mutating = false;
    reconcile();
    return {ok, ok ? "ok" : "The card could not change fullscreen."};
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
    snapshot.faces = current->count;
    for (unsigned side = 0; side < current->count; ++side) {
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
    if (action == "fullscreen") return fullscreen();
    if (action.starts_with("restore ")) return restore(action.substr(8));
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
    if (action.starts_with("mark 0x"))
        return mark(action.substr(5));
    if (action == "pair")
        return pair();
    if (action == "card")
        return pair(true);
    if (action.starts_with("card "))
        return cardAction(action.substr(5));
    if (action.starts_with("adopt ")) {
        std::istringstream arguments(action.substr(6));
        std::string front, back, extra;
        if (!(arguments >> front >> back) || arguments >> extra)
            return {false, "Use adopt <front-address> <back-address>."};
        return adopt(front, back);
    }
    if (action == "flip")
        return flipKey();
    if (action == "switcher" || action.starts_with("switcher "))
        return switcherAction(action.size() > 9 ? action.substr(9) : "");
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
    if (action == "attach face")
        return attach(false, true);
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
    if (action == "layout toggle") {
        // Super+J on a card face: flip its apps between beside and stacked.
        auto p = find(Desktop::focusState()->window());
        const auto s = p && p->containerID ? state(*p) : std::nullopt;
        if (!s) return {false, "Focus an app in a Hyprflip container first."};
        return editContainer(s->vertical[s->active] ? ContainerEdit::Horizontal : ContainerEdit::Vertical);
    }
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
    return {false,
            "Unknown action. Use mark, pair, card, attach [horizontal|vertical], replace <old> <new>, release, unfold, "
            "layout <horizontal|vertical|balance|toggle>, other_side, "
            "workspace <number> [silent], move <left|right|up|down>, cancel, "
            "flip, peek [end], unpair, finish, restore [quiet] ..., "
            "card <id> <flip|show <front|back>|ungroup|workspace <workspace> [silent]>, "
            "card <id or 0x address> hold|leave|reveal [speed], or status."};
}
namespace {
// notify-send on PATH, for desktop notifications through the user's daemon.
std::optional<std::string> notifySend() {
    const char *path = getenv("PATH");
    std::istringstream dirs(path ? path : "/usr/local/bin:/usr/bin:/bin");
    for (std::string dir; std::getline(dirs, dir, ':');) {
        auto candidate = std::filesystem::path(dir) / "notify-send";
        if (!dir.empty() && access(candidate.c_str(), X_OK) == 0) return candidate.string();
    }
    return std::nullopt;
}
} // namespace
void Controller::notify(const Result &r) {
    if (!m_settings.notifications->value() || r.message == "ok")
        return;
    // A desktop notification matches the rest of the desktop; the same
    // synchronous hint makes a newer message replace an older one.
    if (m_settings.desktopNotifications->value())
        if (const auto binary = notifySend()) {
            Hyprutils::OS::CProcess process(*binary, {"--app-name=Hyprflip", "--expire-time=3500",
                                                      "--hint=string:x-canonical-private-synchronous:hyprflip",
                                                      "--icon=" + std::string(r.ok ? "dialog-information" : "dialog-warning"),
                                                      "Hyprflip", r.message});
            if (process.runAsync())
                return;
        }
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
                       ",\"accent_ring\":" + (m_settings.accentRing->value() ? "true" : "false") +
                       ",\"accent_color\":" + quote(parseAccent(m_settings.accentColor->value()) ? m_settings.accentColor->value() : "") +
                       ",\"fullscreen_divider\":" + std::to_string(m_settings.fullscreenDivider->value()) +
                       ",\"divider_color\":" + quote(parseAccent(m_settings.dividerColor->value()) ? m_settings.dividerColor->value() : "") +
                       ",\"drag_to_add\":" + (m_settings.dragToAdd->value() ? "true" : "false") +
                       ",\"fullscreen_focus\":" + (FloatingCards::focusShared() ? "true" : "false") +
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
        for (unsigned side = 0; side < s->count; ++side) {
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
        json += "],\"native_group\":" + std::string(p.providerEpoch == FloatingCards::EPOCH ? "true" : "false") +
                ",\"fullscreen\":" + std::string(std::ranges::any_of(s->windows(), [](const auto &w) { return Fullscreen::controller()->isFullscreen(w.lock()); }) ? "true" : "false") + ",\"floating\":" + std::string(s->focused[s->active]->m_isFloating ? "true" : "false");
        const auto space = s->focused[s->active]->m_workspace;
        json += ",\"workspace\":{\"id\":" + std::to_string(space ? space->m_id : 0) + ",\"name\":" + quote(space ? space->m_name : "") +
                ",\"special\":" + (space && space->m_isSpecialWorkspace ? "true" : "false") + "},\"layouts\":[";
        for (unsigned side = 0; side < s->count; ++side) {
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
    return json + "],\"card_frames\":" + (m_frames ? m_frames->status() : "[]") +
           ",\"card_rings\":" + (m_frames ? m_frames->rings() : "[]") +
           ",\"card_dividers\":" + (m_frames ? m_frames->dividers() : "[]") +
           ",\"native_cards\":true,\"floating_cards\":true,\"workspace_protection\":true,\"container_provider\":true" +
           ",\"layout_controls\":true,\"repair_cards\":true,\"card_ungroup\":true,\"pane_replacement\":true" +
           ",\"reveal\":true,\"container_max_panes\":" + std::to_string(CONTAINER_MAX_PANES) +
           ",\"container_max_faces\":" + std::to_string(CONTAINER_MAX_FACES) +
           ",\"switcher\":" + m_switcher->status() + ",\"switch_pending\":" +
           (m_switch && !m_switch->open ? "true" : "false") + "}";
}
} // namespace Hyprflip
