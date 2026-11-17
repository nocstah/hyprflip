#include <vector>
#include "AccentColor.hpp"
#include "CloseLedger.hpp"
#include "InputGuard.hpp"
#include "SplitLayout.hpp"
#include "Timeline.hpp"
#include <cstdlib>
#include <iostream>

static void require(bool condition, const char *message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

// Close requests matched to closes, the record ring, and the "closes" JSON, on fake times.
static void closeLedger() {
    using namespace Hyprflip;
    using std::chrono::milliseconds, std::chrono::seconds, std::chrono::minutes;
    const Clock::time_point t0{};
    const CloseWatch both{true, true}, closeOnly{true, false}, none{};
    const auto ledger = [] { return CloseLedger("0123456789abcdef"); };
    const auto isOwn = [](const CloseVerdict &v, CloseReason reason) {
        return v.reason == reason && !v.via && !v.askedMs && !v.pid;
    };
    {
        auto l = ledger();
        l.ask(1, CloseAsk::Close, CloseVia::Key, 4242, t0);
        const auto v = l.closed(1, t0 + seconds(119), both);
        require(v.reason == CloseReason::Requested && v.via == CloseVia::Key && v.askedMs == 119000 && v.pid == 4242,
                "a close unmapped within 120 s reads requested, with its via, the time since and the pid");
    }
    for (const auto &[watch, reason] : {std::pair{both, CloseReason::Own}, std::pair{closeOnly, CloseReason::Unknown}}) {
        auto l = ledger();
        l.ask(1, CloseAsk::Close, CloseVia::Key, 4242, t0);
        require(isOwn(l.closed(1, t0 + milliseconds(120001), watch), reason),
                "a close past 120 s reads own with both hooks and unknown without, with no via, time or pid");
    }
    {
        auto l = ledger();
        l.ask(1, CloseAsk::Kill, CloseVia::Key, 7, t0);
        require(l.closed(1, t0 + seconds(9), both).reason == CloseReason::Killed, "a kill unmapped within 10 s reads killed");
        l.ask(1, CloseAsk::Kill, CloseVia::Key, 7, t0);
        require(isOwn(l.closed(1, t0 + milliseconds(10001), both), CloseReason::Own), "a kill past 10 s reads own");
    }
    {
        auto l = ledger();
        l.ask(1, CloseAsk::Close, CloseVia::Other, 7, t0);
        l.ask(1, CloseAsk::Kill, CloseVia::Click, 8, t0 + seconds(1));
        const auto killed = l.closed(1, t0 + seconds(2), both);
        require(killed.reason == CloseReason::Killed && killed.via == CloseVia::Click && killed.askedMs == 1000 &&
                    killed.pid == 8,
                "a live kill wins over a live close");
        l.ask(1, CloseAsk::Close, CloseVia::Other, 7, t0);
        l.ask(1, CloseAsk::Kill, CloseVia::Click, 8, t0 + seconds(1));
        const auto requested = l.closed(1, t0 + seconds(15), both);
        require(requested.reason == CloseReason::Requested && requested.via == CloseVia::Other &&
                    requested.askedMs == 15000 && requested.pid == 7,
                "an expired kill leaves a live close to decide");
    }
    {
        auto l = ledger();
        l.ask(1, CloseAsk::Close, CloseVia::Other, 7, t0);
        l.ask(1, CloseAsk::Close, CloseVia::Key, 7, t0 + seconds(100));
        const auto v = l.closed(1, t0 + seconds(200), both);
        require(v.reason == CloseReason::Requested && v.via == CloseVia::Key && v.askedMs == 100000,
                "a repeated close restarts the clock and its via wins");
    }
    {
        auto l = ledger();
        l.ask(1, CloseAsk::Close, CloseVia::Key, 7, t0);
        require(l.closed(1, t0 + seconds(1), both).reason == CloseReason::Requested, "the first close uses the request");
        require(isOwn(l.closed(1, t0 + seconds(2), both), CloseReason::Own), "a second close of the same id reads own");
        require(isOwn(l.closed(2, t0 + seconds(2), both), CloseReason::Own), "a close with no request reads own");
        for (const int pid : {0, -1}) {
            l.ask(3, CloseAsk::Close, CloseVia::Key, pid, t0);
            const auto v = l.closed(3, t0 + seconds(1), both);
            require(v.reason == CloseReason::Requested && !v.pid, "a pid of zero or less is stored as none");
        }
    }
    {
        auto l = ledger();
        for (uint64_t id = 1; id <= 130; ++id)
            l.ask(id, CloseAsk::Close, CloseVia::Key, 7, t0 + milliseconds(id));
        require(l.pendingCount() == PENDING_LIMIT, "at most 128 windows have a request pending");
        require(isOwn(l.closed(1, t0 + seconds(1), both), CloseReason::Own) &&
                    isOwn(l.closed(2, t0 + seconds(1), both), CloseReason::Own) &&
                    l.closed(3, t0 + seconds(1), both).reason == CloseReason::Requested,
                "past 128 pending windows, the ones asked longest ago are dropped");
    }
    {
        auto l = ledger();
        l.ask(1, CloseAsk::Kill, CloseVia::Key, 7, t0);
        l.ask(2, CloseAsk::Close, CloseVia::Key, 7, t0);
        l.ask(3, CloseAsk::Close, CloseVia::Key, 7, t0 + seconds(11));
        require(l.pendingCount() == 2, "a kill past 10 s is pruned on the next request; a live close stays");
        l.ask(4, CloseAsk::Close, CloseVia::Key, 7, t0 + seconds(132));
        require(l.pendingCount() == 1, "closes past 120 s are pruned on the next request");
    }
    // The record ring.
    {
        auto l = ledger();
        for (uint64_t seq = 1; seq <= 3; ++seq)
            require(l.append({}, t0) == seq, "append numbers records 1, 2, 3");
        for (int i = 0; i < 67; ++i)
            l.append({}, t0);
        const auto json = l.json(t0, true, both);
        size_t listed = 0;
        for (size_t at = json.find("\"seq\":"); at != std::string::npos; at = json.find("\"seq\":", at + 1))
            ++listed;
        require(listed == RECORD_LIMIT && json.contains("\"next\":71,\"oldest\":7,") &&
                    json.contains("{\"seq\":7,") && json.contains("{\"seq\":70,") && !json.contains("{\"seq\":6,"),
                "70 records keep the newest 64: oldest 7, next 71");
        require(l.json(t0 + minutes(10), true, both).contains("\"oldest\":7,"), "a record 10 minutes old is kept");
        require(l.json(t0 + minutes(10) + milliseconds(1), true, both) ==
                    R"({"instance":"0123456789abcdef","next":71,"oldest":71,"watch":{"close":true,"kill":true},"list":[]})",
                "records older than 10 minutes are dropped, and with none listed oldest is next");
    }
    // Text and JSON.
    require(CloseLedger::text("\xff\xfe") == "\xef\xbf\xbd\xef\xbf\xbd", "bytes that start no UTF-8 sequence become U+FFFD");
    require(CloseLedger::text("a\xc0\xaf" "b\xed\xa0\x80" "c\xf4\x90\x80\x80") ==
                "a\xef\xbf\xbd\xef\xbf\xbd" "b\xef\xbf\xbd\xef\xbf\xbd\xef\xbf\xbd" "c\xef\xbf\xbd\xef\xbf\xbd\xef\xbf\xbd\xef\xbf\xbd",
            "overlong forms, surrogates and code points past U+10FFFF are replaced");
    require(CloseLedger::text("caf\xc3\xa9 \xe2\x82\xac \xf0\x9f\x83\x8f") == "caf\xc3\xa9 \xe2\x82\xac \xf0\x9f\x83\x8f",
            "valid UTF-8 is kept");
    {
        std::string wide;
        for (int i = 0; i < 100; ++i)
            wide += "\xe2\x82\xac";
        const auto cut = CloseLedger::text(wide);
        require(cut.size() <= TEXT_LIMIT && cut.size() == 255 && CloseLedger::text(cut) == cut,
                "text is cut to 256 bytes at a code-point boundary");
    }
    require(CloseLedger::quote("a\"b\\c\n") == R"("a\"b\\c\u000a")", "quote escapes quotes, backslashes and controls");
    require(ledger().json(t0, false, none) ==
                R"({"instance":"0123456789abcdef","next":1,"oldest":1,"watch":{"close":false,"kill":false},"list":[]})",
            "an empty ledger's JSON");
    {
        auto l = ledger();
        CloseRecord inCard;
        inCard.address = 0x55d0a1b2c3e0;
        inCard.stableId = 0x40;
        inCard.pid = 41234;
        inCard.initialClass = "org.gnome.TextEditor";
        inCard.workspaceId = 3;
        inCard.workspaceName = "3";
        inCard.place = {12, 1, 0, 3, false};
        inCard.verdict = {CloseReason::Requested, CloseVia::Key, 140, 41234};
        l.append(inCard, t0);
        CloseRecord cover;
        cover.address = 0x55d0a1b2c3d0;
        cover.stableId = 0x3f;
        cover.initialClass = "org.gnome.Nautilus";
        cover.workspaceId = -98;
        cover.workspaceName = "special:park";
        cover.workspaceSpecial = true;
        cover.place = {12, std::nullopt, std::nullopt, std::nullopt, true};
        cover.dissolved = true;
        cover.verdict = {CloseReason::Own, std::nullopt, std::nullopt, std::nullopt};
        l.append(cover, t0 + milliseconds(30));
        CloseRecord loose;
        loose.address = 0x1;
        loose.stableId = 0x2137;
        loose.initialClass = "Lua error \"x\"";
        loose.verdict = {CloseReason::Killed, CloseVia::Click, 5, std::nullopt};
        l.append(loose, t0 + milliseconds(830));
        const std::string head = R"({"instance":"0123456789abcdef","next":4,"oldest":1,"watch":{"close":true,"kill":true},"list":[)";
        const std::string first =
            R"({"seq":1,"age_ms":830,"address":"0x55d0a1b2c3e0","stable_id":"40","pid":41234,)"
            R"("initial_class":"org.gnome.TextEditor","workspace":{"id":3,"name":"3","special":false},)"
            R"("card":12,"face":1,"index":0,"faces":3,"cover":false,"dissolved":false,"reason":"requested","via":"key","asked_ms":140})";
        const std::string second =
            R"({"seq":2,"age_ms":800,"address":"0x55d0a1b2c3d0","stable_id":"3f","pid":null,)"
            R"("initial_class":"org.gnome.Nautilus","workspace":{"id":-98,"name":"special:park","special":true},)"
            R"("card":12,"face":null,"index":null,"faces":null,"cover":true,"dissolved":true,"reason":"own","via":null,"asked_ms":null})";
        const std::string third =
            R"({"seq":3,"age_ms":0,"address":"0x1","stable_id":"2137","pid":null,"initial_class":"Lua error \"x\"",)"
            R"("workspace":null,"card":null,"face":null,"index":null,"faces":null,"cover":false,"dissolved":false,)"
            R"("reason":"killed","via":"click","asked_ms":5})";
        const auto json = l.json(t0 + milliseconds(830), true, both);
        require(json == head + first + ',' + second + ',' + third + "]}",
                "records list every field in order: in a card, the cover, and in no card with no workspace");
        const auto halfHooked = l.json(t0 + milliseconds(830), false, closeOnly);
        require(halfHooked.contains(R"("cover":true,"dissolved":true,"reason":"unknown","via":null)") &&
                    !halfHooked.contains(R"("reason":"own")") && halfHooked.contains(R"("watch":{"close":true,"kill":false})"),
                "without both hooks no record claims own");
    }
}

