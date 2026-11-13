# Hyprland calls the plugin's Lua functions on its own Lua state, so the
# plugin must link the Lua library Hyprland links and no other.
execute_process(COMMAND "${READELF}" -d "${PLUGIN}" OUTPUT_VARIABLE dynamic COMMAND_ERROR_IS_FATAL ANY)
string(REGEX MATCHALL "\\[liblua[a-z0-9.-]*\\]" linked "${dynamic}")
if(NOT linked STREQUAL "[${EXPECTED}]")
  message(FATAL_ERROR "The plugin links ${linked}; Hyprland links [${EXPECTED}]")
endif()
