#pragma once
#include "CloseLedger.hpp"

// Notes close requests and kills in a CloseLedger as Hyprland sends them: every
// polite close goes through CHyprXWaylandManager::sendCloseWindow, and the kill
// dispatchers through Config::Actions::killWindow. Nothing is logged; status
// reports which hooks are live.
namespace Hyprflip::CloseReasons {
// Installs both hooks unless hooksAllowed is false (HYPRFLIP_CLOSE_HOOKS=0).
// The watch says which are live; one may install without the other.
CloseWatch install(void *handle, CloseLedger *ledger, bool hooksAllowed);
// Stops noting before the hooks go, so no hook writes to a ledger that is gone.
void uninstall();
// Key while a key bind's dispatcher runs (Lua-function binds included), else Other.
CloseVia currentVia();
} // namespace Hyprflip::CloseReasons
