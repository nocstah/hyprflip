#pragma once
#include "Transition.hpp"
#include <array>
#include <hyprland/src/render/transformer/Transformer.hpp>
#include <memory>
#include <optional>

namespace Hyprflip {
struct Pose {
    Transition mode = Transition::Flip;
    float progress = 0, direction = 1;
    bool dirty = true;
    // Two snapshots, source then target. A card sliding along three or more faces keeps one per face,
    // in face order, and slides from face `from` by `travel` faces.
    std::array<SP<Render::IFramebuffer>, 4> faces;
    unsigned count = 2;
    float from = 0, travel = 1;
    unsigned present = 0; // faces captured, as bits; others are never drawn
    SP<Render::IFramebuffer> composite;
    // Hyprland asks each transformed window for its colour, then for a blur
    // matte. contentDrawn tells the two apart; preWindowRender clears it
    // before every draw of the leader.
    SP<Render::IFramebuffer> matte;
    bool contentDrawn = false;
    PHLWINDOWREF leader;
    float angle = 0;
    float perspective = 5.F;
    float retreat = .02F;
    bool failed = false;
    std::string error;
    std::optional<CBox> containerBox;
};

class FlipShader {
  public:
    ~FlipShader();
    bool initialize(std::string &error);
    SP<Render::IFramebuffer> captureFace(const std::vector<PHLWINDOW> &windows, PHLMONITOR monitor, std::string &error);
    // Draws the part of a captured face inside `from` (monitor pixels) into
    // `to` on the current target, with rounded corners. For the face switcher.
    void drawPreview(const SP<Render::IFramebuffer> &face, CBox from, CBox to, float alpha, float radius);
    GLuint previewProgram = 0;
    GLint previewTarget = -1, previewSource = -1, previewTexture = -1, previewAlpha = -1, previewSize = -1,
          previewRadius = -1;
    GLuint program = 0, vao = 0;
    GLint matrix = -1, composite = -1, rotation = -1, perspective = -1, texture = -1;
    GLint thirdTexture = -1, fourthTexture = -1, faceCount = -1, from = -1, travel = -1, present = -1;
    GLint secondTexture = -1, mode = -1, progress = -1, direction = -1, aspect = -1, backdrop = -1, useBackdrop = -1, pane = -1;
};

class FlipTransformer final : public Render::IWindowTransformer {
  public:
    FlipTransformer(PHLWINDOW window, std::shared_ptr<Pose> pose, std::shared_ptr<FlipShader> shader, bool glass = false);
    SP<Render::IFramebuffer> transform(SP<Render::IFramebuffer> in) override;
    void preWindowRender(CSurfacePassElement::SRenderData *data) override;

  private:
    SP<Render::IFramebuffer> matte();
    PHLWINDOWREF m_window;
    std::shared_ptr<Pose> m_pose;
    std::shared_ptr<FlipShader> m_shader;
    bool m_glass = false;
};
} // namespace Hyprflip
