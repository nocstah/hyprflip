// SPDX-License-Identifier: MIT
#include "Reveal.hpp"
#include <algorithm>
#include <cmath>
#include <hyprland/src/animation/AnimationManager.hpp>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
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
#include <chrono>
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
    // A slide waits, the window unseen over the picture, until the app has drawn at its tile's size: one parked at
    // another size otherwise shows its old layout for a few frames, then reflows on the way in.
    std::optional<double> slideBy;
    std::chrono::steady_clock::time_point until{};
    bool still = false; // in place under pictures that go by themselves: never moved, hidden or faded here
};
std::vector<Active> active;
constexpr auto SLIDE_WAIT = std::chrono::milliseconds(200);
std::optional<double> lastWait;

bool waitingToSlide(const PHLWINDOW &w) {
    return std::ranges::any_of(active, [&](const Active &a) { return a.slideBy && a.window.lock() == w; });
}

// The app's last buffer matches the size it now has, give or take a pixel and the border.
bool drawnAtSize(const PHLWINDOW &w) {
    const auto surface = w->wlSurface() ? w->wlSurface()->resource() : nullptr;
    if (!surface)
        return true;
    const auto drawn = surface->m_current.size, size = w->sizeAnimation()->goal();
    return std::abs(drawn.x - size.x) <= 2 && std::abs(drawn.y - size.y) <= 2;
}

// Hyprland tells an app it may draw (its frame callbacks) as it draws that app, and a window waiting unseen is not
// drawn. An app that asked before it went out of sight, as one drawing every frame does, waits for that word before
// it draws at its new size: the word comes from here, each frame, while it waits.
void letDraw(const PHLWINDOW &w, std::chrono::steady_clock::time_point now) {
    if (const auto surface = w->wlSurface() ? w->wlSurface()->resource() : nullptr)
        surface->breadthfirst([now](SP<CWLSurfaceResource> s, const Vector2D &, void *) { s->frame(now); }, nullptr);
}

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
    if (entry.still && !entry.tookBlur)
        return;
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

