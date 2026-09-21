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
    std::array<SP<Render::IFramebuffer>, 2> faces;
    SP<Render::IFramebuffer> composite;
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
    GLuint program = 0, vao = 0;
    GLint matrix = -1, composite = -1, rotation = -1, perspective = -1, texture = -1;
    GLint secondTexture = -1, mode = -1, progress = -1, direction = -1, aspect = -1;
};

class FlipTransformer final : public Render::IWindowTransformer {
  public:
    FlipTransformer(PHLWINDOW window, std::shared_ptr<Pose> pose, std::shared_ptr<FlipShader> shader);
    SP<Render::IFramebuffer> transform(SP<Render::IFramebuffer> in) override;
    void preWindowRender(CSurfacePassElement::SRenderData *data) override;

  private:
    PHLWINDOWREF m_window;
    std::shared_ptr<Pose> m_pose;
    std::shared_ptr<FlipShader> m_shader;
};
} // namespace Hyprflip
