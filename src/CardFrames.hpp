// SPDX-License-Identifier: MIT
#pragma once
#include <functional>
#include <hyprland/src/devices/IPointer.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <map>
#include <optional>
#include <set>

namespace Hyprflip {
struct CardFrameView {
    uint64_t id = 0;
    unsigned active = 0;
    bool unfolded = false;
    bool animating = false;
    // Frame draws the shared outline and controls; the accent ring surrounds
    // the card in either appearance. A card with neither is not listed.
    bool frame = false;
    std::optional<CHyprColor> ring;
    unsigned count[2]{};
    std::vector<PHLWINDOWREF> windows;
};

class CardFrames {
  public:
    using Source = std::function<std::vector<CardFrameView>()>;
    using Activate = std::function<void(uint64_t)>;
    CardFrames(Source source, Activate activate);
    ~CardFrames();
    static double headerHeight();
    void nativeHeaders(const std::vector<PHLWINDOWREF> &windows);
    bool button(const IPointer::SButtonEvent &, Event::SCallbackInfo &);
    void clearInput();
    void refresh(bool force = false);
    std::string status();
    std::string rings();

  private:
    struct Layout {
        CardFrameView view;
        CBox box, button, label, focusPane;
        PHLWINDOWREF anchor;
        std::string text;
        bool focused = false;
        float alpha = 1;
        float focusRound = 0;
        int focusWidth = 0;
    };
    std::vector<Layout> layouts() const;
    std::optional<uint64_t> hit(Vector2D position) const;
    void stage(eRenderStage);
    void paint(const Layout &);
    Source m_source;
    Activate m_activate;
    std::vector<CHyprSignalListener> m_listeners;
    std::vector<Layout> m_layouts;
    std::vector<PHLWINDOWREF> m_headerWindows;
    std::set<uint64_t> m_rendered;
    struct DamageState {
        CBox box;
        CBox focusPane;
        std::string text;
        bool focused, hovered, pressed, frame;
        std::optional<uint32_t> ring;
        float alpha;
        bool operator==(const DamageState &) const = default;
    };
    std::map<uint64_t, DamageState> m_last;
    std::map<std::string, SP<Render::ITexture>> m_textures;
    std::optional<uint64_t> m_pressed, m_hovered;
    Vector2D m_pressPosition;
    bool m_rendering = false, m_dragged = false, m_eatRelease = false;
};
} // namespace Hyprflip
