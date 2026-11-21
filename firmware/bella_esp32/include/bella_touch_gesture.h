#pragma once

#include <cstdint>

enum class BellaTouch4Action : uint8_t { None, ShortTap, StartPushToTalk, StopPushToTalk };

// Pure state for a momentary active-level pad. A toggle/latch TTP223 mode is
// not compatible with this gesture and must remain disabled at build time.
class BellaTouch4Gesture {
public:
    void press(uint32_t now_ms) {
        pressed_ = true;
        long_fired_ = false;
        pressed_at_ = now_ms;
    }

    BellaTouch4Action poll(uint32_t now_ms, uint32_t threshold_ms, bool enabled) {
        if (!enabled || !pressed_ || long_fired_ || uint32_t(now_ms - pressed_at_) < threshold_ms) {
            return BellaTouch4Action::None;
        }
        long_fired_ = true;
        return BellaTouch4Action::StartPushToTalk;
    }

    BellaTouch4Action release() {
        if (!pressed_) return BellaTouch4Action::None;
        pressed_ = false;
        if (long_fired_) return BellaTouch4Action::StopPushToTalk;
        return BellaTouch4Action::ShortTap;
    }

private:
    bool pressed_ = false;
    bool long_fired_ = false;
    uint32_t pressed_at_ = 0;
};
