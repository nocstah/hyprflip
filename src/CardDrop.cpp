// SPDX-License-Identifier: MIT
#include "CardDrop.hpp"
#include <algorithm>
#include <cmath>
#include <format>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/ViewState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/protocols/core/DataDevice.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/pass/PassElement.hpp>
#include <linux/input-event-codes.h>

namespace Hyprflip {
namespace {
bool blocked() {
    const auto grab = g_pSeatManager->m_seatGrab;
    return g_pSessionLockManager->isSessionLocked() || (grab && (grab->m_keyboard || grab->m_pointer)) ||
           PROTO::data->dndActive() || g_pInputManager->isConstrained();
}
int fontSize() {
    static auto value = CConfigValue<Config::INTEGER>("group:groupbar:font_size");
    return std::clamp<int>(*value, 12, 24);
}
struct Paint {
    CBox zone, preview, textBox;
    Config::CGradientValueData border;
    CHyprColor fill, tint;
    SP<Render::ITexture> text;
    int round = 0;
};
class DropPass final : public IPassElement {
  public:
    explicit DropPass(Paint data) : data(std::move(data)) {}
    std::vector<UP<IPassElement>> draw() override {
        auto &gl = Render::GL::g_pHyprOpenGL;
        if (!data.preview.empty()) {
            gl->renderRect(data.preview, data.tint, {.round = data.round});
            gl->renderBorder(data.preview.copy().expand(-2), data.border, {.round = data.round, .borderSize = 2});
        }
        gl->renderRect(data.zone, data.fill, {.round = data.round});
        gl->renderBorder(data.zone.copy().expand(-2), data.border, {.round = data.round, .borderSize = 2});
        if (data.text)
            gl->renderTexture(data.text, data.textBox, {});
        return {};
    }
    bool needsLiveBlur() override { return false; }
    bool needsPrecomputeBlur() override { return false; }
    const char *passName() override { return "HyprflipCardDropPass"; }
    ePassElementType type() override { return EK_CUSTOM; }
    bool disableSimplification() override { return true; }
    Paint data;
};
} // namespace

CardDrop::CardDrop(Source source, Commit commit) : m_source(std::move(source)), m_commit(std::move(commit)) {
    auto &e = Event::bus()->m_events;
    m_listeners.emplace_back(e.input.mouse.move.listen([this](Vector2D, Event::SCallbackInfo &info) {
        if (!info.cancelled)
            m_seen = dragged();
        refresh();
    }));
    m_listeners.emplace_back(e.render.pre.listen([this](PHLMONITOR) { refresh(); }));
    m_listeners.emplace_back(e.render.stage.listen([this](eRenderStage s) {
        if (s == RENDER_POST_WINDOWS)
            paint(); // above the moving app, below menus and lock surfaces
    }));
    m_listeners.emplace_back(e.input.mouse.button.listen([this](const IPointer::SButtonEvent &event, Event::SCallbackInfo &info) {
        if (info.cancelled || event.state != WL_POINTER_BUTTON_STATE_RELEASED || event.button != BTN_LEFT)
            return;
        const auto w = dragged();
        refresh();
        if (w && w == m_seen && w != m_cancelled)
            for (const auto &target : m_targets)
                if (target.hovered) {
                    m_commit(w, target.offer);
                    break;
                }
        clear();
    }));
    m_listeners.emplace_back(e.input.keyboard.key.listen([this](const IKeyboard::SKeyEvent &key, Event::SCallbackInfo &) {
        if (key.state == WL_KEYBOARD_KEY_STATE_PRESSED && key.keycode == KEY_ESC) {
            m_cancelled = dragged();
            clear();
        }
    }));
    m_listeners.emplace_back(e.config.preReload.listen([this]() { m_cancelled = dragged(); clear(); }));
    m_listeners.emplace_back(e.config.reloaded.listen([this]() { m_textures.clear(); }));
    m_listeners.emplace_back(e.window.close.listen([this](PHLWINDOW) { clear(); }));
    m_listeners.emplace_back(g_pSessionLockManager->m_events.lock.listen([this]() { m_cancelled = dragged(); clear(); }));
}
CardDrop::~CardDrop() {
    m_listeners.clear();
    clear();
    g_pHyprRenderer->m_renderPass.removeAllOfType("HyprflipCardDropPass");
    g_pHyprRenderer->glBackend()->makeEGLCurrent();
    m_textures.clear();
}
PHLWINDOW CardDrop::dragged() const {
    static auto threshold = CConfigValue<Config::INTEGER>("binds:drag_threshold");
    const auto &drag = g_layoutManager->dragController();
    const auto target = drag->target();
    // Hyprland clears this flag after dispatching a bind. With a zero threshold
    // it stays false during a valid drag; our motion listener still requires
    // actual pointer movement before showing or accepting a target.
    if (blocked() || !target || drag->mode() != MBIND_MOVE || (*threshold > 0 && !drag->dragThresholdReached()))
        return nullptr;
    return target->window();
}
std::vector<CardDrop::Target> CardDrop::targets(PHLWINDOW w) const {
    std::vector<Target> result;
    if (!w || w == m_cancelled || w != m_seen)
        return result;
    const auto pos = g_pInputManager->getMouseCoordsInternal();
    const auto under = Desktop::viewState()->hitTest().windowAt(
        pos, Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING, w);
    for (auto offer : m_source(w)) {
        const auto box = offer.box;
        const double width = std::min(box.w - 16, 420.);
        if (width < 150 || box.h < fontSize() + 32)
            continue;
        Target target;
        target.offer = std::move(offer);
        target.zone = {box.x + (box.w - width) / 2, box.y + 8, width, double(fontSize() + 24)};
        const auto covering = Desktop::viewState()->hitTest().windowAt(
            target.zone.pos() + target.zone.size() / 2.,
            Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING, w);
        if (covering && std::ranges::find(target.offer.members, covering) == target.offer.members.end())
            continue;
        target.hovered = target.zone.containsPoint(pos) &&
                         (!under || std::ranges::find(target.offer.members, under) != target.offer.members.end());
        const std::string face = target.offer.side ? "Back" : "Front";
        target.text = target.offer.refusal.empty() ? "Drop to add to " + face : face + ": " + target.offer.refusal;
        if (target.hovered && target.offer.refusal.empty()) {
            target.preview = box;
            if (target.offer.vertical) {
                target.preview.h = box.h / (target.offer.count + 1);
                target.preview.y += box.h - target.preview.h;
            } else {
                target.preview.w = box.w / (target.offer.count + 1);
                target.preview.x += box.w - target.preview.w;
            }
        }
        result.push_back(std::move(target));
    }
    return result;
}
void CardDrop::clear() {
    for (const auto &t : m_targets)
        g_pHyprRenderer->damageBox(t.offer.box.copy().expand(2));
    m_targets.clear();
    m_seen.reset();
}
void CardDrop::refresh() {
    const auto w = dragged();
    if (!w) {
        m_cancelled.reset();
        if (!m_targets.empty()) clear();
        return;
    }
    auto next = targets(w);
    const auto same = [](const Target &a, const Target &b) {
        return a.offer.id == b.offer.id && a.offer.side == b.offer.side && a.offer.box == b.offer.box &&
               a.zone == b.zone && a.preview == b.preview && a.text == b.text && a.hovered == b.hovered;
    };
    if (std::ranges::equal(next, m_targets, same))
        return;
    for (const auto &t : m_targets) g_pHyprRenderer->damageBox(t.offer.box.copy().expand(2));
    for (const auto &t : next) g_pHyprRenderer->damageBox(t.offer.box.copy().expand(2));
    m_targets = std::move(next);
}
void CardDrop::paint() {
    const auto monitor = g_pHyprRenderer->m_renderData.pMonitor;
    if (!monitor || blocked()) return;
    static auto active = CConfigValue<Config::IComplexConfigValue>("general:col.active_border");
    static auto inactive = CConfigValue<Config::IComplexConfigValue>("general:col.inactive_border");
    static auto font = CConfigValue<Config::STRING>("group:groupbar:font_family");
    static auto textColor = CConfigValue<Config::INTEGER>("group:groupbar:text_color");
    const auto color = CHyprColor(*textColor).stripA();
    const auto linear = [](double c) { return c <= .04045 ? c / 12.92 : std::pow((c + .055) / 1.055, 2.4); };
    const double luminance = .2126 * linear(color.r) + .7152 * linear(color.g) + .0722 * linear(color.b);
    const double scale = monitor->m_scale;
    const auto local = [&](CBox b) { return b.translate(-monitor->m_position).scale(scale).round(); };
    for (const auto &t : m_targets) {
        if (!t.zone.overlaps(monitor->logicalBox())) continue;
        Paint p;
        p.zone = local(t.zone);
        p.preview = t.preview.empty() ? CBox{} : local(t.preview);
        p.round = std::lround(6 * scale);
        p.border = *static_cast<Config::CGradientValueData *>((t.hovered ? active : inactive).ptr());
        // Honor the groupbar foreground and retain at least 4.5:1 contrast.
        p.fill = luminance > .179 ? CHyprColor(0xff000000) : CHyprColor(0xffffffff);
        p.tint = p.border.m_colors.front().modifyA(.15F);
        const auto key = std::format("{}:{}:{}:{}", t.text, scale, fontSize(), *textColor);
        if (m_textures.size() > 24) m_textures.clear();
        auto &texture = m_textures[key];
        if (!texture)
            texture = g_pHyprRenderer->renderText(t.text, color, std::lround(fontSize() * scale), false, *font);
        p.text = texture;
        if (texture) {
            const auto size = texture->m_size * std::min(1., (p.zone.w - 20 * scale) / texture->m_size.x);
            p.textBox = CBox{p.zone.pos() + (p.zone.size() - size) / 2., size}.round();
        }
        g_pHyprRenderer->m_renderPass.add(makeUnique<DropPass>(std::move(p)));
    }
}
std::string CardDrop::status() const {
    std::string json = "[";
    for (const auto &t : m_targets) {
        if (json.size() > 1) json += ',';
        json += std::format("{{\"id\":{},\"side\":{},\"zone\":[{},{},{},{}],\"hovered\":{},\"allowed\":{}}}",
                            t.offer.id, t.offer.side, t.zone.x, t.zone.y, t.zone.w, t.zone.h,
                            t.hovered ? "true" : "false", t.offer.refusal.empty() ? "true" : "false");
    }
    return json + ']';
}
} // namespace Hyprflip
