#include "FlipTransformer.hpp"
#include "Timeline.hpp"
#include <array>
#include <cmath>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/output/MonitorResources.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>

namespace Hyprflip {
namespace {
constexpr const char *VERTEX = R"glsl(#version 300 es
precision highp float;
out vec2 local;
uniform mat3 boxToClip;
uniform mat3 outputToClip;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    // Affine output mapping belongs at the vertices, not at every pixel.
    local = ((inverse(boxToClip) * outputToClip * vec3(p, 1.0)).xy - 0.5) * 2.0;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)glsl";
constexpr const char *FRAGMENT = R"glsl(#version 300 es
precision highp float;
in vec2 local;
out vec4 color;
uniform sampler2D source;
uniform mat3 boxToClip;
uniform vec3 rotation; // cosine, sine, bounded projection scale
uniform float perspective;
void main() {
    color = vec4(0.0);
    float c = rotation.x, s = rotation.y, k = rotation.z;
    if (c < 0.00001) return;
    float divisor = k * c - local.x * s;
    float x = local.x * perspective / max(divisor, 0.00001);
    float y = local.y * (perspective + x * s) / k;
    vec2 sampleUV = (boxToClip * vec3(vec2(x, y) * 0.5 + 0.5, 1.0)).xy * 0.5 + 0.5;
    // Derivatives must be evaluated before divergent clipping. Four subpixel
    // samples calm text/edge shimmer during minification, on both the color
    // pass and the compositor's blur matte. No temporal smearing or snapshots.
    vec2 dx = dFdx(sampleUV) * (0.25 * abs(s)), dy = dFdy(sampleUV) * (0.25 * abs(s));
    vec2 edge = clamp((1.0 - abs(vec2(x, y))) / max(fwidth(vec2(x, y)), vec2(0.00001)) + 0.5, 0.0, 1.0);
    if (divisor <= 0.00001 || edge.x * edge.y <= 0.0) return;
    if (any(lessThan(sampleUV, vec2(0.0))) || any(greaterThan(sampleUV, vec2(1.0)))) return;
    color = (texture(source, sampleUV + dx + dy) + texture(source, sampleUV + dx - dy)
           + texture(source, sampleUV - dx + dy) + texture(source, sampleUV - dx - dy)) * (0.25 * edge.x * edge.y);
}
)glsl";

GLuint compile(GLenum type, const char *source, std::string &error) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &source, nullptr);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        std::array<char, 2048> log{};
        glGetShaderInfoLog(s, log.size(), nullptr, log.data());
        error = log.data();
        glDeleteShader(s);
        return 0;
    }
    return s;
}

// Restore real GL state, including bindings, so Hyprland's state caches remain valid.
struct GLState {
    GLint program, vao, activeTexture, texture, sampler, readFramebuffer;
    GLboolean blend, scissor, depth, stencil, cull, depthMask, colorMask[4];
    GLState() {
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &readFramebuffer);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &depthMask);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &activeTexture);
        glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture);
        glGetIntegerv(GL_SAMPLER_BINDING, &sampler);
        blend = glIsEnabled(GL_BLEND);
        scissor = glIsEnabled(GL_SCISSOR_TEST);
        depth = glIsEnabled(GL_DEPTH_TEST);
        stencil = glIsEnabled(GL_STENCIL_TEST);
        cull = glIsEnabled(GL_CULL_FACE);
        glGetBooleanv(GL_COLOR_WRITEMASK, colorMask);
    }
    ~GLState() {
        glUseProgram(program);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, readFramebuffer);
        glDepthMask(depthMask);
        glBindVertexArray(vao);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, texture);
        glBindSampler(0, sampler);
        glActiveTexture(activeTexture);
        for (const auto &[flag, enabled] : {std::pair{GL_BLEND, blend},
                                            {GL_SCISSOR_TEST, scissor},
                                            {GL_DEPTH_TEST, depth},
                                            {GL_STENCIL_TEST, stencil},
                                            {GL_CULL_FACE, cull}})
            enabled ? glEnable(flag) : glDisable(flag);
        glColorMask(colorMask[0], colorMask[1], colorMask[2], colorMask[3]);
    }
};
} // namespace

