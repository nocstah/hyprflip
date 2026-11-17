#pragma once
// Why an app went away. Hyprland unmaps every window the same way and records no
// reason, so Hyprflip notes each close request and kill when it happens, keyed by
// the window's stable id, and decides at the close whether one was pending.
// STL only: tests/core_test.cpp includes this header with fake times.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <deque>
#include <format>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>

namespace Hyprflip {
using Clock = std::chrono::steady_clock;

inline constexpr auto CLOSE_HORIZON = std::chrono::seconds(120); // a close request counts this long after the latest one
inline constexpr auto KILL_HORIZON = std::chrono::seconds(10);
inline constexpr size_t PENDING_LIMIT = 128; // windows with a pending request; oldest latest-request dropped
inline constexpr size_t RECORD_LIMIT = 64;
inline constexpr auto RECORD_AGE = std::chrono::minutes(10);
inline constexpr size_t TEXT_LIMIT = 256; // bytes, after UTF-8 cleaning

enum class CloseAsk { Close, Kill };
// Who asked: a key bind running, a click in Hyprland's kill mode, or anything else
// (hyprctl dispatch, a title-bar button, a close-all script, a gesture or a taskbar).
enum class CloseVia { Key, Click, Other };
enum class CloseReason { Requested, Killed, Own, Unknown };
// Which request hooks are live. Without both, a close with nothing pending is
// unknown rather than the app's own doing.
struct CloseWatch {
    bool close = false, kill = false;
    bool complete() const { return close && kill; }
};
struct CloseVerdict {
    CloseReason reason = CloseReason::Unknown;
    std::optional<CloseVia> via;
    std::optional<int64_t> askedMs;
    std::optional<int> pid;
};
// Where the window was just before it closed, in status's own-face numbering.
struct ClosePlace { // null optionals = not in a card
    std::optional<uint64_t> card;
    std::optional<unsigned> face, index, faces;
    bool cover = false;
};
struct CloseRecord {
    uint64_t seq = 0;
    Clock::time_point at;
    uintptr_t address = 0;
    uint64_t stableId = 0;
    std::optional<int> pid;
    std::string initialClass;
    std::optional<int64_t> workspaceId; // null: no workspace, and the record says so
    std::string workspaceName;
    bool workspaceSpecial = false;
    ClosePlace place;
    bool dissolved = false;
    CloseVerdict verdict;
};

class CloseLedger {
  public:
    explicit CloseLedger(std::string instance) : m_instance(std::move(instance)) {}

    void ask(uint64_t stableId, CloseAsk kind, CloseVia via, int pid, Clock::time_point now) {
        std::erase_if(m_pending, [&](const auto &entry) { return entry.second.expired(now); });
        if (!m_pending.contains(stableId) && m_pending.size() >= PENDING_LIMIT) {
            const auto oldest = std::ranges::min_element(
                m_pending, [](const auto &a, const auto &b) { return a.second.latest() < b.second.latest(); });
            m_pending.erase(oldest);
        }
        auto &slot = kind == CloseAsk::Kill ? m_pending[stableId].kill : m_pending[stableId].close;
        slot = Slot{now, via, pid > 0 ? std::optional<int>(pid) : std::nullopt};
    }

    // Consumes the window's pending entry: a live kill wins, then a live close.
    CloseVerdict closed(uint64_t stableId, Clock::time_point now, const CloseWatch &watch) {
        std::optional<Pending> entry;
        if (const auto it = m_pending.find(stableId); it != m_pending.end()) {
            entry = it->second;
            m_pending.erase(it);
        }
        const auto verdict = [&](CloseReason reason, const Slot &slot) {
            return CloseVerdict{reason, slot.via,
                                std::chrono::duration_cast<std::chrono::milliseconds>(now - slot.at).count(), slot.pid};
        };
        if (entry && entry->kill && now - entry->kill->at <= KILL_HORIZON)
            return verdict(CloseReason::Killed, *entry->kill);
        if (entry && entry->close && now - entry->close->at <= CLOSE_HORIZON)
            return verdict(CloseReason::Requested, *entry->close);
        return {watch.complete() ? CloseReason::Own : CloseReason::Unknown, std::nullopt, std::nullopt, std::nullopt};
    }

    uint64_t append(CloseRecord record, Clock::time_point now) {
        record.seq = m_next++;
        record.at = now;
        m_records.push_back(std::move(record));
        prune(now);
        return m_records.back().seq;
    }

