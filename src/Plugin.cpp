#include "Controller.hpp"
#include <lua.hpp>
#include <memory>
#include <stdexcept>

namespace {
HANDLE handle = nullptr;
std::unique_ptr<Hyprflip::Controller> controller;
SP<SHyprCtlCommand> command;
int invoke(lua_State *L, const char *action) {
    auto result = controller->action(action);
    controller->notify(result);
    lua_pushboolean(L, result.ok);
    lua_pushlstring(L, result.message.data(), result.message.size());
    return 2;
}
int mark(lua_State *L) { return invoke(L, "mark"); }
int pair(lua_State *L) { return invoke(L, "pair"); }
int flip(lua_State *L) { return invoke(L, "flip"); }
int preview(lua_State *L) { return invoke(L, (std::string("preview ") + luaL_checkstring(L, 1)).c_str()); }
int unpair(lua_State *L) { return invoke(L, "unpair"); }
int cancel(lua_State *L) { return invoke(L, "cancel"); }
int finish(lua_State *L) { return invoke(L, "finish"); }
int attach(lua_State *L) {
    const std::string axis = luaL_optstring(L, 1, "horizontal");
    return invoke(L, ("attach " + axis).c_str());
}
int release(lua_State *L) { return invoke(L, "release"); }
int workspace(lua_State *L) {
    const auto destination = luaL_checkinteger(L, 1);
    if (!lua_isnoneornil(L, 2))
        luaL_checktype(L, 2, LUA_TBOOLEAN);
    const bool follow = lua_isnoneornil(L, 2) || lua_toboolean(L, 2);
    return invoke(L, ("workspace " + std::to_string(destination) + (follow ? "" : " silent")).c_str());
}
int move(lua_State *L) { return invoke(L, (std::string("move ") + luaL_checkstring(L, 1)).c_str()); }
int unfold(lua_State *L) { return invoke(L, "unfold"); }
int inContainer(lua_State *L) {
    lua_pushboolean(L, controller->inContainer());
    return 1;
}
int protectsWorkspace(lua_State *L) {
    const auto workspace = luaL_checkinteger(L, 1);
    lua_pushboolean(L, workspace > 0 && workspace <= INT32_MAX && controller->protectsWorkspace(workspace));
    return 1;
}
int adopt(lua_State *L) {
    const std::string front = luaL_checkstring(L, 1), back = luaL_checkstring(L, 2);
    return invoke(L, ("adopt " + front + " " + back).c_str());
}
int status(lua_State *L) {
    auto value = controller->status();
    lua_pushlstring(L, value.data(), value.size());
    return 1;
}
template <class T> auto config(SP<T> value) {
    if (!HyprlandAPI::addConfigValueV2(handle, value))
        throw std::runtime_error("Hyprflip: could not register config");
    return value;
}
} // namespace

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }
APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE h) {
    handle = h;
    if (std::string_view(__hyprland_api_get_hash()) != std::string_view(__hyprland_api_get_client_hash()))
        throw std::runtime_error("Hyprflip ABI mismatch. Rebuild against the running Hyprland and its compiler.");
    using namespace Config::Values;
    Hyprflip::Settings settings;
    settings.duration = config(makeConfigValue<Int>("plugin:hyprflip:duration_ms",
                                                    "Full flip duration in milliseconds (zero switches instantly)", 420,
                                                    SIntValueOptions{.min = 0, .max = 2000}));
    settings.enabled = config(makeConfigValue<Bool>("plugin:hyprflip:enabled", "Animate flips", true));
    settings.transition = config(makeConfigValue<String>("plugin:hyprflip:transition",
        "Card transition: flip, vertical, slide, fade, dissolve, portal or instant", "flip",
        SStringValueOptions{.validator = [](const std::string &value) -> std::expected<void, std::string> {
            if (Hyprflip::transition(value)) return {};
            return std::unexpected("Choose flip, vertical, slide, fade, dissolve, portal or instant");
        }}));
    settings.notifications =
        config(makeConfigValue<Bool>("plugin:hyprflip:notifications", "Show pairing and error notifications", true));
    settings.perspective = config(makeConfigValue<Float>("plugin:hyprflip:perspective", "Perspective camera distance",
                                                         5.F, SFloatValueOptions{.min = 2.F, .max = 8.F}));
    settings.retreat = config(makeConfigValue<Float>("plugin:hyprflip:retreat", "Retreat at the edge of the turn", .02F,
                                                     SFloatValueOptions{.min = 0.F, .max = .2F}));
    controller = std::make_unique<Hyprflip::Controller>(handle, std::move(settings));
    for (const auto &[name, fn] : {std::pair<const char *, PLUGIN_LUA_FN>{"mark", mark},
                                   {"pair", pair},
                                   {"flip", flip},
                                   {"preview", preview},
                                   {"unpair", unpair},
                                   {"cancel", cancel},
                                   {"finish", finish},
                                   {"attach", attach},
                                   {"release", release},
                                   {"workspace", workspace},
                                   {"move", move},
                                   {"unfold", unfold},
                                   {"in_container", inContainer},
                                   {"protects_workspace", protectsWorkspace},
                                   {"adopt", adopt},
                                   {"status", status}})
        if (!HyprlandAPI::addLuaFunction(handle, "hyprflip", name, fn))
            throw std::runtime_error("Hyprflip: could not register Lua function");
    command = HyprlandAPI::registerHyprCtlCommand(
        handle, {.name = "hyprflip", .exact = false, .fn = [](eHyprCtlOutputFormat, std::string request) {
                     const auto space = request.find(' ');
                     const auto action = space == std::string::npos ? "status" : request.substr(space + 1);
                     if (action == "status")
                         return controller->status();
                     auto r = controller->action(action);
                     controller->notify(r);
                     return (r.ok ? "ok: " : "error: ") + r.message;
                 }});
    if (!command)
        throw std::runtime_error("Hyprflip: could not register IPC command");
    return {"hyprflip", "Two real windows, two sides, one rotating card", "Hyprflip contributors", "0.1.1"};
}
APICALL EXPORT void PLUGIN_EXIT() {
    controller.reset();
    command.reset();
    handle = nullptr;
}
