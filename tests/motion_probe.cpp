// Read-only render-cycle probe, exclusively for the disposable compositor.
// Measures when a pose is actually consumed; polling IPC cannot do that.
#include <chrono>
#include <cstdlib>
#include <format>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <stdexcept>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
CHyprSignalListener listener;
SP<SHyprCtlCommand> command;
Clock::time_point epoch, frameStart;
std::string pending;
std::vector<std::string> samples;
bool recording = false;
} // namespace
APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }
APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    const char *runtime = std::getenv("XDG_RUNTIME_DIR");
    if (!runtime || !std::string_view(runtime).starts_with("/tmp/"))
        throw std::runtime_error("The motion probe is only for disposable test compositors under /tmp");
    if (std::string_view(__hyprland_api_get_hash()) != std::string_view(__hyprland_api_get_client_hash()))
        throw std::runtime_error("Motion probe ABI mismatch");
    samples.reserve(4096);
    listener = Event::bus()->m_events.render.stage.listen([](eRenderStage stage) {
        if (!recording || samples.size() >= 4096)
            return;
        if (stage == RENDER_PRE) {
            frameStart = Clock::now();
            auto state = HyprlandAPI::invokeHyprctlCommand("hyprflip", "status");
            if (state.starts_with('{'))
                pending = std::format("{{\"ms\":{},\"state\":{}",
                                      std::chrono::duration<double, std::milli>(frameStart - epoch).count(), state);
        } else if (stage == RENDER_POST && !pending.empty()) {
            samples.push_back(
                pending + std::format(",\"cpu_render_ms\":{}}}",
                                      std::chrono::duration<double, std::milli>(Clock::now() - frameStart).count()));
            pending.clear();
        }
    });
    command = HyprlandAPI::registerHyprCtlCommand(
        handle, {.name = "hyprflip-motion-probe", .exact = false, .fn = [](eHyprCtlOutputFormat, std::string request) {
                     if (request.ends_with(" start")) {
                         samples.clear();
                         pending.clear();
                         epoch = Clock::now();
                         recording = true;
                         return std::string("ok");
                     }
                     recording = false;
                     std::string json = "[";
                     for (const auto &sample : samples) {
                         if (json.size() > 1)
                             json += ',';
                         json += sample;
                     }
                     return json + "]";
                 }});
    return {"hyprflip-motion-probe", "Disposable render timing test", "Hyprflip contributors", "1"};
}
APICALL EXPORT void PLUGIN_EXIT() {
    listener.reset();
    command.reset();
    samples.clear();
    pending.clear();
    recording = false;
}