int main() {
    using namespace Hyprflip;
    closeLedger();
    require(balancedSplit(840, {200, 2000}, {200, 2000}) == 420, "unfold keeps balanced faces when both fit");
    require(balancedSplit(840, {200, 2000}, {530, 2000}) == 310, "a tall back face gets enough room on a laptop");
    require(balancedSplit(1400, {860, 2000}, {450, 2000}) == 860, "a wide front face keeps its minimum width");
    require(balancedSplit(840, {200, 300}, {200, 2000}) == 300, "unfold respects a face maximum size");
    require(!balancedSplit(840, {420, 2000}, {430, 2000}), "unfold refuses when the combined minima cannot fit");
    require(!balancedSplit(840, {200, 300}, {200, 400}), "unfold refuses when both maxima are too small");
    require(balancedSplit(841, {420.2, 2000}, {419.8, 2000}) == 421, "fractional minima retain whole-pixel boundaries");
    require(sharedSplit(900, {{100, 2000}, {100, 2000}, {100, 2000}}) == std::vector<double>{300, 300, 300},
            "three faces unfold in equal thirds when they fit");
    require(sharedSplit(900, {{500, 2000}, {100, 2000}, {100, 2000}}) == std::vector<double>{500, 200, 200},
            "a wide face keeps its minimum and the others share the rest");
    require(sharedSplit(1000, {{100, 200}, {100, 2000}, {100, 2000}, {100, 2000}}) ==
                std::vector<double>{200, 267, 267, 266},
            "a face at its maximum gives its room to the others, in whole pixels");
    require(parseAccent("#F78DBB") == 0xfff78dbbu && parseAccent("#00aa11") == 0xff00aa11u, "accent parses #RRGGBB");
    require(!parseAccent("") && !parseAccent("F78DBB") && !parseAccent("#F78DB") && !parseAccent("#F78DBBAA") &&
                !parseAccent("#G78DBB"),
            "accent rejects anything but #RRGGBB");
    // Keyboard and menu actions wait for any input in progress. Actions by id
    // wait only for input that their move would disturb.
    const auto input = [](std::initializer_list<bool InputState::*> set) {
        InputState state{};
        for (const auto field : set)
            state.*field = true;
        return state;
    };
    require(!interactiveBusy(input({})) && !scriptedBusy(input({})), "idle input refuses nothing");
    for (const auto field :
         {&InputState::locked, &InputState::grab, &InputState::dnd, &InputState::constrained, &InputState::held})
        require(interactiveBusy(input({field})), "keyboard and menu actions wait for any input in progress");
    require(!scriptedBusy(input({&InputState::locked})), "a locked screen does not stop actions by id");
    require(!scriptedBusy(input({&InputState::held})), "a button held over another window does not stop actions by id");
    for (const auto field : {&InputState::grab, &InputState::dnd, &InputState::constrained})
        require(scriptedBusy(input({field})), "a grab, drag-and-drop or constrained pointer stops actions by id");
    require(scriptedBusy(input({&InputState::held, &InputState::heldOverTarget})),
            "a button held over the card stops actions by id");
    Timeline t(280);
    require(!t.finished() && !t.secondSide() && t.angle() == 0, "initial front");
    t.advance(139);
    require(!t.secondSide() && t.angle() > 1.5, "outgoing edge");
    t.advance(2);
    require(t.secondSide() && t.angle() < -1.5, "incoming edge without mirrored face");
    t.reverse();
    t.advance(2);
    require(t.secondSide(), "reversal brakes before changing direction");
    t.advance(60);
    require(!t.secondSide(), "reverse returns across the actual edge");
    t.advance(1000);
    require(t.finished() && t.progress() == 0, "reverse settles to original");
    t.reverse();
    t.advance(1000);
    require(t.finished() && t.secondSide() && t.angle() == 0, "stall settles cleanly");
    t.reverse();
    t.advance(-100);
    require(t.progress() == 1, "negative time cannot advance");
    // A one-millisecond step must meet rest gently at either endpoint. This
    // guards the abrupt acceleration of the previous cubic ease, not a copy
    // of the new polynomial's implementation.
    Timeline start(420), end(420);
    start.advance(1);
    end.advance(419);
    require(start.angle() < 0.000001, "departure acceleration approaches zero");
    require(std::abs(end.angle()) < 0.000001, "arrival acceleration approaches zero");
    require(std::abs(start.angle() + end.angle()) < 1e-12, "turn is symmetric");
    double previous = 0;
    Timeline smooth(420);
    for (int i = 1; i <= 420; ++i) {
        smooth.advance(1);
        const double angle = smooth.angle() + (smooth.secondSide() ? std::numbers::pi : 0.0);
        require(angle >= previous, "full physical angle is monotonic through the side change");
        previous = angle;
    }
    const auto physical = [](const Timeline &turn) {
        return turn.angle() + (turn.secondSide() ? std::numbers::pi : 0.0);
    };
    for (double elapsed : {80.0, 209.0, 211.0, 350.0}) {
        Timeline reversing(420);
        reversing.advance(elapsed);
        const auto before = physical(reversing);
        reversing.advance(.001);
        const auto atReverse = physical(reversing);
        const auto incoming = atReverse - before;
        reversing.reverse();
        require(physical(reversing) == atReverse, "retarget preserves the physical angle");
        reversing.advance(.001);
        const auto outgoing = physical(reversing) - atReverse;
        require(std::abs(outgoing - incoming) < incoming * .002, "retarget preserves angular velocity");
        reversing.advance(1000);
        require(reversing.finished() && !reversing.secondSide(), "retarget settles on the requested face");
    }
    // Dropped frames must not change the trajectory, even when the coast hits
    // an endpoint before turning back. Exercise repeated retargeting as well.
    for (double initial : {1.0, 200.0, 419.0}) {
        for (double interval : {15.0, 60.0, 200.0, 700.0}) {
            Timeline coarse(420), fine(420);
            coarse.advance(initial);
            fine.advance(initial);
            for (int retarget = 0; retarget < 5; ++retarget) {
                coarse.reverse();
                fine.reverse();
                coarse.advance(interval);
                for (int frame = 0; frame < int(interval); ++frame)
                    fine.advance(1);
                require(std::abs(physical(coarse) - physical(fine)) < 1e-10,
                        "reversals are independent of frame subdivision");
                require(coarse.progress() >= 0 && coarse.progress() <= 1, "reversal stays within the card's two faces");
            }
        }
    }
    for (int direction : {-1, 1}) {
        for (int i = 0; i <= 1000; ++i) {
            const double a = direction * i * std::numbers::pi / 2000.0;
            const double s = std::sin(a), c = std::cos(a);
            for (double d : {2.0, 3.2, 5.0, 8.0}) {
                const double k = projectionScale(s, d, .035);
                for (double x : {-1.0, -.4, 0.0, .6, 1.0}) {
                    for (double y : {-1.0, 0.0, 1.0}) {
                        double px = c * x * k / (d + x * s), py = y * k / (d + x * s);
                        require(std::abs(px) <= 1.000001 && std::abs(py) <= 1.000001, "projection fits damage bounds");
                        if (c < .0001)
                            continue;
                        double ix = px * d / (k * c - px * s), iy = py * (d + ix * s) / k;
                        require(std::abs(ix - x) < 1e-8 && std::abs(iy - y) < 1e-8, "inverse projection round trip");
                    }
                }
            }
        }
    }
    std::cout << "Close ledger, face size constraints, input guards, timeline, reversals, stalls and perspective bounds "
                 "passed\n";
}
