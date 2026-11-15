#pragma once
#include <cmath>
#include <cstdint>

enum class FaceState : uint8_t { Idle, Happy, Excited, Love, Curious, Surprised, Sad, Angry, Sleepy, Wink, Listening, Thinking, Speaking, Offline, Error };
// Pure, allocation-free model. Call from one owner task; pass monotonic milliseconds.
struct BellaFace {
    FaceState status = FaceState::Idle, emotion = FaceState::Idle;
    uint32_t until = 0, last_touch = 0, next_blink = 2800, seed = 17;
    bool touched = false;
    float openness = 1, width = 1, gaze = 0;
    void touch(unsigned pad, uint32_t now) {
        if (pad > 3 || (touched && uint32_t(now-last_touch) < 250)) return;
        touched = true; last_touch = now;
        const FaceState map[] = {FaceState::Happy, FaceState::Love, FaceState::Curious, FaceState::Wink};
        emotion = map[pad]; until = now + 1800;
    }
    FaceState state(uint32_t now) const {
        if (status != FaceState::Idle) return status;
        return int32_t(until-now) > 0 ? emotion : FaceState::Idle;
    }
    void tick(uint32_t now, float dt) {
        auto s = state(now);
        if (int32_t(now-next_blink) > 180) {
            seed = seed*1664525u+1013904223u;
            next_blink = now+2400+seed%3200;
        }
        float blink = int32_t(now-next_blink) >= 0 ? std::fabs(float(now-next_blink)/90.f-1.f) : 1.f;
        float target = (s==FaceState::Sleepy ? .35f : s==FaceState::Happy ? .22f : s==FaceState::Surprised ? 1.25f : 1.f)*blink;
        float a = 1.f-std::exp(-12.f*dt);
        openness += (target-openness)*a;
        width += ((s==FaceState::Love ? 1.12f : 1.f)-width)*a;
        gaze += ((s==FaceState::Thinking || s==FaceState::Curious ? .3f : 0.f)-gaze)*a;
    }
};
