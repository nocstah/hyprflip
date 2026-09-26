// SPDX-License-Identifier: MIT
#include "CardFrames.hpp"
#include <algorithm>
#include <cmath>
#include <format>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/View.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/protocols/core/DataDevice.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/CHyprGroupBarDecoration.hpp>
#include <hyprland/src/render/pass/PassElement.hpp>
#include <linux/input-event-codes.h>

namespace Hyprflip {
namespace {
using namespace Desktop::View;
constexpr auto HEADER_NAME = "Hyprflip card header";
// The accent ring sits just outside the card's window borders.
constexpr int RING_GAP = 2, RING_MAX = 4, DAMAGE_MARGIN = RING_GAP + RING_MAX + 2;
bool shown(PHLWINDOW w) {
    return w && w->m_isMapped && !w->isHidden() && w->m_workspace && w->m_workspace->m_visible &&
           w->alpha(WINDOW_ALPHA_LAYOUT)->value() > .01F && !Fullscreen::controller()->hasFullscreen(w->m_workspace);
}
bool busy() {
    const auto grab = g_pSeatManager->m_seatGrab;
    return g_pSessionLockManager->isSessionLocked() || (grab && (grab->m_keyboard || grab->m_pointer)) ||
           PROTO::data->dndActive() || g_pInputManager->isConstrained() || g_pInputManager->hasHeldButtons();
}
int fontSize() {
    static auto value = CConfigValue<Config::INTEGER>("group:groupbar:font_size");
    return std::clamp<int>(*value, 11, 24);
}
double luminance(CHyprColor color) {
    const auto linear = [](double c) { return c <= .04045 ? c / 12.92 : std::pow((c + .055) / 1.055, 2.4); };
    return .2126 * linear(color.r) + .7152 * linear(color.g) + .0722 * linear(color.b);
}
double contrast(CHyprColor a, CHyprColor b) {
    const auto x = luminance(a), y = luminance(b);
    return (std::max(x, y) + .05) / (std::min(x, y) + .05);
}
CHyprColor controlFill(CHyprColor text) {
    auto dark = CHyprColor(0xff202329), light = CHyprColor(0xfff4f5f7);
    auto fill = contrast(text, dark) > contrast(text, light) ? dark : light;
    if (contrast(text, fill) < 4.5)
        fill = luminance(text) > .179 ? CHyprColor(0xff000000) : CHyprColor(0xffffffff);
    return fill;
}
// A genuine groupbar subclass keeps native group cleanup/type expectations.
// It reserves the compact header; the common renderer paints all card kinds.
class FrameGroupBar final : public CHyprGroupBarDecoration {
  public:
    explicit FrameGroupBar(PHLWINDOW w) : CHyprGroupBarDecoration(w), window(w) {}
    SDecorationPositioningInfo getPositioningInfo() override {
        const double height =
            window && !Fullscreen::controller()->isFullscreen(window.lock()) ? CardFrames::headerHeight() : 0;
        return {.policy = DECORATION_POSITION_STICKY,
                .edges = DECORATION_EDGE_TOP,
                .priority = 3,
                .desiredExtents = {{0., height}, {}},
                .reserved = true};
    }
    void draw(PHLMONITOR, const float &) override {
        const double height = getPositioningInfo().desiredExtents.topLeft.y;
        if (height != previousHeight) {
            previousHeight = height;
            g_pDecorationPositioner->repositionDeco(this);
        }
    }
    bool onInputOnDeco(eInputType, const Vector2D &, std::any) override { return false; }
    uint64_t getDecorationFlags() override { return 0; }
    std::string getDisplayName() override { return HEADER_NAME; }
    PHLWINDOWREF window;
    double previousHeight = -1;
};
struct PaintData {
    bool frame = false;
    CBox box, label, button, labelText, buttonText, focusPane, ring;
    Config::CGradientValueData border, ringColor;
    int ringWidth = 0, ringRound = 0;
    CHyprColor fill, buttonFill;
    SP<Render::ITexture> labelTexture, buttonTexture;
    float alpha = 1;
    int width = 2, round = 0, controlRound = 0, controlInset = 1;
    float roundingPower = 2;
    int focusWidth = 0, focusRound = 0;
};
// All data is owned by the pass. No controller, provider or window pointers can
// become dangling between pass collection and execution. Purge before dlclose.
class CardFramePass final : public IPassElement {
  public:
    explicit CardFramePass(PaintData data, CBox bounds) : data(std::move(data)), bounds(bounds) {}
    std::vector<UP<IPassElement>> draw() override {
        auto &gl = Render::GL::g_pHyprOpenGL;
        if (!data.ring.empty())
            gl->renderBorder(data.ring, data.ringColor,
                             {.round = data.ringRound,
                              .roundingPower = data.roundingPower,
                              .borderSize = data.ringWidth,
                              .a = data.alpha});
        if (!data.frame)
            return {};
        if (!data.focusPane.empty() && data.focusWidth)
            gl->renderBorder(data.focusPane, data.border,
                             {.round = data.focusRound,
                              .roundingPower = data.roundingPower,
                              .borderSize = data.focusWidth,
                              .a = data.alpha});
        gl->renderBorder(
            data.box, data.border,
            {.round = data.round, .roundingPower = data.roundingPower, .borderSize = data.width, .a = data.alpha});
        const auto control = [&](const CBox &box, CHyprColor fill) {
            gl->renderRect(box, fill.modifyA(fill.a * data.alpha), {.round = data.controlRound});
            gl->renderBorder(
                box.copy().expand(-data.controlInset), data.border,
                {.round = std::max(0, data.controlRound - data.controlInset), .borderSize = 1, .a = data.alpha});
        };
        if (!data.label.empty())
            control(data.label, data.fill);
        control(data.button, data.buttonFill);
        Render::GL::CHyprOpenGLImpl::STextureRenderData textureData{};
        textureData.a = data.alpha;
        if (data.labelTexture && !data.label.empty())
            gl->renderTexture(data.labelTexture, data.labelText, textureData);
        if (data.buttonTexture)
            gl->renderTexture(data.buttonTexture, data.buttonText, textureData);
        return {};
    }
    bool needsLiveBlur() override { return false; }
    bool needsPrecomputeBlur() override { return false; }
    const char *passName() override { return "HyprflipCardFramePass"; }
    ePassElementType type() override { return EK_CUSTOM; }
    std::optional<CBox> boundingBox() override { return bounds; }
    bool disableSimplification() override { return true; }
    PaintData data;
    CBox bounds;
};
} // namespace

double CardFrames::headerHeight() { return fontSize() + 16; }
CardFrames::CardFrames(Source source, Activate activate)
    : m_source(std::move(source)), m_activate(std::move(activate)) {
    auto &e = Event::bus()->m_events;
    m_listeners.emplace_back(e.render.pre.listen([this](PHLMONITOR) { refresh(); }));
    m_listeners.emplace_back(e.render.stage.listen([this](eRenderStage stage) { this->stage(stage); }));
    m_listeners.emplace_back(e.input.mouse.move.listen([this](Vector2D pos, Event::SCallbackInfo &) {
        if (m_pressed && pos.distance(m_pressPosition) > 5)
            m_dragged = true;
        const auto over = busy() ? std::nullopt : hit(pos);
        if (over != m_hovered) {
            m_hovered = over;
            refresh();
        }
    }));
    m_listeners.emplace_back(e.config.reloaded.listen([this]() {
        m_textures.clear();
        refresh(true);
    }));
    m_listeners.emplace_back(e.window.active.listen([this](PHLWINDOW, Desktop::eFocusReason) { refresh(); }));
    m_listeners.emplace_back(e.window.close.listen([this](PHLWINDOW) {
        clearInput();
        refresh();
    }));
    m_listeners.emplace_back(e.workspace.active.listen([this](PHLWORKSPACE) {
        clearInput();
        refresh();
    }));
    m_listeners.emplace_back(g_pSessionLockManager->m_events.lock.listen([this]() {
        clearInput();
        refresh();
    }));
}
CardFrames::~CardFrames() {
    m_listeners.clear();
    g_pHyprRenderer->m_renderPass.removeAllOfType("HyprflipCardFramePass");
    nativeHeaders({});
    for (const auto &[_, previous] : m_last)
        g_pHyprRenderer->damageBox(previous.box.copy().expand(DAMAGE_MARGIN));
    g_pHyprRenderer->glBackend()->makeEGLCurrent();
    m_textures.clear();
}
void CardFrames::nativeHeaders(const std::vector<PHLWINDOWREF> &windows) {
    auto all = Desktop::windowState()->windows();
    for (const auto &ref : m_headerWindows)
        if (auto w = ref.lock(); w && std::ranges::find(all, w) == all.end())
            all.push_back(w);
    for (const auto &w : all) {
        auto current = w->getDecorationByType(DECORATION_GROUPBAR);
        const bool ours = current && current->getDisplayName() == HEADER_NAME;
        const bool wanted = w->m_isMapped && w->m_group && std::ranges::find(windows, w) != windows.end();
        if (ours == wanted)
            continue;
        if (current) {
            if (!w->m_isMapped || w->isHidden()) {
                // updateWindowDecos deliberately skips hidden/unmapped windows.
                // Drain our replacement here, including retained closing views,
                // so none of its virtual methods can survive module unload.
                std::erase(w->m_decosToRemove, current);
                g_pDecorationPositioner->uncacheDecoration(current);
                std::erase_if(w->m_windowDecorations, [current](const auto &d) { return d.get() == current; });
                g_pDecorationPositioner->forceRecalcFor(w);
            } else
                w->removeWindowDeco(current);
        }
        if (wanted) {
            w->addWindowDeco(makeUnique<FrameGroupBar>(w));
            if (std::ranges::find(m_headerWindows, w) == m_headerWindows.end())
                m_headerWindows.push_back(w);
        } else if (w->m_group && w->m_isMapped)
            w->addWindowDeco(makeUnique<CHyprGroupBarDecoration>(w));
        w->updateWindowDecos();
    }
    std::erase_if(m_headerWindows, [](const auto &w) {
        if (!w)
            return true;
        const auto deco = w->getDecorationByType(DECORATION_GROUPBAR);
        return !deco || deco->getDisplayName() != HEADER_NAME;
    });
}
std::vector<CardFrames::Layout> CardFrames::layouts() const {
    std::vector<Layout> result;
    if (g_pSessionLockManager->isSessionLocked())
        return result;
    for (auto view : m_source()) {
        Layout layout;
        layout.view = std::move(view);
        bool any = false;
        for (const auto &w : Desktop::windowState()->windows()) {
            if (!shown(w) || std::ranges::find(layout.view.windows, w) == layout.view.windows.end())
                continue;
            auto box = w->geometricBox(IGeometric::GEOMETRIC_CURRENT).expand(w->getRealBorderSize());
            box.translate(w->m_floatingOffset);
            if (w->m_workspace && !w->m_pinned)
                box.translate(w->m_workspace->m_renderOffset->value());
            if (!any)
                layout.box = box;
            else {
                const double x = std::min(layout.box.x, box.x), y = std::min(layout.box.y, box.y);
                layout.box = {x, y, std::max(layout.box.x + layout.box.w, box.x + box.w) - x,
                              std::max(layout.box.y + layout.box.h, box.y + box.h) - y};
            }
            layout.anchor = w;
            any = true;
        }
        if (!any)
            continue;
        layout.focused =
            std::ranges::find(layout.view.windows, Desktop::focusState()->window()) != layout.view.windows.end();
        layout.alpha = layout.anchor->m_workspace->m_alpha->value() * layout.anchor->alpha(WINDOW_ALPHA_FADE)->value();
        // Native groups use group-wide border colors. On multi-app faces, keep
        // the actual keyboard recipient distinct using the normal focus color.
        const auto focused = Desktop::focusState()->window();
        // Hyprland renders the focused tiled window after every other tiled
        // window, regardless of window-state order. Insert the frame after it
        // so its group border cannot overwrite the pane's focus outline.
        if (layout.focused && focused && !focused->m_isFloating && shown(focused))
            layout.anchor = focused;
        if (!layout.view.frame) {
            result.push_back(std::move(layout));
            continue;
        }
        if (layout.focused && focused && focused->m_group && !layout.view.animating &&
            (layout.view.unfolded || layout.view.count[layout.view.active] > 1)) {
            layout.focusPane =
                focused->geometricBox(IGeometric::GEOMETRIC_CURRENT).translate(focused->m_floatingOffset);
            if (!focused->m_pinned)
                layout.focusPane.translate(focused->m_workspace->m_renderOffset->value());
            layout.focusWidth = focused->getRealBorderSize();
            layout.focusRound = focused->rounding();
        }
        const auto height = headerHeight();
        layout.box.y -= height;
        layout.box.h += height;
        const double controlHeight = height - 4;
        const double buttonWidth = std::min(layout.box.w - 8, fontSize() * 4.0 + 24);
        if (buttonWidth < 38 || layout.box.h < height + 12)
            continue;
        layout.button = {layout.box.x + layout.box.w - buttonWidth - 4, layout.box.y, buttonWidth, controlHeight};
        layout.text = layout.view.unfolded ? "Both sides" : layout.view.active ? "Back" : "Front";
        const auto count =
            layout.view.unfolded ? layout.view.count[0] + layout.view.count[1] : layout.view.count[layout.view.active];
        const auto longText = layout.text + " · " + std::to_string(count) + (count == 1 ? " app" : " apps");
        double labelWidth = longText.size() * fontSize() * .64 + 20;
        if (labelWidth + buttonWidth + 24 <= layout.box.w)
            layout.text = longText;
        else
            labelWidth = layout.text.size() * fontSize() * .64 + 20;
        if (labelWidth + buttonWidth + 24 <= layout.box.w)
            layout.label = {layout.box.x + 8, layout.box.y, labelWidth, controlHeight};
        result.push_back(std::move(layout));
    }
    return result;
}
void CardFrames::refresh(bool force) {
    std::map<uint64_t, DamageState> next;
    for (const auto &layout : layouts())
        next[layout.view.id] = {layout.box,
                                layout.focusPane,
                                layout.text,
                                layout.focused,
                                m_hovered == layout.view.id,
                                m_pressed == layout.view.id,
                                layout.view.frame,
                                layout.view.ring ? std::optional(layout.view.ring->getAsHex()) : std::nullopt,
                                layout.alpha};
    for (const auto &[id, previous] : m_last) {
        const auto current = next.find(id);
        if (force || current == next.end() || current->second != previous)
            g_pHyprRenderer->damageBox(previous.box.copy().expand(DAMAGE_MARGIN));
    }
    for (const auto &[id, current] : next) {
        const auto previous = m_last.find(id);
        if (force || previous == m_last.end() || previous->second != current)
            g_pHyprRenderer->damageBox(current.box.copy().expand(DAMAGE_MARGIN));
    }
    m_last = std::move(next);
}
void CardFrames::stage(eRenderStage stage) {
    if (stage == RENDER_PRE_WINDOWS) {
        m_layouts = layouts();
        m_rendered.clear();
        m_rendering = true;
    } else if (stage == RENDER_POST_WINDOWS)
        m_rendering = false;
    else if (stage == RENDER_POST_WINDOW && m_rendering) {
        const auto window = g_pHyprRenderer->m_renderData.currentWindow.lock();
        for (const auto &layout : m_layouts)
            if (layout.anchor == window && m_rendered.insert(layout.view.id).second)
                paint(layout);
    }
}
void CardFrames::paint(const Layout &layout) {
    const auto monitor = g_pHyprRenderer->m_renderData.pMonitor;
    if (!monitor || !layout.anchor)
        return;
    static auto active = CConfigValue<Config::IComplexConfigValue>("general:col.active_border");
    static auto inactive = CConfigValue<Config::IComplexConfigValue>("general:col.inactive_border");
    static auto width = CConfigValue<Config::INTEGER>("general:border_size");
    static auto textColor = CConfigValue<Config::INTEGER>("group:groupbar:text_color");
    static auto font = CConfigValue<Config::STRING>("group:groupbar:font_family");
    const auto color = CHyprColor(*textColor).stripA();
    const auto fill = controlFill(color);
    const auto scale = monitor->m_scale;
    const auto local = [&](CBox box) { return box.translate(-monitor->m_position).scale(scale).round(); };
    PaintData data;
    data.frame = layout.view.frame;
    data.roundingPower = layout.anchor->roundingPower();
    data.alpha = layout.alpha;
    if (layout.view.ring) {
        // Full strength on the focused card, quieter elsewhere, so the ring
        // marks card membership without competing with the focus border.
        data.ringColor = Config::CGradientValueData(
            layout.view.ring->modifyA(layout.focused ? 1.F : .55F));
        data.ringWidth = std::clamp<int>(*width, 2, RING_MAX);
        data.ring = local(layout.box.copy().expand(RING_GAP));
        data.ringRound = std::lround(
            (layout.anchor->rounding() + layout.anchor->getRealBorderSize() + RING_GAP) * scale);
    }
    if (!data.frame) {
        g_pHyprRenderer->m_renderPass.add(makeUnique<CardFramePass>(
            std::move(data), layout.box.copy().expand(DAMAGE_MARGIN).translate(-monitor->m_position)));
        return;
    }
    data.width = std::clamp<int>(*width + 1, 2, 6);
    data.round =
        std::lround(std::max(0.F, layout.anchor->rounding() + layout.anchor->getRealBorderSize() - data.width) * scale);
    data.controlRound = std::lround(std::min(6. * scale, double(data.round)));
    data.controlInset = std::lround(scale);
    data.box = local(layout.box.copy().expand(-data.width));
    data.border = *static_cast<Config::CGradientValueData *>((layout.focused ? active : inactive).ptr());
    data.label = layout.label.empty() ? CBox{} : local(layout.label);
    data.button = local(layout.button);
    data.focusPane = layout.focusPane.empty() ? CBox{} : local(layout.focusPane);
    data.focusWidth = layout.focusWidth;
    data.focusRound = std::lround(layout.focusRound * scale);
    data.fill = fill;
    data.buttonFill = fill;
    if (m_hovered == layout.view.id || m_pressed == layout.view.id) {
        float weight = m_pressed == layout.view.id ? .22F : .15F;
        const auto mix = [&](float w) {
            return CHyprColor(fill.r * (1 - w) + color.r * w, fill.g * (1 - w) + color.g * w,
                              fill.b * (1 - w) + color.b * w, 1.F);
        };
        while (weight > .005F && contrast(color, mix(weight)) < 4.5)
            weight *= .5F;
        data.buttonFill = mix(weight);
    }
    const auto text = [&](const std::string &value, CBox box, CBox &out) {
        const auto key = value + std::format("/{}/{}/{}/{}", fontSize(), scale, color.getAsHex(), *font);
        auto it = m_textures.find(key);
        if (it == m_textures.end()) {
            if (m_textures.size() > 64)
                m_textures.clear();
            it = m_textures
                     .emplace(key,
                              g_pHyprRenderer->renderText(value, color, std::lround(fontSize() * scale), false, *font))
                     .first;
        }
        if (it->second) {
            auto size = it->second->m_size;
            const double fit = std::min(1., std::min((box.w - 12 * scale) / size.x, (box.h - 4 * scale) / size.y));
            size *= std::max(.1, fit);
            out = CBox{box.pos() + (box.size() - size) / 2, size}.round();
        }
        return it->second;
    };
    if (!data.label.empty())
        data.labelTexture = text(layout.text, data.label, data.labelText);
    data.buttonTexture = text(layout.view.unfolded ? "Fold" : "Flip", data.button, data.buttonText);
    g_pHyprRenderer->m_renderPass.add(
        makeUnique<CardFramePass>(std::move(data), layout.box.copy().expand(DAMAGE_MARGIN).translate(-monitor->m_position)));
}
std::optional<uint64_t> CardFrames::hit(Vector2D pos) const {
    // Layer menus, popups and locks retain priority over compositor controls.
    const auto surface = CWLSurface::fromResource(g_pSeatManager->m_state.pointerFocus.lock());
    const auto view = surface ? surface->view() : nullptr;
    if (view && (view->type() == VIEW_TYPE_LAYER_SURFACE || view->type() == VIEW_TYPE_POPUP ||
                 view->type() == VIEW_TYPE_LOCK_SCREEN)) {
        const auto box = view->logicalBox();
        if (box && box->containsPoint(pos))
            return {};
    }
    auto candidates = layouts();
    for (auto it = candidates.rbegin(); it != candidates.rend(); ++it) {
        if (!it->button.containsPoint(pos))
            continue;
        // A later floating window must be able to cover the card's controls.
        bool above = false;
        for (const auto &w : Desktop::windowState()->windows()) {
            if (w == it->anchor) {
                above = true;
                continue;
            }
            const bool focusedTileAbove = !it->anchor->m_isFloating && w == Desktop::focusState()->window();
            if ((!above && !(w->m_isFloating && !it->anchor->m_isFloating) && !focusedTileAbove) || !shown(w) ||
                std::ranges::find(it->view.windows, w) != it->view.windows.end())
                continue;
            auto box = w->getFullWindowBoundingBox();
            if (w->m_workspace && !w->m_pinned)
                box.translate(w->m_workspace->m_renderOffset->value());
            if (box.containsPoint(pos))
                return {};
        }
        return it->view.id;
    }
    return {};
}
bool CardFrames::button(const IPointer::SButtonEvent &event, Event::SCallbackInfo &info) {
    if (event.button != BTN_LEFT)
        return false;
    if (event.state == WL_POINTER_BUTTON_STATE_RELEASED && m_eatRelease) {
        const auto pressed = m_pressed;
        m_pressed.reset();
        m_eatRelease = false;
        info.cancelled = true;
        const auto over = hit(g_pInputManager->getMouseCoordsInternal());
        if (pressed && !m_dragged && over == pressed && !busy() && !g_pInputManager->getModsFromAllKBs())
            m_activate(*pressed);
        refresh();
        return true;
    }
    if (info.cancelled || event.state != WL_POINTER_BUTTON_STATE_PRESSED || busy() ||
        g_pInputManager->getModsFromAllKBs())
        return false;
    const auto pos = g_pInputManager->getMouseCoordsInternal();
    if (const auto over = hit(pos)) {
        m_pressed = over;
        m_eatRelease = true;
        m_pressPosition = pos;
        m_dragged = false;
        info.cancelled = true;
        refresh();
        return true;
    }
    return false;
}
void CardFrames::clearInput() {
    m_pressed.reset();
    m_hovered.reset();
    m_dragged = true;
}
std::string CardFrames::status() {
    std::string result = "[";
    for (const auto &layout : layouts()) {
        if (!layout.view.frame)
            continue;
        if (result.size() > 1)
            result += ',';
        result += std::format(
            "{{\"id\":{},\"box\":[{},{},{},{}],\"button\":[{},{},{},{}],\"active\":{},\"unfolded\":{}}}",
            layout.view.id, layout.box.x, layout.box.y, layout.box.w, layout.box.h, layout.button.x, layout.button.y,
            layout.button.w, layout.button.h, layout.view.active, layout.view.unfolded ? "true" : "false");
    }
    return result + ']';
}
std::string CardFrames::rings() {
    std::string result = "[";
    for (const auto &layout : layouts()) {
        if (!layout.view.ring)
            continue;
        if (result.size() > 1)
            result += ',';
        const auto box = layout.box.copy().expand(RING_GAP);
        result += std::format("{{\"id\":{},\"box\":[{},{},{},{}],\"color\":\"#{:06X}\",\"focused\":{}}}",
                              layout.view.id, box.x, box.y, box.w, box.h, layout.view.ring->getAsHex() & 0xffffff,
                              layout.focused ? "true" : "false");
    }
    return result + ']';
}
} // namespace Hyprflip
