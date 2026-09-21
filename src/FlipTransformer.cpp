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
out vec2 screenUV;
uniform mat3 boxToClip;
uniform mat3 outputToClip;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    screenUV = p;
    // Affine output mapping belongs at the vertices, not at every pixel.
    local = ((inverse(boxToClip) * outputToClip * vec3(p, 1.0)).xy - 0.5) * 2.0;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)glsl";
constexpr const char *FRAGMENT = R"glsl(#version 300 es
precision highp float;
in vec2 local;
in vec2 screenUV;
out vec4 color;
uniform sampler2D source;
uniform sampler2D secondSource;
uniform int mode;
uniform float progress;
uniform float direction;
uniform float aspect;
uniform mat3 boxToClip;
uniform vec3 rotation; // cosine, sine, bounded projection scale
uniform float perspective;
vec4 sampleFace(sampler2D face, vec2 p) {
    vec2 uv = (boxToClip * vec3(p * 0.5 + 0.5, 1.0)).xy * 0.5 + 0.5;
    if (any(greaterThan(abs(p), vec2(1.0))) || any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0))))
        return vec4(0.0);
    return texture(face, uv);
}
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float field(vec2 p) {
    vec2 cell = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(cell), hash(cell + vec2(1.0, 0.0)), f.x),
               mix(hash(cell + vec2(0.0, 1.0)), hash(cell + vec2(1.0, 1.0)), f.x), f.y);
}
void main() {
    if (mode == -1) { color = texture(source, screenUV); return; }
    color = vec4(0.0);
    if (mode >= 2) {
        if (any(greaterThan(abs(local), vec2(1.0)))) return;
        float t = clamp(progress, 0.0, 1.0);
        float e = t * t * t * (t * (6.0 * t - 15.0) + 10.0);
        if (t <= 0.0) { color = sampleFace(source, local); return; }
        if (t >= 1.0) { color = sampleFace(secondSource, local); return; }
        if (mode == 2) {
            color = sampleFace(source, local + vec2(2.0 * e * direction, 0.0))
                  + sampleFace(secondSource, local - vec2(2.0 * (1.0-e) * direction, 0.0));
        } else if (mode == 3) {
            color = mix(sampleFace(source, local), sampleFace(secondSource, local), e);
        } else if (mode == 4) {
            // A stable, smoothly interpolated field: reversing retraces it,
            // with no time-varying noise or separate seams between panes.
            float n = field((local * 0.5 + 0.5) * vec2(22.0 * aspect, 22.0));
            float reveal = smoothstep(n - 0.08, n + 0.08, mix(-0.08, 1.08, e));
            color = mix(sampleFace(source, local), sampleFace(secondSource, local), reveal);
        } else {
            vec2 radial = local * vec2(aspect, 1.0);
            float maximum = length(vec2(aspect, 1.0));
            float radius = mix(-0.06, 1.06, e) * maximum;
            float delta = (length(radial) - radius) / maximum;
            float reveal = 1.0 - smoothstep(-0.04, 0.04, delta);
            float ring = exp(-delta * delta * 900.0) * sin(t * 3.14159265);
            color = mix(sampleFace(source, local), sampleFace(secondSource, local / (1.0 + 0.025 * ring)), reveal);
            color.rgb *= 1.0 + 0.045 * ring;
        }
        return;
    }
    vec2 axis = mode == 1 ? local.yx : local;
    float c = rotation.x, s = rotation.y, k = rotation.z;
    if (c < 0.00001) return;
    float divisor = k * c - axis.x * s;
    float x = axis.x * perspective / max(divisor, 0.00001);
    float y = axis.y * (perspective + x * s) / k;
    vec2 point = mode == 1 ? vec2(y, x) : vec2(x, y);
    vec2 sampleUV = (boxToClip * vec3(point * 0.5 + 0.5, 1.0)).xy * 0.5 + 0.5;
    // Derivatives must be evaluated before divergent clipping. Four subpixel
    // samples calm text/edge shimmer during minification, on both the color
    // pass and the compositor's blur matte. No temporal smearing or snapshots.
    vec2 dx = dFdx(sampleUV) * (0.25 * abs(s)), dy = dFdy(sampleUV) * (0.25 * abs(s));
    vec2 edge = clamp((1.0 - abs(vec2(x, y))) / max(fwidth(vec2(x, y)), vec2(0.00001)) + 0.5, 0.0, 1.0);
    if (divisor <= 0.00001 || edge.x * edge.y <= 0.0) return;
    if (any(lessThan(sampleUV, vec2(0.0))) || any(greaterThan(sampleUV, vec2(1.0)))) return;
    color = (texture(source, sampleUV + dx + dy) + texture(source, sampleUV + dx - dy)
           + texture(source, sampleUV - dx + dy) + texture(source, sampleUV - dx - dy)) * (0.25 * edge.x * edge.y);
    // A single light field in card coordinates, shared by every pane. Fade it
    // out at rest and keep alpha untouched so the blur matte and transparent
    // margins retain the same coverage. This adds no texture samples or pass.
    float depth = s * s;
    float light = 1.0 - depth * (0.065 + 0.035 * x * s);
    color.rgb *= light;
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
    GLint program, vao, activeTexture, texture[2], sampler[2], readFramebuffer;
    GLint blendSrcRGB, blendDstRGB, blendSrcAlpha, blendDstAlpha, blendEqRGB, blendEqAlpha;
    GLboolean blend, scissor, depth, stencil, cull, depthMask, colorMask[4];
    GLState() {
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &readFramebuffer);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &depthMask);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &activeTexture);
        for (unsigned i = 0; i < 2; ++i) {
            glActiveTexture(GL_TEXTURE0 + i);
            glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture[i]);
            glGetIntegerv(GL_SAMPLER_BINDING, &sampler[i]);
        }
        glGetIntegerv(GL_BLEND_SRC_RGB, &blendSrcRGB);
        glGetIntegerv(GL_BLEND_DST_RGB, &blendDstRGB);
        glGetIntegerv(GL_BLEND_SRC_ALPHA, &blendSrcAlpha);
        glGetIntegerv(GL_BLEND_DST_ALPHA, &blendDstAlpha);
        glGetIntegerv(GL_BLEND_EQUATION_RGB, &blendEqRGB);
        glGetIntegerv(GL_BLEND_EQUATION_ALPHA, &blendEqAlpha);
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
        for (unsigned i = 0; i < 2; ++i) {
            glActiveTexture(GL_TEXTURE0 + i);
            glBindTexture(GL_TEXTURE_2D, texture[i]);
            glBindSampler(i, sampler[i]);
        }
        glBlendFuncSeparate(blendSrcRGB, blendDstRGB, blendSrcAlpha, blendDstAlpha);
        glBlendEquationSeparate(blendEqRGB, blendEqAlpha);
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
    secondTexture = glGetUniformLocation(p, "secondSource");
    mode = glGetUniformLocation(p, "mode");
    progress = glGetUniformLocation(p, "progress");
    direction = glGetUniformLocation(p, "direction");
    aspect = glGetUniformLocation(p, "aspect");
    return true;
}

