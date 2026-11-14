#pragma once

#include <cstddef>
#include <cstdint>

void bella_ws_init();
void bella_ws_start();
bool bella_ws_is_ready();
bool bella_ws_is_recording();
uint32_t bella_ws_current_turn_id();
bool bella_ws_send_control(const char *json);
bool bella_ws_send_audio(const uint8_t *pcm, size_t length, uint32_t turn_id, uint32_t sequence);
uint32_t bella_ws_begin_recording();
void bella_ws_end_recording(uint32_t turn_id);
void bella_ws_cancel(uint32_t turn_id);
