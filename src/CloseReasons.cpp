#include "CloseReasons.hpp"
#include "FunctionHook.hpp"
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/managers/XWaylandManager.hpp>

namespace Hyprflip::CloseReasons {
CloseVia currentVia() {
    return g_pKeybindManager && g_pKeybindManager->m_currentKeybind ? CloseVia::Key : CloseVia::Other;
}
namespace {
void *plugin = nullptr;
CloseLedger *ledger = nullptr;
CFunctionHook *closeHook = nullptr, *killHook = nullptr;

// CHyprXWaylandManager::sendCloseWindow(PHLWINDOW): xdg_toplevel.close or the X11
// close, for a key bind, Lua, hyprctl dispatch, a gesture, a taskbar or a group bar.
using SendCloseWindow = void (*)(CHyprXWaylandManager *, PHLWINDOW);
void closeAsked(CHyprXWaylandManager *self, PHLWINDOW w) {
    if (ledger && w && w->m_isMapped)
        ledger->ask(w->m_stableID, CloseAsk::Close, currentVia(), w->getPID(), Clock::now());
    reinterpret_cast<SendCloseWindow>(closeHook->m_original)(self, w);
}
// Config::Actions::killWindow: SIGKILL to the window's process, with no event.
// The target is read the way Hyprland reads it, and the pid before the kill.
using KillWindow = Config::Actions::ActionResult (*)(std::optional<PHLWINDOW>);
Config::Actions::ActionResult killAsked(std::optional<PHLWINDOW> w) {
    if (ledger)
        if (const auto target = w.value_or(Desktop::focusState()->window()))
            ledger->ask(target->m_stableID, CloseAsk::Kill, currentVia(), target->getPID(), Clock::now());
    return reinterpret_cast<KillWindow>(killHook->m_original)(w);
}
} // namespace

CloseWatch install(void *handle, CloseLedger *closes, bool hooksAllowed) {
    plugin = handle;
    ledger = closes;
    if (!hooksAllowed)
        return {};
    closeHook = hookFunction(handle, "sendCloseWindow", "CHyprXWaylandManager::sendCloseWindow(",
                             reinterpret_cast<void *>(&closeAsked));
    killHook = hookFunction(handle, "killWindow", "Config::Actions::killWindow(", reinterpret_cast<void *>(&killAsked));
    return {closeHook != nullptr, killHook != nullptr};
}

void uninstall() {
    ledger = nullptr;
    for (auto *h : {closeHook, killHook})
        if (h)
            HyprlandAPI::removeFunctionHook(plugin, h);
    closeHook = killHook = nullptr;
}
} // namespace Hyprflip::CloseReasons
