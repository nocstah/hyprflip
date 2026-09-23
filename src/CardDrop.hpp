// SPDX-License-Identifier: MIT
#pragma once
#include <functional>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <optional>
#include <map>

namespace Hyprflip {
struct CardDropOffer {
    uint64_t id = 0;
    unsigned side = 0, count = 0;
    bool vertical = false;
    CBox box;
    std::vector<PHLWINDOWREF> members;
    std::string refusal;
};

// Observes native window moves; never takes over the compositor's drag state.
// The controller receives a drop after Hyprland has finished the release.
class CardDrop {
  public:
    using Source = std::function<std::vector<CardDropOffer>(PHLWINDOW)>;
    using Commit = std::function<void(PHLWINDOWREF, CardDropOffer)>;
    CardDrop(Source, Commit);
    ~CardDrop();
    void clear();
    std::string status() const;

  private:
    struct Target {
        CardDropOffer offer;
        CBox zone, preview;
        std::string text;
        bool hovered = false;
    };
    PHLWINDOW dragged() const;
    void refresh();
    void paint();
    std::vector<Target> targets(PHLWINDOW) const;
    Source m_source;
    Commit m_commit;
    std::vector<CHyprSignalListener> m_listeners;
    std::vector<Target> m_targets;
    PHLWINDOWREF m_cancelled, m_seen;
    std::map<std::string, SP<Render::ITexture>> m_textures;
};
} // namespace Hyprflip
