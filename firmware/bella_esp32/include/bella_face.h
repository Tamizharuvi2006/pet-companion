#pragma once
#include <cmath>
#include <cstdint>

enum class FaceState : uint8_t { Idle, Happy, Excited, Love, Curious, Surprised, Sad, Angry, Sleepy, Wink, Listening, Thinking, Speaking, Offline, Error };
struct BellaFaceGeometry {
    float openness=1,width=1,gaze_x=0,gaze_y=0,pupil=1,warmth=0;
    bool offline=false;
    FaceState expression=FaceState::Idle;
    float left_open=1,right_open=1,eye_curve=0,eye_angle=0;
    bool crossed_pupils=false;
    float animation_phase=0;
};
// Pure, allocation-free model. Call from one owner task; pass monotonic milliseconds.
struct BellaFace {
    FaceState status = FaceState::Idle, emotion = FaceState::Idle;
    uint32_t until = 0, last_touch = 0, next_blink = 2800, seed = 17;
    bool touched = false;
    float openness = 1, width = 1, gaze = 0, gaze_y=0,pupil=1,warmth=0;
    float left_open=1,right_open=1,curve=0,angle=0;
    void touch(unsigned pad, uint32_t now) {
        if (pad > 3 || (touched && uint32_t(now-last_touch) < 250)) return;
        touched = true; last_touch = now;
        const FaceState map[] = {FaceState::Happy, FaceState::Love, FaceState::Curious, FaceState::Wink};
        emotion = map[pad]; until = now + 1800;
    }
    FaceState state(uint32_t now) const {
        // Offline is retained as a separate indicator while local touch animates.
        if(status==FaceState::Offline&&int32_t(until-now)>0)return emotion;
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
        const float speak = .5f + .5f * std::sin(float(now) * .0045f);
        float target = (s==FaceState::Sleepy ? .32f : s==FaceState::Happy ? .18f : s==FaceState::Offline ? .10f : s==FaceState::Thinking ? .88f : s==FaceState::Speaking ? .18f + .82f * speak : s==FaceState::Sad ? .65f : s==FaceState::Angry ? .62f : s==FaceState::Surprised ? 1.25f : s==FaceState::Listening ? 1.08f : 1.f)*blink;
        float a = 1.f-std::exp(-12.f*dt);
        openness += (target-openness)*a;
        width += ((s==FaceState::Love ? 1.12f : 1.f)-width)*a;
        gaze += ((s==FaceState::Thinking || s==FaceState::Curious ? .3f : 0.f)-gaze)*a;
        gaze_y+=((s==FaceState::Thinking?-.42f:0.f)-gaze_y)*a;
        pupil+=((s==FaceState::Surprised?.7f:s==FaceState::Love?1.2f:1.f)-pupil)*a;
        warmth+=((s==FaceState::Love?1.f:0.f)-warmth)*a;
        left_open+=((s==FaceState::Wink?openness*.05f:openness)-left_open)*a;
        right_open+=((s==FaceState::Curious?openness*.7f:s==FaceState::Thinking?openness*.82f:openness)-right_open)*a;
        curve+=((s==FaceState::Happy?-.4f:s==FaceState::Sleepy?.15f:0.f)-curve)*a;
        angle+=((s==FaceState::Angry?.2f:s==FaceState::Sad?-.15f:0.f)-angle)*a;
    }
    BellaFaceGeometry geometry(uint32_t now) const {
        BellaFaceGeometry result{openness,width,gaze,gaze_y,pupil,warmth,status==FaceState::Offline,state(now)};
        result.left_open=left_open;result.right_open=right_open;
        result.eye_curve=curve;result.eye_angle=angle;
        result.crossed_pupils=result.expression==FaceState::Error;
        result.animation_phase=float(now % 60000U) * .006f;
        return result;
    }
};