// What a picture of a window that can be seen through needs under it to look as the window does: Hyprland's blur, as its
// own close animation gives it a closing window's picture (WindowFadeout.cpp's shouldBlurWindow), or the glass Hyprglass
// draws for the windows it tags, which blurs the wallpaper alone (it sets their no_blur, its glass being its own). A
// snapshot has neither, so without this the picture shows whatever is under it, sharp: the wallpaper, or the window it
// slides over.
std::optional<bool> backdrop(const PHLWINDOW &w) {
    static auto blur = CConfigValue<Config::INTEGER>("decoration:blur:enabled");
    if (!*blur || solid(w))
        return std::nullopt;
    auto &rules = *w->m_ruleApplicator;
    if (rules.m_tagKeeper.isTagged("hyprglass_enabled"))
        return true;
    if (rules.noBlur().valueOrDefault() || rules.RGBX().valueOrDefault() || w->opaque())
        return std::nullopt;
    if (const auto surface = w->wlSurface(); surface && surface->m_hasBackgroundEffect && surface->m_blurRegion.empty())
        return std::nullopt;
    return rules.xray().valueOr(false);
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
        picture->m_backdrop = backdrop(window);
        picture->m_rounding = window->rounding();
        picture->m_roundingPower = window->roundingPower();
        picture->m_window = window->getWindowMainSurfaceBox();
        Animation::mgr()->createAnimation(window->position(IGeometric::GEOMETRIC_CURRENT), picture->m_realPosition,
                                          tree("windowsOut"), AVARDAMAGE_NONE);
        Animation::mgr()->createAnimation(window->size(IGeometric::GEOMETRIC_CURRENT), picture->m_realSize,
                                          tree("windowsOut"), AVARDAMAGE_NONE);
        return picture;
    }
    PHLMONITORREF monitor() const override { return m_monitor; }
    // A still one is over the windows of its workspace, where it was taken: what it uncovers is under it.
    Desktop::eFadeoutPlane plane() const override {
        return m_still ? Desktop::FADEOUT_PLANE_WINDOW_FLOATING : Desktop::FADEOUT_PLANE_LAYER_BOTTOM;
    }
    int zIndex() const override { return 0; }
    CBox renderBox() const override { return renderBoxSlid(); }
    Desktop::SFadeoutRenderEffects effects() const override {
        auto effects = Desktop::IFadeout::effects();
        const auto monitor = m_monitor.lock();
        if (!m_backdrop || !monitor)
            return effects;
        effects.preBlur = Desktop::SFadeoutPreBlur{
            .box = CBox{m_window.x, m_window.y + offset(), m_window.w, m_window.h}
                       .translate(-monitor->m_position)
                       .scale(monitor->m_scale)
                       .round(),
            .round = static_cast<int>(m_rounding),
            .roundingPower = m_roundingPower,
            .xray = *m_backdrop,
            .alpha = std::sqrt(std::max(alpha(), 0.F)),
        };
        return effects;
    }
    CBox renderBoxSlid() const {
        const auto monitor = m_monitor.lock();
        if (!monitor)
            return {};
        return CBox{Vector2D{0., offset() * monitor->m_scale}, monitor->m_transformedSize};
    }
    // How far it is from where it was taken, in layout pixels.
    double offset() const {
        // Moves with what arrives, a fixed distance ahead of it: they go along together, and it is out when that is in.
        // A still one moves by itself, from where it was to its whole height and a gap away.
        double offset = 0;
        if (m_still) {
            if (m_started && m_away)
                offset = -m_sign * m_distance * m_away->value();
        } else if (const auto over = m_over.lock(); m_sign && over && !waitingToSlide(over)) {
            const auto &position = over->positionAnimation();
            offset = position->value().y - position->goal().y - m_sign * m_distance;
        }
        return offset;
    }
    float alpha() const override {
        if (m_gone || m_monitor.expired())
            return 0.F;
        const auto over = m_over.lock();
        if (m_still) {
            if (!over || !over->m_workspace || !over->m_workspace->isVisible())
                return 0.F;
            if (!m_started)
                return 1.F;
            const float progress = m_away->value();
            if (progress >= 1.F && !m_away->isBeingAnimated())
                return 0.F;
            return m_sign ? 1.F : 1.F - progress;
        }
        if (m_sign)
            return over && over->m_workspace && over->m_workspace->isVisible() &&
                           (over->positionAnimation()->isBeingAnimated() || waitingToSlide(over))
                       ? 1.F
                       : 0.F;
        if (!over || !over->m_workspace || !over->m_workspace->isVisible() ||
            !over->alpha(WINDOW_ALPHA_FADE)->isBeingAnimated())
            return 0.F;
        // Solid until the page over it has come in, so no wallpaper shows through the fade.
        return std::clamp((1.F - over->alphaValue(WINDOW_ALPHA_FADE)) * 10.F, 0.F, 1.F);
    }
    bool done() const override { return alpha() == 0.F; }
    void over(PHLWINDOW window) { m_over = window; }
    // Up: it leaves upwards as what arrives comes up from below; Down the other way. distance is the arriving card's
    // height and the gap above it.
    void slide(Slide slide, double distance) {
        m_sign = slide == Slide::Up ? 1 : slide == Slide::Down ? -1 : 0;
        m_distance = distance;
    }
    // Still over what came in under it (reveal's still), until it goes by itself (go).
    void still(const PHLWINDOW &lead, Slide slide, double gap, SP<AnimConfig> config) {
        m_over = lead;
        m_still = true;
        m_workspace = lead->m_workspace;
        m_sign = slide == Slide::Up ? 1 : slide == Slide::Down ? -1 : 0;
        m_distance = m_sign ? m_box.h + gap : 0;
        m_config = config; // animated variables hold their config weakly
        Animation::mgr()->createAnimation(0.F, m_away, config, AVARDAMAGE_NONE);
        // Nothing else need draw while it goes: the window under it is still, and frame() runs inside a render, where
        // the damage it adds is that frame's. So each step of its way asks for the next frame, and its end for one
        // without it. The variable is the picture's own, so this goes with it.
        m_away->setUpdateCallback([this](auto) { damage(); });
        m_away->setCallbackOnEnd([this](auto) { damage(); }, false);
    }
    bool stillWaiting() const { return m_still && !m_started && !m_gone; }
    bool isStill() const { return m_still; }
    void go() {
        if (!stillWaiting())
            return;
        m_started = true;
        *m_away = 1.F;
    }
    bool waiting() const { return !m_over && !m_gone; }
    bool alive() const { return !m_gone; }
    bool framed() const { return m_framed; }
    int generation() const { return m_generation; }
    void gone() { m_gone = true; }
    void damage() const {
        auto box = m_box;
        // A sliding picture is somewhere along its way out
        box.y -= m_distance;
        box.h += 2 * m_distance;
        g_pHyprRenderer->damageBox(box);
        if (const auto monitor = m_monitor.lock())
            monitor->scheduleFrame();
    }

  private:
    Picture() = default;
    PHLMONITORREF m_monitor;
    PHLWINDOWREF m_over;
    CBox m_box;
    bool m_gone = false, m_framed = false, m_still = false, m_started = false;
    PHLANIMVAR<float> m_away; // a still one's way out: 0 where it was taken, 1 gone
    SP<AnimConfig> m_config;
    std::optional<bool> m_backdrop; // blur under it (true: of the wallpaper alone), for a window seen through
    CBox m_window;                  // the window's own box, where its backdrop goes
    float m_rounding = 0, m_roundingPower = 2;
    int m_generation = 0, m_sign = 0;
    double m_distance = 0;
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

