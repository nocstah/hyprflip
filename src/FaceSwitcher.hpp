// SPDX-License-Identifier: MIT
#pragma once
#include "ContainerABI.hpp"
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace Hyprflip {
class FlipShader;
// The strip of face previews shown while the flip key is held on a card
// with three or more faces. It only draws and hit-tests; the controller
// decides when it opens, what is selected and what a pick does.
struct SwitcherView {
    uint64_t pairID = 0;
    PHLMONITORREF monitor;
    CBox card;                // the card, in layout coordinates
    CBox captured;            // the card in the snapshots, in monitor pixels
    unsigned count = 0, active = 0, selected = 0;
    std::vector<SP<Render::IFramebuffer>> faces; // a snapshot per face; may be empty
    std::vector<std::string> names;
};
class FaceSwitcher {
  public:
    explicit FaceSwitcher(std::shared_ptr<FlipShader> shader);
    ~FaceSwitcher();
    void show(SwitcherView view);
    void select(unsigned face);
    void hide();
    bool open() const { return m_view.has_value(); }
    std::optional<unsigned> hit(Vector2D position) const;
    std::string status() const;

  private:
    struct Tile {
        CBox box, label;
    };
    struct Layout {
        CBox panel;
        std::vector<Tile> tiles;
        double scale = 1;
    };
    Layout layout() const;
    void stage(eRenderStage stage);
    void damage();
    std::shared_ptr<FlipShader> m_shader;
    std::optional<SwitcherView> m_view;
    std::optional<CBox> m_damaged;
    std::vector<CHyprSignalListener> m_listeners;
    std::map<std::string, SP<Render::ITexture>> m_textures;
};
} // namespace Hyprflip
