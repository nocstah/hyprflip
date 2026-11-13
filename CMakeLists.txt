cmake_minimum_required(VERSION 3.25)
project(hyprflip VERSION 0.3.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(PkgConfig REQUIRED)
pkg_check_modules(HYPRLAND REQUIRED IMPORTED_TARGET hyprland=0.56.2)
# Hyprland runs the plugin's Lua functions on its own Lua state, so the plugin
# is built against the Lua that Hyprland links (5.5 for Arch's hyprland
# 0.56.2-4, 5.4 before), not whichever Lua has a pkg-config file.
# scripts/bootstrap.py reads it the same way.
set(HYPRFLIP_LUA "" CACHE STRING "Lua version Hyprland links, such as 5.5; empty reads it from Hyprland")
set(HYPRLAND_LUA_LIBRARY "")
find_program(HYPRFLIP_READELF readelf)
if(NOT HYPRFLIP_LUA)
  find_program(HYPRLAND_EXECUTABLE Hyprland REQUIRED)
  if(NOT HYPRFLIP_READELF)
    message(FATAL_ERROR "readelf (binutils) is needed to tell which Lua Hyprland links; or set -DHYPRFLIP_LUA=5.5")
  endif()
  execute_process(COMMAND "${HYPRFLIP_READELF}" -d "${HYPRLAND_EXECUTABLE}" OUTPUT_VARIABLE hyprland_dynamic)
  if(hyprland_dynamic MATCHES "\\[(liblua[a-z0-9.-]*)\\]")
    set(HYPRLAND_LUA_LIBRARY "${CMAKE_MATCH_1}")
  endif()
  if(HYPRLAND_LUA_LIBRARY MATCHES "^liblua-?([0-9]+\\.[0-9]+)\\.so" OR HYPRLAND_LUA_LIBRARY MATCHES "^liblua\\.so\\.([0-9]+\\.[0-9]+)")
    set(HYPRFLIP_LUA "${CMAKE_MATCH_1}")
  else()
    message(FATAL_ERROR "Could not tell which Lua ${HYPRLAND_EXECUTABLE} links; set -DHYPRFLIP_LUA=5.5 or the version it uses")
  endif()
endif()
string(REPLACE "." "" hyprflip_lua_digits "${HYPRFLIP_LUA}")
# pkg_search_module keeps what it found in the cache and does not search again.
# A prefix for each Lua version makes a build directory configured for another
# Lua (every one from before 0.3.0-rc.21 found lua5.4 as LUA) search afresh.
set(lua LUA${hyprflip_lua_digits})
pkg_search_module(${lua} REQUIRED IMPORTED_TARGET lua${HYPRFLIP_LUA} lua-${HYPRFLIP_LUA} lua${hyprflip_lua_digits} lua)
if(NOT ${lua}_VERSION MATCHES "^${HYPRFLIP_LUA}(\\.|$)")
  # Search again next time, once the right Lua is installed.
  unset(__pkg_config_checked_${lua} CACHE)
  message(FATAL_ERROR "Hyprland links Lua ${HYPRFLIP_LUA}, but pkg-config found Lua ${${lua}_VERSION} (${${lua}_MODULE_NAME}); install Lua ${HYPRFLIP_LUA}'s development files")
endif()
message(STATUS "Building against Lua ${${lua}_VERSION} (${${lua}_MODULE_NAME})")
pkg_check_modules(GLES REQUIRED IMPORTED_TARGET glesv2)
add_library(hyprflip MODULE src/Plugin.cpp src/Controller.cpp src/FlipTransformer.cpp src/FloatingCards.cpp src/CardFrames.cpp src/CardDrop.cpp src/Reveal.cpp src/FaceSwitcher.cpp)
set_target_properties(hyprflip PROPERTIES PREFIX "")
target_link_libraries(hyprflip PRIVATE PkgConfig::HYPRLAND PkgConfig::${lua} PkgConfig::GLES ${CMAKE_DL_LIBS})
target_compile_options(hyprflip PRIVATE -Wall -Wextra -Wpedantic -Wno-unused-parameter -fno-gnu-unique)
target_compile_definitions(hyprflip PRIVATE WLR_USE_UNSTABLE HYPRFLIP_VERSION="${PROJECT_VERSION}")
include(CTest)
if(BUILD_TESTING)
  add_library(motion_probe MODULE tests/motion_probe.cpp)
  set_target_properties(motion_probe PROPERTIES PREFIX "")
  target_link_libraries(motion_probe PRIVATE PkgConfig::HYPRLAND)
  target_compile_options(motion_probe PRIVATE -Wall -Wextra -Wpedantic -Wno-unused-parameter -fno-gnu-unique)
  target_compile_definitions(motion_probe PRIVATE WLR_USE_UNSTABLE)
  add_executable(core_test tests/core_test.cpp)
  target_include_directories(core_test PRIVATE src)
  target_compile_options(core_test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME core COMMAND core_test)
  # The compositor provides Hyprland's symbols, never the plugin's own: a
  # declared function left in an anonymous namespace links, then fails when
  # Hyprland first calls it.
  add_test(NAME own_symbols COMMAND sh -c "! nm -C -u \"$<TARGET_FILE:hyprflip>\" | grep 'Hyprflip::'")
  if(HYPRLAND_LUA_LIBRARY)
    add_test(NAME lua_library COMMAND ${CMAKE_COMMAND} -DREADELF=${HYPRFLIP_READELF}
             -DPLUGIN=$<TARGET_FILE:hyprflip> -DEXPECTED=${HYPRLAND_LUA_LIBRARY}
             -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/lua_library.cmake)
  endif()
endif()
install(TARGETS hyprflip LIBRARY DESTINATION lib/hyprland/plugins)