// The windows a picture was taken of in this request (hold or leave): a request's commands run one after another before
// the event loop goes on, so the list is cleared after them.
std::vector<PHLWINDOWREF> standIns;
void standIn(const PHLWINDOW &w) {
    if (standIns.empty())
        g_pEventLoopManager->doLater([] { standIns.clear(); });
    standIns.emplace_back(w);
}

bool drawable(const PHLWINDOW &w) {
    return w && w->m_isMapped && !w->isHidden() && w->m_workspace && w->m_workspace->isVisible() &&
           g_pHyprRenderer->shouldRenderWindow(w);
}
} // namespace

// What arrives slides into its tile from beside it, with no fade: at the user's window move animation and speed, the way
// a card's faces slide.
bool slideIn(const std::vector<PHLWINDOW> &shown, float speed, Card card, Slide slide) {
    CBox all = shown[0]->geometricBox(IGeometric::GEOMETRIC_GOAL);
    for (const auto &w : shown) {
        const auto box = w->geometricBox(IGeometric::GEOMETRIC_GOAL);
        const double x = std::min(all.x, box.x), y = std::min(all.y, box.y);
        all = {x, y, std::max(all.x + all.w, box.x + box.w) - x, std::max(all.y + all.h, box.y + box.h) - y};
    }
    static constexpr double GAP = 8;
    const double distance = all.h + card.extraTop + GAP, sign = slide == Slide::Up ? 1 : -1;
    const auto move = scaled("windowsMove", speed);
    PHLWINDOW lead;
    for (const auto &w : shown) {
        auto &rules = *w->m_ruleApplicator;
        rules.noAnim().unset(Desktop::Types::PRIORITY_SET_PROP);
        if (rules.noAnim().valueOr(false))
            continue;
        w->alpha(WINDOW_ALPHA_MOVE_FROM_WORKSPACE)->setValueAndWarp(1.F);
        // unseen until it slides: see Active::slideBy
        w->alpha(WINDOW_ALPHA_FADE)->setValueAndWarp(0.F);
        const auto config = move ? move : tree("windowsMove");
        w->positionAnimation()->setConfig(config);
        w->sizeAnimation()->setConfig(config);
        w->m_animatingIn = false;
        const auto previous = std::ranges::find_if(active, [&](const Active &a) { return a.window.lock() == w; });
        Active entry{.window = w, .in = move, .fade = nullptr, .steady = false, .tookBlur = false, .blur = {},
                     .slideBy = sign * distance, .until = std::chrono::steady_clock::now() + SLIDE_WAIT};
        if (previous != active.end()) {
            entry.tookBlur = previous->tookBlur;
            entry.blur = previous->blur;
            active.erase(previous);
        }
        active.push_back(std::move(entry));
        if (!lead)
            lead = w;
    }
    if (!lead)
        return true;
    // (a still one goes its own way)
    for (const auto &picture : pictures)
        if (picture->alive() && !picture->isStill() && picture->monitor() == lead->m_monitor) {
            picture->over(lead);
            picture->slide(slide, distance);
        }
    return true;
}

// What arrives is in place already, under the pictures held this request: they go over it, by themselves, once it has
// drawn at its size. It is neither moved, hidden nor faded, and keeps its no_anim: it may still be changing its tile.
bool stillIn(const std::vector<PHLWINDOW> &shown, float speed, Slide slide) {
    static constexpr double GAP = 8;
    const auto own = slide == Slide::None ? scaled("fadeOut", speed) : scaled("windowsMove", speed);
    const auto config = own ? own : tree(slide == Slide::None ? "fadeOut" : "windowsMove");
    const auto until = std::chrono::steady_clock::now() + SLIDE_WAIT;
    for (const auto &w : shown) {
        const auto previous = std::ranges::find_if(active, [&](const Active &a) { return a.window.lock() == w; });
        Active entry{.window = w, .in = nullptr, .fade = nullptr, .steady = false, .tookBlur = false, .blur = {},
                     .slideBy = 0., .until = until, .still = true};
        if (previous != active.end()) {
            entry.tookBlur = previous->tookBlur;
            entry.blur = previous->blur;
            active.erase(previous);
        }
        active.push_back(std::move(entry));
    }
    const auto &lead = shown[0];
    for (const auto &picture : pictures)
        if (picture->waiting() && picture->monitor() == lead->m_monitor)
            picture->still(lead, slide, GAP, config);
    return true;
}

