#pragma once

#include <cstddef>
#include <cstdint>

bool bella_audio_init();
void bella_audio_flush_playback();
void bella_audio_begin_turn(uint32_t turn_id);
bool bella_audio_finish_turn(uint32_t turn_id);
bool bella_audio_enqueue_speaker(
    uint32_t turn_id,
    uint32_t sequence,
    const char *trace_id,
    int64_t chunk_started_us,
    const uint8_t *pcm,
    size_t length);
bool bella_audio_end_speaker_chunk(uint32_t turn_id, const char *trace_id, int64_t chunk_started_us);
uint32_t bella_audio_dropped_frames();
bool bella_audio_input_ready();
bool bella_audio_output_ready();
uint16_t bella_audio_last_mic_rms();
uint32_t bella_audio_mic_frame_count();
uint32_t bella_audio_tx_eof_count();
