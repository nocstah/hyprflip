#pragma once
#include "ContainerABI.hpp"
#include "FlipTransformer.hpp"
#include "Timeline.hpp"
#include <array>
#include <chrono>
#include <hyprland/src/config/values/ConfigValues.hpp>
#include <hyprland/src/desktop/view/Group.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <optional>
#include <map>

namespace Hyprflip {
struct Settings {
    SP<Config::Values::Int> duration;
    SP<Config::Values::Bool> enabled, notifications;
    SP<Config::Values::Float> perspective, retreat;
    SP<Config::Values::String> transition;
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
    bool inContainer();
    bool protectsWorkspace(uint32_t workspace) const;
    void notify(const Result &result);

  private:
    struct Pair {
        uint64_t id;
        std::array<PHLWINDOWREF, 2> windows;
        WP<Desktop::View::CGroup> group;
        bool previousLock = false;
        uint64_t containerID = 0, providerEpoch = 0;
    };
    struct State {
        std::array<std::vector<PHLWINDOW>, 2> faces;
        std::array<PHLWINDOW, 2> focused;
        std::array<bool, 2> vertical{};
        std::array<std::array<double, CONTAINER_MAX_PANES>, 2> ratios{};
        unsigned active = 0;
        bool unfolded = false;
        CBox geometry;
        bool contains(PHLWINDOW window) const;
        std::vector<PHLWINDOWREF> windows() const;
    };
    struct Turn {
        uint64_t pairID;
        unsigned source;
        Timeline timeline;
        std::chrono::steady_clock::time_point last;
        std::shared_ptr<Pose> pose;
        std::vector<Render::IWindowTransformer *> transformers;
        std::vector<PHLWINDOWREF> windows;
        CBox geometry;
        PHLMONITORREF monitor;
        PHLWORKSPACEREF workspace;
        std::optional<uint32_t> triggerKey;
        std::vector<bool> suppressedGlass;
        std::vector<CBox> windowGeometry;
        bool previewReturn = false;
    };
    Pair *find(PHLWINDOW window);
    Pair *find(uint64_t id);
    bool valid(const Pair &pair) const;
    std::optional<State> state(const Pair &pair) const;
    const ContainerAPI *provider(uint64_t epoch = 0) const;
    void discardContainer(const Pair &pair);
    void reconcile();
    void deferReconcile();
    void onFrame(PHLMONITOR monitor);
    void finish(bool applyDestination = true);
    void select(Pair &pair, unsigned index, bool focus = true);
    void damage(const Pair &pair);
    void detach();
    Result mark();
    Result pair();
    Result adopt(const std::string &front, const std::string &back);
    Result flip(std::optional<Transition> preview = std::nullopt);
    Result peek();
    Result endPeek();
    bool canReturnPeek() const;
    Result unpair();
    Result attach(bool vertical);
    Result release();
    Result workspace(uint32_t destination, bool follow);
    Result move(char direction);
    Result unfold();
    Result editContainer(ContainerEdit operation, const std::string &target = "");
    Result arrangeFace(const std::string &arguments);
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
    struct Peek {
        uint64_t pairID;
        unsigned source;
        std::optional<uint32_t> triggerKey;
        PHLWORKSPACEREF workspace;
        PHLMONITORREF monitor;
        CBox geometry;
        std::vector<PHLWINDOWREF> windows;
    };
    std::optional<Peek> m_peek;
    std::shared_ptr<FlipShader> m_shader;
    PHLMONITORREF m_renderingMonitor;
    SP<CEventLoopTimer> m_timer;
    UP<SEventLoopDoLaterLock> m_reconcileLater, m_keyLater;
    std::vector<CHyprSignalListener> m_listeners;
    std::optional<uint32_t> m_eventKey;
    bool m_mutating = false;
    bool m_stopping = false;
    std::string m_lastFallback;
    double m_captureMs = 0;
    struct Reservation {
        uint32_t workspace;
        std::chrono::steady_clock::time_point until;
    };
    std::map<std::string, Reservation> m_reservations;
    std::optional<uint32_t> m_movingWorkspace;
};
} // namespace Hyprflip