SP<Render::IFramebuffer> FlipShader::captureFace(const std::vector<PHLWINDOW> &windows, PHLMONITOR monitor, std::string &error) {
    g_pHyprRenderer->glBackend()->makeEGLCurrent();
    if (!initialize(error)) return nullptr;
    SP<Render::IFramebuffer> face;
    for (const auto &window : windows) {
        auto pane = g_pHyprRenderer->makeSnapshotFB(window);
        if (!pane || !pane->isAllocated() || !pane->getTexture()) {
            error = "A face could not be captured";
            return nullptr;
        }
        if (!face) { face = pane; continue; }
        CRegion damage{0, 0, monitor->m_transformedSize.x, monitor->m_transformedSize.y};
        if (!g_pHyprRenderer->beginFullFakeRender(monitor, damage, face)) {
            error = "Could not compose the card face";
            return nullptr;
        }
        {
            GLState state;
            glEnable(GL_BLEND);
            glBlendEquation(GL_FUNC_ADD);
            glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
            glDisable(GL_SCISSOR_TEST);
            glDisable(GL_DEPTH_TEST);
            glDisable(GL_STENCIL_TEST);
            glDisable(GL_CULL_FACE);
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
            glUseProgram(program);
            glBindVertexArray(vao);
            glActiveTexture(GL_TEXTURE0);
            glBindTexture(GL_TEXTURE_2D, pane->getTexture()->m_texID);
            glBindSampler(0, 0);
            glUniform1i(texture, 0);
            glUniform1i(mode, -1);
            glDrawArrays(GL_TRIANGLES, 0, 3);
        }
        g_pHyprRenderer->endRender();
    }
    return face;
}

