cmake_minimum_required(VERSION 3.25)
project(hyprflip_hy3_bridge LANGUAGES CXX)
if(NOT HY3_SOURCE_DIR)
  message(FATAL_ERROR "Pass -DHY3_SOURCE_DIR pointing to the pinned hy3 checkout")
endif()
execute_process(COMMAND git -C "${HY3_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE HY3_REV OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
if(NOT HY3_REV STREQUAL "42b7ed8fd9aefd3f36e5f617afd5071245c67853")
  message(FATAL_ERROR "This experimental bridge requires hy3 hl0.56.0.1 (42b7ed8)")
endif()
find_package(PkgConfig REQUIRED)
pkg_check_modules(HYPRLAND REQUIRED hyprland=0.56.2)
set(HY3_NO_VERSION_CHECK OFF CACHE BOOL "Keep the compositor ABI check" FORCE)
add_subdirectory("${HY3_SOURCE_DIR}" upstream)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(HY3_PATCHED "${CMAKE_CURRENT_BINARY_DIR}/patched")
execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/prepare-source.py"
  "${HY3_SOURCE_DIR}" "${HY3_PATCHED}" COMMAND_ERROR_IS_FATAL ANY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/prepare-source.py")
set_source_files_properties("${HY3_SOURCE_DIR}/src/Hy3Layout.cpp" "${HY3_SOURCE_DIR}/src/Hy3Node.cpp"
  TARGET_DIRECTORY hy3 PROPERTIES HEADER_FILE_ONLY TRUE)
target_sources(hy3 PRIVATE Bridge.cpp HyprflipSafety.cpp "${HY3_PATCHED}/Hy3Layout.cpp" "${HY3_PATCHED}/Hy3Node.cpp")
# Wrap only the exit entry point so retained render-pass objects are destroyed
# while their code is still mapped. Upstream's tree and rendering stay intact.
set_source_files_properties("${HY3_SOURCE_DIR}/src/main.cpp" TARGET_DIRECTORY hy3
  PROPERTIES COMPILE_DEFINITIONS "pluginExit=hy3_original_plugin_exit")
target_include_directories(hy3 PRIVATE "${HY3_SOURCE_DIR}/src" "${CMAKE_CURRENT_LIST_DIR}" "${CMAKE_CURRENT_LIST_DIR}/../../src")
# Permit a real dlclose: otherwise GCC's GNU-unique symbols keep stale provider
# state alive across unload/reload, defeating the lifetime boundary.
target_compile_options(hy3 PRIVATE -fno-gnu-unique)
