// SPDX-License-Identifier: MIT
#include "FaceSwitcher.hpp"
#include "CardFrames.hpp"
#include "FlipTransformer.hpp"
#include <algorithm>
#include <cmath>
#include <format>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/pass/PassElement.hpp>

namespace Hyprflip {
namespace {
constexpr double PAD = 14, GAP = 8, MAX_TILE_W = 320, MAX_TILE_H = 240, FONT = 14;
struct TileData {
    SP<Render::IFramebuffer> face;
    CBox box, label;
    SP<Render::ITexture> text;
    bool selected = false, active = false;
};
struct PassData {
    CBox panel, captured;
    std::vector<TileData> tiles;
    Config::CGradientValueData border;
    std::shared_ptr<FlipShader> shader;
    int round = 12, tileRound = 8, borderWidth = 3;
};
// Owns everything it draws; nothing points back at the switcher.
class SwitcherPass final : public IPassElement {
  public:
    SwitcherPass(PassData data, CBox bounds) : data(std::move(data)), bounds(bounds) {}
    std::vector<UP<IPassElement>> draw() override {
        auto &gl = Render::GL::g_pHyprOpenGL;
        gl->renderRect(data.panel, CHyprColor(0.07, 0.075, 0.09, 0.9), {.round = data.round});
        for (const auto &tile : data.tiles) {
            if (tile.face)
                data.shader->drawPreview(tile.face, data.captured, tile.box, 1.F, data.tileRound);
            else
                gl->renderRect(tile.box, CHyprColor(1, 1, 1, .08), {.round = data.tileRound});
            if (tile.selected)
                gl->renderBorder(tile.box.copy().expand(data.borderWidth + 1), data.border,
                                 {.round = data.tileRound + data.borderWidth + 1, .borderSize = data.borderWidth});
            else
                gl->renderBorder(tile.box, Config::CGradientValueData(CHyprColor(1, 1, 1, .14)),
                                 {.round = data.tileRound, .borderSize = 1});
            if (tile.text) {
                Render::GL::CHyprOpenGLImpl::STextureRenderData textureData{};
                textureData.a = tile.selected ? 1.F : .72F;
                gl->renderTexture(tile.text, tile.label, textureData);
            }
        }
        return {};
    }
    bool needsLiveBlur() override { return false; }
    bool needsPrecomputeBlur() override { return false; }
    const char *passName() override { return "HyprflipFaceSwitcherPass"; }
    ePassElementType type() override { return EK_CUSTOM; }
    std::optional<CBox> boundingBox() override { return bounds; }
    bool disableSimplification() override { return true; }
    PassData data;
    CBox bounds;
};
} // namespace

FaceSwitcher::FaceSwitcher(std::shared_ptr<FlipShader> shader) : m_shader(std::move(shader)) {
    m_listeners.emplace_back(Event::bus()->m_events.render.stage.listen([this](eRenderStage stage) { this->stage(stage); }));
}
FaceSwitcher::~FaceSwitcher() {
    m_listeners.clear();
    hide();
}
void FaceSwitcher::show(SwitcherView view) {
    damage();
    m_view = std::move(view);
    damage();
}
void FaceSwitcher::select(unsigned face) {
    if (!m_view || face >= m_view->count || face == m_view->selected)
        return;
    m_view->selected = face;
    damage();
}
void FaceSwitcher::hide() {
    damage();
    m_view.reset();
    m_textures.clear();
}
void FaceSwitcher::damage() {
    if (m_damaged) {
        g_pHyprRenderer->damageBox(*m_damaged);
        m_damaged.reset();
    }
    if (!m_view)
        return;
    const auto box = layout().panel.copy().expand(8);
    g_pHyprRenderer->damageBox(box);
    m_damaged = box;
    if (auto monitor = m_view->monitor.lock())
        monitor->scheduleFrame();
}
FaceSwitcher::Layout FaceSwitcher::layout() const {
    Layout out;
    if (!m_view || !m_view->count)
        return out;
    const auto monitor = m_view->monitor.lock();
    const CBox screen = monitor ? monitor->logicalBox() : m_view->card;
    const double n = m_view->count, aspect = std::max(.2, m_view->card.h / std::max(1.0, m_view->card.w));
    double w = std::min(MAX_TILE_W, (screen.w * .9 - PAD * (n + 1)) / n);
    w = std::min(w, MAX_TILE_H / aspect);
    const double h = w * aspect, label = FONT + 10;
    out.panel = CBox{0, 0, n * w + (n + 1) * PAD, PAD + h + GAP + label + PAD / 2};
    Vector2D centre = m_view->card.middle();
    out.panel.x = std::clamp(centre.x - out.panel.w / 2, screen.x, screen.x + screen.w - out.panel.w);
    out.panel.y = std::clamp(centre.y - out.panel.h / 2, screen.y, screen.y + screen.h - out.panel.h);
    out.panel.round();
    for (unsigned i = 0; i < m_view->count; ++i) {
        const double x = out.panel.x + PAD + i * (w + PAD);
        out.tiles.push_back({CBox{x, out.panel.y + PAD, w, h}.round(), CBox{x, out.panel.y + PAD + h + GAP, w, label}});
    }
    out.scale = monitor ? monitor->m_scale : 1;
    return out;
}
std::optional<unsigned> FaceSwitcher::hit(Vector2D position) const {
    const auto l = layout();
    for (unsigned i = 0; i < l.tiles.size(); ++i)
        if (l.tiles[i].box.copy().expand(PAD / 2).containsPoint(position))
            return i;
    return std::nullopt;
}
std::string FaceSwitcher::status() const {
    if (!m_view)
        return "{\"open\":false}";
    const auto l = layout();
    return std::format("{{\"open\":true,\"card\":{},\"selected\":{},\"active\":{},\"faces\":{},\"previews\":{},"
                       "\"panel\":[{},{},{},{}]}}",
                       m_view->pairID, m_view->selected, m_view->active, m_view->count,
                       std::ranges::count_if(m_view->faces, [](const auto &f) { return bool(f); }), l.panel.x,
                       l.panel.y, l.panel.w, l.panel.h);
}
void FaceSwitcher::stage(eRenderStage stage) {
    if (stage != RENDER_POST_WINDOWS || !m_view)
        return;
    const auto monitor = g_pHyprRenderer->m_renderData.pMonitor.lock();
    if (!monitor || monitor != m_view->monitor.lock())
        return;
    static auto activeBorder = CConfigValue<Config::IComplexConfigValue>("general:col.active_border");
    static auto font = CConfigValue<Config::STRING>("group:groupbar:font_family");
    const auto l = layout();
    const double scale = monitor->m_scale;
    const auto local = [&](CBox box) { return box.translate(-monitor->m_position).scale(scale).round(); };
    PassData data;
    data.panel = local(l.panel);
    data.captured = m_view->captured;
    data.border = *static_cast<Config::CGradientValueData *>(activeBorder.ptr());
    data.shader = m_shader;
    data.round = std::lround(12 * scale);
    data.tileRound = std::lround(8 * scale);
    data.borderWidth = std::max(2L, std::lround(2 * scale));
    for (unsigned i = 0; i < m_view->count; ++i) {
        TileData tile;
        tile.face = i < m_view->faces.size() ? m_view->faces[i] : nullptr;
        tile.box = local(l.tiles[i].box);
        tile.selected = i == m_view->selected;
        tile.active = i == m_view->active;
        const auto value = std::format("{}  {}{}", i + 1, faceName(i), tile.active ? "  ·  now" : "");
        const auto key = std::format("{}/{}/{}", value, scale, *font);
        auto it = m_textures.find(key);
        if (it == m_textures.end())
            it = m_textures
                     .emplace(key, g_pHyprRenderer->renderText(value, CHyprColor(.93, .94, .96, 1.),
                                                               std::lround(FONT * scale), false, *font))
                     .first;
        tile.text = it->second;
        if (tile.text) {
            const auto area = local(l.tiles[i].label);
            auto size = tile.text->m_size;
            size *= std::min(1., area.w / std::max(1., size.x));
            tile.label = CBox{area.pos() + (area.size() - size) / 2, size}.round();
        }
        data.tiles.push_back(std::move(tile));
    }
    const auto bounds = l.panel.copy().expand(8).translate(-monitor->m_position);
    g_pHyprRenderer->m_renderPass.add(makeUnique<SwitcherPass>(std::move(data), bounds));
}
} // namespace Hyprflip