bool reveal(const std::vector<PHLWINDOW> &windows, float speed, Card card, Slide slide, bool still) {
    std::vector<PHLWINDOW> shown;
    for (const auto &w : windows)
        if (w && w->m_isMapped && w->m_workspace && w->m_workspace->isVisible())
            shown.push_back(w);
    if (shown.empty())
        return false;
    if (still)
        return stillIn(shown, speed, slide);
    if (slide != Slide::None)
        return slideIn(shown, speed, card, slide);
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
        if (picture->alive() && !picture->isStill() && over != shown.end())
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
        standIn(w);
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
        standIn(w);
        // Even with no reveal to follow: the next frame takes it away.
        picture->damage();
        any = true;
    }
    return any;
}

void parked(const PHLWINDOW &w, bool unseen) {
    if (!w || w->m_monitorMovedFrom == -1 || !w->m_workspace || w->m_workspace->isVisible())
        return;
    if (!unseen && std::ranges::none_of(standIns, [&](const PHLWINDOWREF &s) { return s.lock() == w; }))
        return;
    // where it is drawn now, before it stops being drawn
    g_pHyprRenderer->damageWindow(w, true);
    // as Hyprland's own fade ends (Window.cpp): back to 1 for the next move, and no longer moving
    auto &fade = w->alpha(WINDOW_ALPHA_MOVE_TO_WORKSPACE);
    fade->resetAllCallbacks();
    fade->setValueAndWarp(1.F);
    w->m_monitorMovedFrom = -1;
}

bool steady(const PHLWINDOW &w) {
    return std::ranges::any_of(active, [&](const Active &a) { return a.steady && a.window.lock() == w; });
}

// Starts the slides that waited: all of one request together, once each app has drawn at its size or the wait is over.
void startSlides() {
    const auto now = std::chrono::steady_clock::now();
    const bool ready = std::ranges::all_of(active, [&](const Active &a) {
        const auto w = a.window.lock();
        return !a.slideBy || !w || now >= a.until || drawnAtSize(w);
    });
    if (!ready) {
        for (const auto &a : active)
            if (const auto w = a.window.lock(); a.slideBy && w && !drawnAtSize(w))
                letDraw(w, now);
        // Nothing moves while it waits, so nothing would draw the next frame that looks again: ask for one, after this
        // frame, where it lands on the next.
        g_pEventLoopManager->doLater([] {
            for (const auto &a : active)
                if (const auto w = a.window.lock(); a.slideBy && w) {
                    g_pHyprRenderer->damageWindow(w);
                    if (const auto monitor = w->m_monitor.lock())
                        monitor->scheduleFrame();
                }
        });
        return;
    }
    for (auto &a : active) {
        const auto w = a.window.lock();
        if (!a.slideBy || !w)
            continue;
        lastWait = std::chrono::duration<double, std::milli>(now - (a.until - SLIDE_WAIT)).count();
        if (a.still) {
            a.slideBy.reset();
            continue;
        }
        const auto goal = w->positionAnimation()->goal();
        w->alpha(WINDOW_ALPHA_FADE)->setValueAndWarp(1.F);
        w->positionAnimation()->setValueAndWarp(goal + Vector2D{0., *a.slideBy});
        *w->positionAnimation() = goal;
        a.slideBy.reset();
    }
    for (const auto &picture : pictures)
        picture->go();
}

void frame() {
    startSlides();
    std::erase_if(active, [](const Active &a) {
        const auto w = a.window.lock();
        if (!w)
            return true;
        if (animating(w) || a.slideBy)
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

std::optional<double> lastSlideWait() { return lastWait; }

void monitorGone(const PHLMONITOR &monitor) {
    drop([&](const SP<Picture> &picture) { return picture->monitor() == monitor; });
}

void shutdown() {
    standIns.clear();
    for (const auto &a : active)
        if (const auto w = a.window.lock())
            handBack(a, w);
    active.clear();
    for (const auto &picture : pictures)
        picture->damage();
    drop([](const SP<Picture> &) { return true; });
}
} // namespace Hyprflip::Reveal
