#pragma once

#include <atomic>
#include <cstdint>

enum class BellaState : uint8_t {
    Booting,
    Connecting,
    Idle,
    Listening,
    Processing,
    Speaking,
    Muted,
    Error,
    Disconnected,
};

void bella_runtime_init();
void bella_set_state(BellaState state);
BellaState bella_get_state();
const char *bella_state_name(BellaState state);
bool bella_is_muted();
bool bella_toggle_muted();
void bella_set_presence(bool present, uint16_t distance_mm);
void bella_set_pet_reaction();