FlipShader::~FlipShader() {
    if (!program && !vao)
        return;
    if (g_pHyprRenderer && g_pHyprRenderer->glBackend()) {
        g_pHyprRenderer->glBackend()->makeEGLCurrent();
        if (program)
            glDeleteProgram(program);
        if (vao)
            glDeleteVertexArrays(1, &vao);
    }
}

bool FlipShader::initialize(std::string &error) {
    if (program)
        return true;
    GLuint vert = compile(GL_VERTEX_SHADER, VERTEX, error);
    if (!vert)
        return false;
    GLuint frag = compile(GL_FRAGMENT_SHADER, FRAGMENT, error);
    if (!frag) {
        glDeleteShader(vert);
        return false;
    }
    GLuint p = glCreateProgram();
    glAttachShader(p, vert);
    glAttachShader(p, frag);
    glLinkProgram(p);
    glDeleteShader(vert);
    glDeleteShader(frag);
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        std::array<char, 2048> log{};
        glGetProgramInfoLog(p, log.size(), nullptr, log.data());
        error = log.data();
        glDeleteProgram(p);
        return false;
    }
    program = p;
    glGenVertexArrays(1, &vao);
    matrix = glGetUniformLocation(p, "boxToClip");
    composite = glGetUniformLocation(p, "outputToClip");
    rotation = glGetUniformLocation(p, "rotation");
    perspective = glGetUniformLocation(p, "perspective");
    texture = glGetUniformLocation(p, "source");
    return true;
}

FlipTransformer::FlipTransformer(PHLWINDOW window, std::shared_ptr<Pose> pose, std::shared_ptr<FlipShader> shader)
    : m_window(window), m_pose(std::move(pose)), m_shader(std::move(shader)) {}

SP<Render::IFramebuffer> FlipTransformer::transform(SP<Render::IFramebuffer> in) {
    const auto w = m_window.lock();
    if (!w || !in || m_pose->failed)
        return in;
    auto &render = g_pHyprRenderer->m_renderData;
    const auto monitor = render.pMonitor;
    if (!monitor || !monitor->resources() || !in->getTexture())
        return in;
    GLState state;
    if (!m_shader->initialize(m_pose->error)) {
        m_pose->failed = true;
        return in;
    }
    auto out = monitor->resources()->getUnusedWorkBuffer();
    if (!out) {
        m_pose->error = "No compositor work buffer available";
        m_pose->failed = true;
        return in;
    }
    auto guard = g_pHyprRenderer->bindTempFB(out);
    CBox box = w->getFullWindowBoundingBox();
    Vector2D offset = w->m_floatingOffset - monitor->m_position;
    if (w->m_workspace && !w->m_pinned)
        offset += w->m_workspace->m_renderOffset->value();
    box.translate(offset).scale(monitor->m_scale);
    render.renderModif.applyToBox(box);
    const auto matrix = g_pHyprRenderer->projectBoxToTarget(box, HYPRUTILS_TRANSFORM_NORMAL).copy().transpose();
    // The transformed pass composites a full-monitor texture using the default
    // monitor transform. Pre-map the output to that sampling space. Merely
    // projecting within the input FBO applies monitor rotation twice.
    CBox compositeBox{0, 0, monitor->m_transformedSize.x, monitor->m_transformedSize.y};
    render.renderModif.applyToBox(compositeBox);
    const auto composite = g_pHyprRenderer->projectBoxToTarget(compositeBox).copy().transpose();
    glDisable(GL_BLEND);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_STENCIL_TEST);
    glDisable(GL_CULL_FACE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glUseProgram(m_shader->program);
    glBindVertexArray(m_shader->vao);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, in->getTexture()->m_texID);
    glBindSampler(0, 0);
    glUniform1i(m_shader->texture, 0);
    glUniformMatrix3fv(m_shader->matrix, 1, GL_FALSE, matrix.getMatrix().data());
    glUniformMatrix3fv(m_shader->composite, 1, GL_FALSE, composite.getMatrix().data());
    const float sine = std::sin(m_pose->angle);
    glUniform3f(m_shader->rotation, std::cos(m_pose->angle), sine,
                projectionScale(sine, m_pose->perspective, m_pose->retreat));
    glUniform1f(m_shader->perspective, m_pose->perspective);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    return out;
}
} // namespace Hyprflip
