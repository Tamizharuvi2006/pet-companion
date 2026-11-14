#include "bella_audio_i2s.h"

#include "bella_config.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"

#include "driver/i2s_std.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include <array>
#include <atomic>
#include <cstdio>
#include <cstring>

static const char *TAG = "bella_audio";
static i2s_chan_handle_t g_i2s_tx = nullptr;
static i2s_chan_handle_t g_i2s_rx = nullptr;
static QueueHandle_t g_playback_queue = nullptr;
static std::atomic<uint32_t> g_dropped_frames{0};
static constexpr size_t PLAYBACK_QUEUE_DEPTH = 8;

struct SpeakerFrame {
    uint32_t turn_id = 0;
    uint32_t sequence = 0;
    int64_t chunk_started_us = 0;
    bool end_of_chunk = false;
    char trace_id[32]{};
    size_t samples = 0;
    int16_t pcm[BELLA_AUDIO_FRAME_SAMPLES]{};
};

static void speaker_task(void *) {
    SpeakerFrame frame{};
    std::array<int32_t, BELLA_AUDIO_FRAME_SAMPLES * 2> stereo{};
    while (true) {
        if (xQueueReceive(g_playback_queue, &frame, portMAX_DELAY) != pdTRUE) continue;
        if (frame.end_of_chunk) {
            ESP_LOGI(TAG,
                     "voice_timing trace_id=%s stage=device_i2s_queue_drained turn_id=%lu offset_from_chunk_start_ms=%lld",
                     frame.trace_id, static_cast<unsigned long>(frame.turn_id),
                     static_cast<long long>((esp_timer_get_time() - frame.chunk_started_us) / 1000));
            continue;
        }
        if (frame.samples == 0) continue;
        for (size_t i = 0; i < frame.samples; ++i) {
            const int32_t value = bella_is_muted() ? 0 : static_cast<int32_t>(frame.pcm[i]) * 65536;
            stereo[i * 2] = value;
            stereo[i * 2 + 1] = value;
        }
        size_t bytes_written = 0;
        const esp_err_t result = i2s_channel_write(
            g_i2s_tx,
            stereo.data(),
            frame.samples * 2 * sizeof(int32_t),
            &bytes_written,
            pdMS_TO_TICKS(150));
        if (frame.sequence == 0) {
            ESP_LOGI(TAG,
                     "voice_timing trace_id=%s stage=device_i2s_first_write turn_id=%lu offset_from_chunk_start_ms=%lld bytes=%u",
                     frame.trace_id, static_cast<unsigned long>(frame.turn_id),
                     static_cast<long long>((esp_timer_get_time() - frame.chunk_started_us) / 1000),
                     static_cast<unsigned>(bytes_written));
        }
        if (result != ESP_OK || bytes_written != frame.samples * 2 * sizeof(int32_t)) {
            g_dropped_frames.fetch_add(1);
            ESP_LOGW(TAG, "I2S playback short write; cumulative_drops=%lu",
                     static_cast<unsigned long>(g_dropped_frames.load()));
        }
    }
}

static void microphone_task(void *) {
    alignas(4) std::array<int32_t, 480> interleaved{}; // 240 stereo 32-bit frames
    std::array<int16_t, BELLA_AUDIO_FRAME_SAMPLES> output{};
    size_t output_samples = 0;
    uint32_t sequence = 0;
    uint32_t observed_turn = 0;
    while (true) {
        size_t bytes_read = 0;
        const esp_err_t result = i2s_channel_read(
            g_i2s_rx, interleaved.data(), sizeof(interleaved), &bytes_read, pdMS_TO_TICKS(80));
        if (result != ESP_OK || bytes_read < 2 * sizeof(int32_t)) continue;

        const bool recording = bella_ws_is_recording();
        const uint32_t turn_id = bella_ws_current_turn_id();
        if (!recording || turn_id == 0) {
            output_samples = 0;
            observed_turn = 0;
            continue; // Keep draining the RX DMA while idle; never retain stale mic audio.
        }
        if (turn_id != observed_turn) {
            observed_turn = turn_id;
            output_samples = 0;
            sequence = 0;
        }

        const size_t stereo_frames = bytes_read / (2 * sizeof(int32_t));
        for (size_t i = 0; i < stereo_frames; ++i) {
            // INMP441 L/R is wired to GND: read the left slot. Its 24-bit sample
            // is left-aligned in the configured 32-bit standard-mode slot.
            const int32_t sample = interleaved[i * 2];
            output[output_samples++] = static_cast<int16_t>(sample >> 16);
            if (output_samples == output.size()) {
                if (!bella_ws_send_audio(reinterpret_cast<const uint8_t *>(output.data()),
                                         BELLA_AUDIO_FRAME_BYTES, turn_id, sequence++)) {
                    g_dropped_frames.fetch_add(1);
                }
                output_samples = 0;
            }
        }
    }
}

