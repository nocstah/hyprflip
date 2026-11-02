// SPDX-License-Identifier: MIT
#include "Reveal.hpp"
#include <algorithm>
#include <cmath>
#include <hyprland/src/animation/AnimationManager.hpp>
#include <hyprland/src/config/shared/animation/AnimationTree.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/state/FadingOutState.hpp>
#include <hyprland/src/desktop/state/WindowFadeout.hpp>
#include <hyprland/src/desktop/view/WLSurface.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <optional>

namespace Hyprflip::Reveal {
namespace {
using namespace Desktop::View;
using AnimConfig = Hyprutils::Animation::SAnimationPropertyConfig;

struct Active {
    PHLWINDOWREF window;
    SP<AnimConfig> in, fade;  // set when the speed is the plugin's own: animated variables hold these weakly
    bool steady = false;      // came in over a picture of a card's header: its card's frame need not move or fade
    bool tookBlur = false;    // no_blur is ours until the fade ends
    std::optional<bool> blur; // the set_prop value it had before ours, which goes back
};
std::vector<Active> active;

SP<AnimConfig> tree(const char *leaf) { return Config::animationTree()->getAnimationPropertyConfig(leaf); }

// The user's animation at another speed. Their curve and style, their config untouched.
SP<AnimConfig> scaled(const char *leaf, float speed) {
    const auto base = tree(leaf);
    if (speed == 1.F)
        return nullptr;
    const auto values = base->pValues.lock();
    if (!values)
        return nullptr;
    auto own = makeShared<AnimConfig>();
    own->overridden = true;
    own->internalBezier = values->internalBezier;
    own->internalStyle = values->internalStyle;
    own->internalSpeed = values->internalSpeed * speed;
    own->internalEnabled = values->internalEnabled;
    own->pValues = own;
    own->pParentAnimation = base;
    return own;
}

// A window fading has blur behind it even if it is opaque, and that blur is of the wallpaper, not of what is under the
// window. Over a picture that shows as wallpaper in the crossfade, so an opaque window does without it until the fade
// is over.
bool solid(const PHLWINDOW &w) {
    const auto surface = w->wlSurface() ? w->wlSurface()->resource() : nullptr;
    if (!surface)
        return false;
    const auto extents = surface->m_current.opaque.getExtents();
    // In surface coordinates, so against the surface's size: Chromium's buffer can be larger, cut down with a viewport.
    if (extents.w >= surface->m_current.size.x && extents.h >= surface->m_current.size.y)
        return true;
    return surface->m_current.texture && surface->m_current.texture->m_opaque;
}

void handBack(const Active &entry, const PHLWINDOW &w) {
    if (entry.tookBlur) {
        auto &noBlur = w->m_ruleApplicator->noBlur();
        // Omaglass writes this property too. If it wrote during the fade, its word stands.
        if (noBlur.hasValue() && noBlur.getPriority() == Desktop::Types::PRIORITY_SET_PROP && noBlur.value()) {
            if (entry.blur)
                noBlur.set(*entry.blur, Desktop::Types::PRIORITY_SET_PROP);
            else
                noBlur.unset(Desktop::Types::PRIORITY_SET_PROP);
        }
    }
    const auto move = tree("windowsMove");
    w->positionAnimation()->setConfig(move);
    w->sizeAnimation()->setConfig(move);
    w->alpha(WINDOW_ALPHA_FADE)->setConfig(tree("fadeIn"));
    w->m_animatingIn = false;
    w->resetMotionBlur();
}

bool animating(const PHLWINDOW &w) {
    return w->positionAnimation()->isBeingAnimated() || w->sizeAnimation()->isBeingAnimated() ||
           w->alpha(WINDOW_ALPHA_FADE)->isBeingAnimated();
}

// A still picture under every window. Its alpha follows the window that comes in over it, so nothing but that window's
// own fade changes what shows in the tile.
class Picture final : public Desktop::IFadeout {
  public:
    static SP<Picture> create(PHLWINDOW window, SP<Render::IFramebuffer> snapshot, Card card, int generation) {
        const auto monitor = window->m_monitor.lock();
        if (!monitor || !snapshot)
            return nullptr;
        auto picture = SP<Picture>(new Picture());
        picture->m_monitor = monitor;
        picture->m_framebuffer = snapshot;
        picture->m_box = window->getFullWindowBoundingBox();
        picture->m_box.y -= card.extraTop;
        picture->m_box.h += card.extraTop;
        picture->m_framed = card.extraTop > 0;
        picture->m_generation = generation;
        Animation::mgr()->createAnimation(window->position(IGeometric::GEOMETRIC_CURRENT), picture->m_realPosition,
                                          tree("windowsOut"), AVARDAMAGE_NONE);
        Animation::mgr()->createAnimation(window->size(IGeometric::GEOMETRIC_CURRENT), picture->m_realSize,
                                          tree("windowsOut"), AVARDAMAGE_NONE);
        return picture;
    }
    PHLMONITORREF monitor() const override { return m_monitor; }
    Desktop::eFadeoutPlane plane() const override { return Desktop::FADEOUT_PLANE_LAYER_BOTTOM; }
    int zIndex() const override { return 0; }
    CBox renderBox() const override {
        const auto monitor = m_monitor.lock();
        return monitor ? CBox{{}, monitor->m_transformedSize} : CBox{};
    }
    float alpha() const override {
        if (m_gone || m_monitor.expired())
            return 0.F;
        const auto over = m_over.lock();
        if (!over || !over->m_workspace || !over->m_workspace->isVisible() ||
            !over->alpha(WINDOW_ALPHA_FADE)->isBeingAnimated())
            return 0.F;
        // Solid until the page over it has come in, so no wallpaper shows through the fade.
        return std::clamp((1.F - over->alphaValue(WINDOW_ALPHA_FADE)) * 10.F, 0.F, 1.F);
    }
    bool done() const override { return alpha() == 0.F; }
    void over(PHLWINDOW window) { m_over = window; }
    bool waiting() const { return !m_over && !m_gone; }
    bool alive() const { return !m_gone; }
    bool framed() const { return m_framed; }
    int generation() const { return m_generation; }
    void gone() { m_gone = true; }
    void damage() const {
        g_pHyprRenderer->damageBox(m_box);
        if (const auto monitor = m_monitor.lock())
            monitor->scheduleFrame();
    }

