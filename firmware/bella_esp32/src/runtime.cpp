#include "bella_runtime.h"

#include "bella_device_ws.h"
#include "bella_display.h"
#include "bella_servo.h"

#include <cstdio>

static std::atomic<BellaState> g_state{BellaState::Booting};
static std::atomic<bool> g_muted{false};
static std::atomic<bool> g_presence{false};
static std::atomic<uint16_t> g_distance_mm{0};

void bella_runtime_init() {
    g_state.store(BellaState::Booting);
}

const char *bella_state_name(BellaState state) {
    switch (state) {
        case BellaState::Booting: return "BOOTING";
        case BellaState::Connecting: return "CONNECTING";
        case BellaState::Idle: return "IDLE";
        case BellaState::Listening: return "LISTENING";
        case BellaState::Processing: return "PROCESSING";
        case BellaState::Speaking: return "SPEAKING";
        case BellaState::Muted: return "MUTED";
        case BellaState::Error: return "ERROR";
        case BellaState::Disconnected: return "DISCONNECTED";
    }
    return "ERROR";
}

BellaState bella_get_state() {
    return g_state.load();
}

bool bella_is_muted() {
    return g_muted.load();
}

void bella_set_state(BellaState state) {
    g_state.store(state);
    bella_display_set_state(state);
    char message[256];
    std::snprintf(
        message,
        sizeof(message),
        "{\"type\":\"sensor_event\",\"version\":1,\"state\":\"%s\",\"sensors\":{\"muted\":%s,\"presence\":%s,\"distance_mm\":%u}}",
        bella_state_name(state),
        bella_is_muted() ? "true" : "false",
        g_presence.load() ? "true" : "false",
        static_cast<unsigned>(g_distance_mm.load()));
    bella_ws_send_control(message);
}

bool bella_toggle_muted() {
    const bool muted = !g_muted.load();
    g_muted.store(muted);
    const BellaState current = g_state.load();
    const BellaState next = current == BellaState::Idle || current == BellaState::Muted
        ? (muted ? BellaState::Muted : BellaState::Idle)
        : current;
    bella_set_state(next);
    return muted;
}

void bella_set_presence(bool present, uint16_t distance_mm) {
    g_presence.store(present);
    g_distance_mm.store(distance_mm);
    char message[256];
    std::snprintf(
        message,
        sizeof(message),
        "{\"type\":\"sensor_event\",\"version\":1,\"state\":\"%s\",\"sensors\":{\"presence\":%s,\"distance_mm\":%u,\"muted\":%s}}",
        bella_state_name(bella_get_state()),
        present ? "true" : "false",
        static_cast<unsigned>(distance_mm),
        bella_is_muted() ? "true" : "false");
    bella_ws_send_control(message);
}

void bella_set_pet_reaction() {
    bella_servo_emote(1);
    char message[128];
    std::snprintf(message, sizeof(message),
                  "{\"type\":\"sensor_event\",\"version\":1,\"state\":\"%s\",\"sensors\":{\"pet_touch\":true}}",
                  bella_state_name(g_state.load()));
    bella_ws_send_control(message);
}