bool bella_audio_init() {
    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel_config.dma_desc_num = 6;
    channel_config.dma_frame_num = 240;
    esp_err_t result = i2s_new_channel(&channel_config, &g_i2s_tx, &g_i2s_rx);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Could not allocate shared full-duplex I2S channels: %s", esp_err_to_name(result));
        return false;
    }

    i2s_std_config_t standard_config{};
    standard_config.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(BELLA_AUDIO_SAMPLE_RATE_HZ);
    standard_config.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
        I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO);
    standard_config.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
    standard_config.gpio_cfg.mclk = I2S_GPIO_UNUSED;
    standard_config.gpio_cfg.bclk = static_cast<gpio_num_t>(BELLA_PIN_I2S_BCLK);
    standard_config.gpio_cfg.ws = static_cast<gpio_num_t>(BELLA_PIN_I2S_WS);
    standard_config.gpio_cfg.dout = static_cast<gpio_num_t>(BELLA_PIN_I2S_SPEAKER_DATA);
    standard_config.gpio_cfg.din = static_cast<gpio_num_t>(BELLA_PIN_I2S_MIC_DATA);
    standard_config.gpio_cfg.invert_flags.mclk_inv = false;
    standard_config.gpio_cfg.invert_flags.bclk_inv = false;
    standard_config.gpio_cfg.invert_flags.ws_inv = false;

    result = i2s_channel_init_std_mode(g_i2s_rx, &standard_config);
    if (result == ESP_OK) result = i2s_channel_init_std_mode(g_i2s_tx, &standard_config);
    if (result == ESP_OK) result = i2s_channel_enable(g_i2s_rx);
    if (result == ESP_OK) result = i2s_channel_enable(g_i2s_tx);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Could not configure full-duplex I2S: %s", esp_err_to_name(result));
        return false;
    }

    g_playback_queue = xQueueCreate(PLAYBACK_QUEUE_DEPTH, sizeof(SpeakerFrame));
    if (!g_playback_queue) {
        ESP_LOGE(TAG, "Could not allocate bounded speaker queue");
        return false;
    }
    if (xTaskCreate(speaker_task, "bella_speaker", 4096, nullptr, 8, nullptr) != pdPASS ||
        xTaskCreate(microphone_task, "bella_microphone", 4096, nullptr, 8, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Audio task creation failed");
        return false;
    }
    ESP_LOGI(TAG, "Shared I2S configured: 16 kHz, 32-bit stereo slots, 16-bit mono wire PCM");
    return true;
}

void bella_audio_flush_playback() {
    if (!g_playback_queue) return;
    SpeakerFrame discarded{};
    while (xQueueReceive(g_playback_queue, &discarded, 0) == pdTRUE) {}
}

bool bella_audio_enqueue_speaker(
    uint32_t turn_id,
    uint32_t sequence,
    const char *trace_id,
    int64_t chunk_started_us,
    const uint8_t *pcm,
    size_t length) {
    if (!g_playback_queue || !pcm || length == 0 || length > BELLA_AUDIO_FRAME_BYTES || length % 2 != 0) {
        return false;
    }
    SpeakerFrame frame{};
    frame.turn_id = turn_id;
    frame.sequence = sequence;
    frame.chunk_started_us = chunk_started_us;
    std::snprintf(frame.trace_id, sizeof(frame.trace_id), "%s", trace_id ? trace_id : "");
    frame.samples = length / 2;
    std::memcpy(frame.pcm, pcm, length);
    // This wait is deliberate backpressure: when speaker DMA is full, stop
    // consuming websocket data instead of silently dropping ordered audio.
    if (xQueueSend(g_playback_queue, &frame, pdMS_TO_TICKS(2000)) != pdTRUE) {
        g_dropped_frames.fetch_add(1);
        ESP_LOGE(TAG, "Speaker queue remained full; an audio frame was dropped");
        return false;
    }
    return true;
}

bool bella_audio_end_speaker_chunk(
    uint32_t turn_id, const char *trace_id, int64_t chunk_started_us) {
    if (!g_playback_queue) return false;
    SpeakerFrame frame{};
    frame.turn_id = turn_id;
    frame.chunk_started_us = chunk_started_us;
    frame.end_of_chunk = true;
    std::snprintf(frame.trace_id, sizeof(frame.trace_id), "%s", trace_id ? trace_id : "");
    if (xQueueSend(g_playback_queue, &frame, pdMS_TO_TICKS(2000)) != pdTRUE) {
        g_dropped_frames.fetch_add(1);
        ESP_LOGE(TAG, "Could not enqueue speaker chunk-drained marker");
        return false;
    }
    return true;
}

uint32_t bella_audio_dropped_frames() {
    return g_dropped_frames.load();
}