FlipTransformer::FlipTransformer(PHLWINDOW window, std::shared_ptr<Pose> pose, std::shared_ptr<FlipShader> shader)
    : m_window(window), m_pose(std::move(pose)), m_shader(std::move(shader)) {}

void FlipTransformer::preWindowRender(CSurfacePassElement::SRenderData *data) {
    if (snapshots(m_pose->mode) && !m_pose->failed) {
        // The cached whole face provides color. Zero also disables native
        // per-pane backdrop blur, which otherwise paints over the composite.
        data->fadeAlpha = 0;
        data->decorate = false;
    }
}

SP<Render::IFramebuffer> FlipTransformer::transform(SP<Render::IFramebuffer> in) {
    const auto w = m_window.lock();
    if (!w || !in || m_pose->failed)
        return in;
    auto &render = g_pHyprRenderer->m_renderData;
    const auto monitor = render.pMonitor;
    if (!monitor || !monitor->resources() || !in->getTexture())
        return in;
    const bool snapshot = snapshots(m_pose->mode);
    if (snapshot && m_pose->leader != w) return in; // already cleared and rendered with zero alpha
    if (snapshot && !m_pose->dirty && m_pose->composite) return m_pose->composite;
    GLState state;
    if (!m_shader->initialize(m_pose->error)) {
        m_pose->failed = true;
        return in;
    }
    if (snapshot && !m_pose->composite) {
        m_pose->composite = g_pHyprRenderer->createFB("Hyprflip transition");
        if (!m_pose->composite->alloc(in->m_size.x, in->m_size.y, DRM_FORMAT_ABGR8888)) {
            m_pose->error = "Could not allocate the card transition";
            m_pose->failed = true;
            return in;
        }
        m_pose->composite->setImageDescription(in->imageDescription());
    }
    auto out = snapshot ? m_pose->composite : monitor->resources()->getUnusedWorkBuffer();
    if (!out) {
        m_pose->error = "No compositor work buffer available";
        m_pose->failed = true;
        return in;
    }
    auto guard = g_pHyprRenderer->bindTempFB(out);
    CBox box = m_pose->containerBox.value_or(w->getFullWindowBoundingBox());
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
    glBindTexture(GL_TEXTURE_2D, (snapshot ? m_pose->faces[0] : in)->getTexture()->m_texID);
    glBindSampler(0, 0);
    glUniform1i(m_shader->texture, 0);
    if (snapshot) {
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, m_pose->faces[1]->getTexture()->m_texID);
        glBindSampler(1, 0);
        glUniform1i(m_shader->secondTexture, 1);
    }
    glUniform1i(m_shader->mode, static_cast<int>(m_pose->mode));
    glUniform1f(m_shader->progress, m_pose->progress);
    glUniform1f(m_shader->direction, m_pose->direction);
    glUniform1f(m_shader->aspect, box.w / std::max(1.0, box.h));
    glUniformMatrix3fv(m_shader->matrix, 1, GL_FALSE, matrix.getMatrix().data());
    glUniformMatrix3fv(m_shader->composite, 1, GL_FALSE, composite.getMatrix().data());
    const float sine = std::sin(m_pose->angle);
    glUniform3f(m_shader->rotation, std::cos(m_pose->angle), sine,
                projectionScale(sine, m_pose->perspective, m_pose->retreat));
    glUniform1f(m_shader->perspective, m_pose->perspective);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    m_pose->dirty = false;
    return out;
}
} // namespace Hyprflip