    // The "closes" object of status. `reasons` is whether both hooks are live;
    // without them no record claims `own`.
    std::string json(Clock::time_point now, bool reasons, const CloseWatch &watch) {
        prune(now);
        std::string out = std::format("{{\"instance\":{},\"next\":{},\"oldest\":{},\"watch\":{{\"close\":{},\"kill\":{}}},"
                                      "\"list\":[",
                                      quote(m_instance), m_next, m_records.empty() ? m_next : m_records.front().seq,
                                      watch.close, watch.kill);
        for (const auto &r : m_records) {
            if (&r != &m_records.front())
                out += ',';
            const auto reason = !reasons && r.verdict.reason == CloseReason::Own ? CloseReason::Unknown : r.verdict.reason;
            out += std::format("{{\"seq\":{},\"age_ms\":{},\"address\":\"0x{:x}\",\"stable_id\":\"{:x}\",\"pid\":{},"
                               "\"initial_class\":{},\"workspace\":{},",
                               r.seq, std::chrono::duration_cast<std::chrono::milliseconds>(now - r.at).count(),
                               r.address, r.stableId, number(r.pid), quote(r.initialClass),
                               r.workspaceId ? std::format("{{\"id\":{},\"name\":{},\"special\":{}}}", *r.workspaceId,
                                                           quote(r.workspaceName), r.workspaceSpecial)
                                             : std::string("null"));
            out += std::format("\"card\":{},\"face\":{},\"index\":{},\"faces\":{},\"cover\":{},\"dissolved\":{},"
                               "\"reason\":\"{}\",\"via\":{},\"asked_ms\":{}}}",
                               number(r.place.card), number(r.place.face), number(r.place.index), number(r.place.faces),
                               r.place.cover, r.dissolved, name(reason),
                               r.verdict.via ? std::format("\"{}\"", name(*r.verdict.via)) : std::string("null"),
                               number(r.verdict.askedMs));
        }
        return out + "]}";
    }

    // Windows with a request pending; for tests.
    size_t pendingCount() const { return m_pending.size(); }

    // Valid UTF-8 (each byte that starts no valid sequence becomes U+FFFD), cut to
    // TEXT_LIMIT bytes at a code-point boundary.
    static std::string text(std::string_view raw) {
        std::string out;
        size_t i = 0;
        while (i < raw.size()) {
            const auto byte = [&](size_t k) { return static_cast<unsigned char>(raw[k]); };
            const unsigned char lead = byte(i);
            size_t length = lead < 0x80 ? 1 : lead >= 0xc2 && lead <= 0xdf ? 2 : lead >= 0xe0 && lead <= 0xef ? 3
                                          : lead >= 0xf0 && lead <= 0xf4 ? 4 : 0;
            bool valid = length && i + length <= raw.size();
            for (size_t k = 1; valid && k < length; ++k)
                valid = (byte(i + k) & 0xc0) == 0x80;
            // Overlong forms, UTF-16 surrogates and code points past U+10FFFF.
            if (valid && length == 3)
                valid = !(lead == 0xe0 && byte(i + 1) < 0xa0) && !(lead == 0xed && byte(i + 1) >= 0xa0);
            if (valid && length == 4)
                valid = !(lead == 0xf0 && byte(i + 1) < 0x90) && !(lead == 0xf4 && byte(i + 1) >= 0x90);
            const std::string_view piece = valid ? raw.substr(i, length) : std::string_view("\xef\xbf\xbd");
            if (out.size() + piece.size() > TEXT_LIMIT)
                break;
            out += piece;
            i += valid ? length : 1;
        }
        return out;
    }
    static std::string quote(std::string_view raw) {
        std::string out = "\"";
        for (const unsigned char c : text(raw)) {
            if (c == '"' || c == '\\') {
                out += '\\';
                out += char(c);
            } else if (c < 0x20)
                out += std::format("\\u{:04x}", c);
            else
                out += char(c);
        }
        return out + '"';
    }

  private:
    struct Slot {
        Clock::time_point at;
        CloseVia via;
        std::optional<int> pid;
    };
    struct Pending {
        std::optional<Slot> close, kill;
        Clock::time_point latest() const {
            return std::max(close ? close->at : Clock::time_point::min(), kill ? kill->at : Clock::time_point::min());
        }
        bool expired(Clock::time_point now) const {
            return (!close || now - close->at > CLOSE_HORIZON) && (!kill || now - kill->at > KILL_HORIZON);
        }
    };
    void prune(Clock::time_point now) {
        std::erase_if(m_records, [&](const CloseRecord &r) { return now - r.at > RECORD_AGE; });
        while (m_records.size() > RECORD_LIMIT)
            m_records.pop_front();
    }
    template <class T> static std::string number(const std::optional<T> &value) {
        return value ? std::to_string(*value) : "null";
    }
    static const char *name(CloseReason reason) {
        switch (reason) {
            case CloseReason::Requested: return "requested";
            case CloseReason::Killed: return "killed";
            case CloseReason::Own: return "own";
            case CloseReason::Unknown: break;
        }
        return "unknown";
    }
    static const char *name(CloseVia via) {
        switch (via) {
            case CloseVia::Key: return "key";
            case CloseVia::Click: return "click";
            case CloseVia::Other: break;
        }
        return "other";
    }
    std::string m_instance;
    std::unordered_map<uint64_t, Pending> m_pending;
    std::deque<CloseRecord> m_records;
    uint64_t m_next = 1;
};
} // namespace Hyprflip
