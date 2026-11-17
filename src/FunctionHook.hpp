#pragma once
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <optional>
#include <string>

namespace Hyprflip {
// The one exported function whose demangled name starts with `qualified` (e.g.
// "Config::Actions::killWindow("), hooked. `search` is the plain name that
// HyprlandAPI::findFunctionsByName matches as a substring of the mangled names.
// nullptr when no function or several match, when hooking fails (always on
// anything but x86_64), or when another plugin already hooked it.
inline CFunctionHook *hookFunction(void *handle, const std::string &search, const std::string &qualified,
                                   void *replacement) {
    std::optional<SFunctionMatch> only;
    for (const auto &match : HyprlandAPI::findFunctionsByName(handle, search)) {
        if (!match.demangled.starts_with(qualified))
            continue;
        if (only)
            return nullptr;
        only = match;
    }
    if (!only)
        return nullptr;
    auto *result = HyprlandAPI::createFunctionHook(handle, only->address, replacement);
    if (result && !result->hook()) {
        HyprlandAPI::removeFunctionHook(handle, result);
        result = nullptr;
    }
    return result;
}
} // namespace Hyprflip
