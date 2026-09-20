#pragma once
#include "FlipTransformer.hpp"
#include "Timeline.hpp"
#include <array>
#include <chrono>
#include <hyprland/src/config/values/ConfigValues.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <optional>

namespace Hyprflip {
struct Settings {
    SP<Config::Values::Int> duration;
    SP<Config::Values::Bool> enabled, notifications;
    SP<Config::Values::Float> perspective, retreat;
};
struct Result {
    bool ok;
    std::string message;
};

class Controller {
  public:
    Controller(HANDLE handle, Settings settings);
    ~Controller();
    Result action(const std::string &action);
    std::string status();
    void notify(const Result &result);

  private:
    struct Pair {
        uint64_t id;
        std::array<PHLWINDOWREF, 2> windows;
        WP<Desktop::View::CGroup> group;
        bool previousLock = false;
    };
    struct Turn {
        uint64_t pairID;
        unsigned source;
        Timeline timeline;
        std::chrono::steady_clock::time_point last;
        std::shared_ptr<Pose> pose;
        std::array<Render::IWindowTransformer *, 2> transformers{};
        std::array<PHLWINDOWREF, 2> windows;
        CBox geometry;
        PHLMONITORREF monitor;
        PHLWORKSPACEREF workspace;
        std::optional<uint32_t> triggerKey;
        std::array<bool, 2> suppressedGlass{};
    };
    Pair *find(PHLWINDOW window);
    Pair *find(uint64_t id);
    bool valid(const Pair &pair) const;
    void reconcile();
    void deferReconcile();
    void onFrame(PHLMONITOR monitor);
    void finish(bool applyDestination = true);
    void select(Pair &pair, unsigned index);
    void damage(const Pair &pair);
    void detach();
    Result mark();
    Result pair();
    Result adopt(const std::string &front, const std::string &back);
    Result flip();
    Result unpair();
    std::string unavailable(PHLWINDOW window) const;
    bool inputBusy() const;
    std::string animationFallback(PHLWINDOW a, PHLWINDOW b) const;
    void onClose(PHLWINDOW window);
    void onFocus(PHLWINDOW window);
    void settleInput();
    HANDLE m_handle;
    Settings m_settings;
    PHLWINDOWREF m_marked;
    std::vector<Pair> m_pairs;
    uint64_t m_nextID = 1;
    std::optional<Turn> m_turn;
    std::shared_ptr<FlipShader> m_shader;
    SP<CEventLoopTimer> m_timer;
    UP<SEventLoopDoLaterLock> m_reconcileLater, m_keyLater;
    std::vector<CHyprSignalListener> m_listeners;
    std::optional<uint32_t> m_eventKey;
    bool m_mutating = false;
    bool m_stopping = false;
    std::string m_lastFallback;
};
} // namespace Hyprflip