  private:
    Picture() = default;
    PHLMONITORREF m_monitor;
    PHLWINDOWREF m_over;
    CBox m_box;
    bool m_gone = false, m_framed = false;
    int m_generation = 0;
};
std::vector<SP<Picture>> pictures;
int generation = 0;

// Takes pictures out of Hyprland's list as well as ours. Hyprland can only sweep a whole monitor's finished fadeouts,
// or clear everything, which would cut windows that are closing. A picture left in its list crashes it once the plugin
// is gone, so each comes out here, by itself, whatever became of its monitor.
template <typename Which> void drop(Which which) {
    if (std::ranges::none_of(pictures, which))
        return;
    g_pHyprRenderer->glBackend()->makeEGLCurrent(); // a framebuffer's last owner frees it
    auto &fadeouts = const_cast<std::vector<SP<Desktop::IFadeout>> &>(Desktop::fadingOutState()->fadeouts());
    std::erase_if(pictures, [&](const SP<Picture> &picture) {
        if (!which(picture))
            return false;
        std::erase_if(fadeouts, [&](const SP<Desktop::IFadeout> &fadeout) {
            return fadeout.get() == static_cast<Desktop::IFadeout *>(picture.get());
        });
        return true;
    });
}

bool drawable(const PHLWINDOW &w) {
    return w && w->m_isMapped && !w->isHidden() && w->m_workspace && w->m_workspace->isVisible() &&
           g_pHyprRenderer->shouldRenderWindow(w);
}
} // namespace

bool reveal(const std::vector<PHLWINDOW> &windows, float speed, Card card) {
    std::vector<PHLWINDOW> shown;
    for (const auto &w : windows)
        if (w && w->m_isMapped && w->m_workspace && w->m_workspace->isVisible())
            shown.push_back(w);
    if (shown.empty())
        return false;
    const auto in = scaled("windowsIn", speed), fade = scaled("fadeIn", speed);
    const auto under = [&](const PHLWINDOW &w, bool framed) {
        return std::ranges::any_of(pictures, [&](const SP<Picture> &p) {
            return p->alive() && p->monitor() == w->m_monitor && (p->framed() || !framed);
        });
    };
    Vector2D center;
    if (card.whole) {
        CBox all = shown[0]->geometricBox(IGeometric::GEOMETRIC_GOAL);
        for (const auto &w : shown) {
            const auto box = w->geometricBox(IGeometric::GEOMETRIC_GOAL);
            const double x = std::min(all.x, box.x), y = std::min(all.y, box.y);
            all = {x, y, std::max(all.x + all.w, box.x + box.w) - x, std::max(all.y + all.h, box.y + box.h) - y};
        }
        center = {all.x + all.w / 2, all.y - card.extraTop + (all.h + card.extraTop) / 2};
    }
    for (const auto &w : shown) {
        auto &rules = *w->m_ruleApplicator;
        // The swap's own no_anim goes; a window rule of the user's stays and wins.
        rules.noAnim().unset(Desktop::Types::PRIORITY_SET_PROP);
        if (rules.noAnim().valueOr(false))
            continue;
        // moveWindowToWorkspace started this for a window coming from a hidden workspace: a second fade over ours.
        w->alpha(WINDOW_ALPHA_MOVE_FROM_WORKSPACE)->setValueAndWarp(1.F);
        const auto windowsIn = in ? in : tree("windowsIn");
        w->positionAnimation()->setConfig(windowsIn);
        w->sizeAnimation()->setConfig(windowsIn);
        w->alpha(WINDOW_ALPHA_FADE)->setConfig(fade ? fade : tree("fadeIn"));
        w->m_animatingIn = true; // the surface scales with the box during an in animation, instead of being cropped
        // A frame stays still only over a header: over a plain window's picture, it comes in with its panes.
        Active entry{.window = w,
                     .in = in,
                     .fade = fade,
                     .steady = card.extraTop > 0 && under(w, true),
                     .tookBlur = false,
                     .blur = {}};
        // Coming back before its last reveal ended: what no_blur had before is still that reveal's to give back.
        const auto previous = std::ranges::find_if(active, [&](const Active &a) { return a.window.lock() == w; });
        if (previous != active.end()) {
            entry.tookBlur = previous->tookBlur;
            entry.blur = previous->blur;
        }
        auto &noBlur = rules.noBlur();
        if (!entry.tookBlur && under(w, false) && solid(w) && !noBlur.valueOr(false)) {
            entry.tookBlur = true;
            if (noBlur.hasValue() && noBlur.getPriority() == Desktop::Types::PRIORITY_SET_PROP)
                entry.blur = noBlur.value();
            noBlur.set(true, Desktop::Types::PRIORITY_SET_PROP);
        }
        auto context = w->m_animationController.animateIn();
        if (card.whole && context.size.to.x > 0 && context.size.to.y > 0) {
            const Vector2D factor = {context.size.from.x / context.size.to.x, context.size.from.y / context.size.to.y};
            if (factor != Vector2D{1, 1}) {
                context.pos.from = center + (context.pos.to - center) * factor;
                context.size.from = context.size.to * factor;
            }
        }
        w->m_animationController.apply(context);
        if (previous != active.end())
            active.erase(previous);
        active.push_back(std::move(entry));
    }
    // Every picture still up stays under what comes in now, so switching on during an animation never shows the
    // wallpaper.
    for (const auto &picture : pictures) {
        const auto over =
            std::ranges::find_if(shown, [&](const PHLWINDOW &w) { return picture->monitor() == w->m_monitor; });
        if (picture->alive() && over != shown.end())
            picture->over(*over);
    }
    return true;
}

bool leave(const std::vector<PHLWINDOW> &windows) {
    bool any = false;
    g_pHyprRenderer->glBackend()->makeEGLCurrent();
    for (const auto &w : windows) {
        if (!drawable(w))
            continue;
        const auto snapshot = g_pHyprRenderer->makeSnapshotFB(w);
        if (!snapshot)
            continue;
        // the style comes from the variable's config, as Hyprland's own unmap says
        const auto out = tree("windowsOut"), move = tree("windowsMove");
        w->positionAnimation()->setConfig(out);
        w->sizeAnimation()->setConfig(out);
        const float alpha = w->alphaValue(WINDOW_ALPHA_FADE) * w->alphaValue(WINDOW_ALPHA_FULLSCREEN) *
                            w->alphaValue(WINDOW_ALPHA_LAYOUT);
        Desktop::fadingOutState()->add(Desktop::CWindowFadeout::create(w, snapshot, alpha));
        w->positionAnimation()->setConfig(move);
        w->sizeAnimation()->setConfig(move);
        any = true;
    }
    return any;
}

bool hold(const std::vector<PHLWINDOW> &windows, Card card) {
    bool any = false;
    // The oldest pictures are solid and the newest show what is on screen now. Rapid switching needs no more than
    // those: each is a monitor-sized buffer. Holds with no reveal yet belong to one request, whatever number of cards
    // it leaves.
    if (std::ranges::none_of(pictures, [](const SP<Picture> &p) { return p->waiting(); })) {
        ++generation;
        const auto oldest = std::ranges::find_if(pictures, [](const SP<Picture> &p) { return p->alive(); });
        if (oldest != pictures.end())
            for (const auto &picture : pictures)
                if (picture->generation() != (*oldest)->generation())
                    picture->gone();
    }
    g_pHyprRenderer->glBackend()->makeEGLCurrent();
    for (const auto &w : windows) {
        if (!drawable(w))
            continue;
        const auto picture = Picture::create(w, g_pHyprRenderer->makeSnapshotFB(w), card, generation);
        if (!picture)
            continue;
        pictures.push_back(picture);
        Desktop::fadingOutState()->add(picture);
        // Even with no reveal to follow: the next frame takes it away.
        picture->damage();
        any = true;
    }
    return any;
}

bool steady(const PHLWINDOW &w) {
    return std::ranges::any_of(active, [&](const Active &a) { return a.steady && a.window.lock() == w; });
}

void frame() {
    std::erase_if(active, [](const Active &a) {
        const auto w = a.window.lock();
        if (!w)
            return true;
        if (animating(w))
            return false;
        handBack(a, w);
        return true;
    });
    for (const auto &picture : pictures) {
        // nothing came in over it within the request that made it
        if (picture->waiting())
            picture->gone();
        picture->damage();
    }
    drop([](const SP<Picture> &picture) { return picture->done(); });
}

void monitorGone(const PHLMONITOR &monitor) {
    drop([&](const SP<Picture> &picture) { return picture->monitor() == monitor; });
}

void shutdown() {
    for (const auto &a : active)
        if (const auto w = a.window.lock())
            handBack(a, w);
    active.clear();
    for (const auto &picture : pictures)
        picture->damage();
    drop([](const SP<Picture> &) { return true; });
}
} // namespace Hyprflip::Reveal
