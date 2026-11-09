#pragma once
#include "ContainerABI.hpp"
#include "CardFrames.hpp"
#include "CardDrop.hpp"
#include "FaceSwitcher.hpp"
#include "FlipTransformer.hpp"
#include "InputGuard.hpp"
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
    SP<Config::Values::Int> duration, cardGap, fullscreenDivider, switcherDelay, swipeFingers;
    SP<Config::Values::Bool> switcher, enabled, notifications, cardFrame, dragToAdd, accentRing, desktopNotifications;
    SP<Config::Values::Float> perspective, retreat;
    SP<Config::Values::String> transition, accentColor, dividerColor;
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
    // Apps on the focused card's visible face; 0 outside multi-app cards.
    size_t faceSize();
    bool protectsWorkspace(uint32_t workspace) const;
    // Narrower than protectsWorkspace: native cards may chill as one window.
    bool blocksChill(uint32_t workspace) const;
    // The whole card's rectangle for any of its apps, so tools that treat a
    // group as one window (Chill) can measure the card instead of one pane.
    std::optional<CBox> cardBox(const std::string &window) const;
    bool placeCard(const std::string &window, CBox box);
    void notify(const Result &result);

  private:
    Result floating();
    Result fullscreen();
    Result restore(const std::string &arguments);
    struct Pair {
        uint64_t id;
        std::array<PHLWINDOWREF, 2> windows;
        WP<Desktop::View::CGroup> group;
        bool previousLock = false;
        uint64_t containerID = 0, providerEpoch = 0;
        bool frame = false;
        // The face shown before the current one: a tap of the flip key on a
        // card with three or more faces goes back to it.
        std::optional<unsigned> lastFace;
    };
    struct State {
        // Faces 0..count-1; a plain pair always has two.
        std::array<std::vector<PHLWINDOW>, CONTAINER_MAX_FACES> faces;
        std::array<PHLWINDOW, CONTAINER_MAX_FACES> focused;
        std::array<bool, CONTAINER_MAX_FACES> vertical{};
        std::array<std::array<double, CONTAINER_MAX_PANES>, CONTAINER_MAX_FACES> ratios{};
        unsigned count = 2;
        unsigned active = 0;
        unsigned next() const { return (active + 1) % count; }
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
        // A swipe holds the faces under the fingers; the timeline waits.
        // `shown` glides towards `goal` each frame; after the fingers lift a
        // spring carries `speed` on to `goal`, the face it settles on.
        bool dragging = false, settling = false;
        double goal = 0, shown = 0, speed = 0;
        // The face the turn goes to: the next one round.
        unsigned target = 1;
        unsigned face(bool second) const { return second ? target : source; }
        float sign() const { return target > source ? 1.F : -1.F; }
        // A slide along the faces, in faces: signed, the short way round.
        static float travel(unsigned from, unsigned to, unsigned count) {
            const unsigned ahead = (to + count - from) % count;
            return ahead * 2 <= count ? float(ahead) : -float(count - ahead);
        }
    };
    Pair *find(PHLWINDOW window);
    Pair *find(uint64_t id);
    bool valid(const Pair &pair) const;
    std::optional<State> state(const Pair &pair) const;
    const ContainerAPI *provider(uint64_t epoch = 0) const;
    void discardContainer(const Pair &pair);
    void reconcile();
    void syncFrames();
    std::vector<CardFrameView> frameViews() const;
    std::vector<CardDropOffer> dropOffers(PHLWINDOW window) const;
    Result dropAttach(PHLWINDOW window, const CardDropOffer &offer);
    std::unique_ptr<CardDrop> m_drop;
    Result dispatch(const std::string &action);
    void deferReconcile();
    void onFrame(PHLMONITOR monitor);
    void finish(bool applyDestination = true);
    void select(Pair &pair, unsigned index, bool focus = true);
    void damage(const Pair &pair);
    void detach();
    Result mark(const std::string &target = {});
    Result pair(bool multiApp = false);
    Result adopt(const std::string &front, const std::string &back);
    // A card addressed by its id (target) turns without taking the focus.
    // `to` picks a face; by default the card turns to the next one round.
    Result flip(std::optional<Transition> preview = std::nullopt, Pair *target = nullptr,
                std::optional<unsigned> to = std::nullopt);
    Result show(Pair &pair, unsigned side);
    Result cardAction(const std::string &arguments);
    // The flip key: a tap turns; on a card with three or more faces it goes
    // back to the last face, and holding it opens the face switcher.
    Result flipKey();
    Result switcherAction(const std::string &arguments);
    void openSwitcher();
    void commitSwitch();
    void cancelSwitch();
    bool switchHeld() const;
    bool switcherKey(const IKeyboard::SKeyEvent &key);
    void remember(Pair &pair, unsigned shown, unsigned next);
    // A sideways swipe over a card with three or more faces slides them
    // under the fingers and settles on the nearest face when they lift.
    bool swipeBegin(uint32_t fingers);
    void swipeUpdate(Vector2D delta);
    void swipeEnd(bool cancelled);
    Result peek();
    Result endPeek();
    bool canReturnPeek() const;
    Result unpair();
    // Dissolves a card or pair where it is, leaving its apps as windows.
    Result ungroup(Pair &pair);
    Result attach(bool vertical, bool newFace = false);
    Result release();
    Result workspace(uint32_t destination, bool follow);
    // scripted: the silent move by id, guarded by scriptBusy instead of inputBusy.
    Result moveCard(Pair &pair, const std::string &destination, bool follow, bool scripted = false);
    Result move(char direction);
    Result unfold();
    Result editContainer(ContainerEdit operation, const std::string &target = "");
    Result arrangeFace(const std::string &arguments);
    Result replacePane(const std::string &arguments);
    std::string unavailable(PHLWINDOW window) const;
    bool inputBusy() const;
    InputState input(const std::vector<PHLWINDOW> &targets) const;
    // Input that an id-addressed silent action on these windows would disturb.
    bool scriptBusy(const std::vector<PHLWINDOW> &targets) const;
    std::vector<PHLWINDOW> members(const Pair &pair) const;
    std::string animationFallback(PHLWINDOW a, PHLWINDOW b) const;
    static bool glassy(PHLWINDOW w);
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
    struct Switch {
        uint64_t pairID;
        std::optional<uint32_t> key; // the flip key while it is down; none from IPC
        unsigned selected, count;
        bool open = false, scripted = false;
    };
    std::optional<Switch> m_switch;
    std::unique_ptr<FaceSwitcher> m_switcher;
    SP<CEventLoopTimer> m_switchTimer;
    UP<SEventLoopDoLaterLock> m_switchLater;
    bool m_eatSwitchRelease = false;
    bool m_forceStrip = false, m_swipeCapture = false;
    struct Swipe {
        uint64_t pairID;
        double width, moved = 0, velocity = 0; // moved and velocity in card widths
        uint32_t lastTime = 0;
        bool started = false;
    };
    std::optional<Swipe> m_swipe;
    std::shared_ptr<FlipShader> m_shader;
    std::unique_ptr<CardFrames> m_frames;
    PHLMONITORREF m_renderingMonitor;
    SP<CEventLoopTimer> m_timer;
    UP<SEventLoopDoLaterLock> m_reconcileLater, m_keyLater, m_frameLater, m_dropLater;
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
