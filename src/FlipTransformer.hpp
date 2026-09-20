#pragma once
#include <hyprland/src/render/transformer/Transformer.hpp>
#include <memory>

namespace Hyprflip {
struct Pose {
    float angle = 0;
    float perspective = 5.F;
    float retreat = .02F;
    bool failed = false;
    std::string error;
};

class FlipShader {
  public:
    ~FlipShader();
    bool initialize(std::string &error);
    GLuint program = 0, vao = 0;
    GLint matrix = -1, composite = -1, rotation = -1, perspective = -1, texture = -1;
};

class FlipTransformer final : public Render::IWindowTransformer {
  public:
    FlipTransformer(PHLWINDOW window, std::shared_ptr<Pose> pose, std::shared_ptr<FlipShader> shader);
    SP<Render::IFramebuffer> transform(SP<Render::IFramebuffer> in) override;

  private:
    PHLWINDOWREF m_window;
    std::shared_ptr<Pose> m_pose;
    std::shared_ptr<FlipShader> m_shader;
};
} // namespace Hyprflip
