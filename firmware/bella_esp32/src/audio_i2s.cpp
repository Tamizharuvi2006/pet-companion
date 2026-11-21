#include "bella_audio_i2s.h"

#include "bella_config.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"
#include "bella_playback.h"

#include "driver/i2s_std.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include <array>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>

static const char *TAG = "bella_audio";
static i2s_chan_handle_t g_i2s_tx = nullptr;
static i2s_chan_handle_t g_i2s_rx = nullptr;
static QueueHandle_t g_playback_queue = nullptr;
static std::atomic<uint32_t> g_dropped_frames{0};
static std::atomic<uint16_t> g_mic_rms{0};
static std::atomic<uint32_t> g_mic_frames{0};
static std::atomic<bool> g_input_ready{false}, g_output_ready{false};
static constexpr size_t PLAYBACK_QUEUE_DEPTH = 8;
static std::atomic<uint32_t> g_audio_turn{0},g_generation{0},g_tx_eofs{0},g_report_sequence{0};
static SemaphoreHandle_t g_tx_mutex=nullptr;
static bool IRAM_ATTR on_tx_sent(i2s_chan_handle_t,i2s_event_data_t*,void*){
    g_tx_eofs.fetch_add(1,std::memory_order_relaxed);return false;
}
static void report_playback(const char *event,uint32_t turn,const char *basis,bool estimated){
    if(!turn)return;
    char message[320];
    std::snprintf(message,sizeof(message),"{\"type\":\"%s\",\"version\":1,\"playback_version\":1,\"turn_id\":%lu,\"sequence\":%lu,\"basis\":\"%s\",\"estimated\":%s}",event,static_cast<unsigned long>(turn),static_cast<unsigned long>(g_report_sequence.fetch_add(1)),basis,estimated?"true":"false");
    bella_ws_queue_control(message);
}

struct SpeakerFrame {
    uint32_t turn_id = 0;
    uint32_t sequence = 0;
    int64_t chunk_started_us = 0;
    bool end_of_chunk = false;
    bool end_of_turn = false;
    uint32_t generation = 0;
    char trace_id[32]{};
    size_t samples = 0;
    int16_t pcm[BELLA_AUDIO_FRAME_SAMPLES]{};
};

static void speaker_task(void *) {
    SpeakerFrame frame{};
    std::array<int32_t, BELLA_AUDIO_FRAME_SAMPLES * 2> stereo{};
    uint32_t started_turn=0;
    while (true) {
        if (xQueueReceive(g_playback_queue, &frame, portMAX_DELAY) != pdTRUE) continue;
        if(frame.generation!=g_generation.load()||frame.turn_id!=g_audio_turn.load())continue;
        if(frame.end_of_turn){
            const BellaPlaybackFence fence{g_tx_eofs.load(),frame.generation};
            const int64_t deadline=esp_timer_get_time()+350000;
            while(!fence.complete(g_tx_eofs.load(),g_generation.load())&&esp_timer_get_time()<deadline&&frame.turn_id==g_audio_turn.load()&&frame.generation==g_generation.load())vTaskDelay(1);
            if(frame.generation!=g_generation.load()||frame.turn_id!=g_audio_turn.load())continue;
            if(fence.complete(g_tx_eofs.load(),g_generation.load())){
                report_playback("playback_drained",frame.turn_id,"dma_ring_fence",true);
                g_audio_turn.store(0);bella_set_state(bella_is_muted()?BellaState::Muted:BellaState::Idle);
            }else{report_playback("playback_error",frame.turn_id,"i2s_error",false);bella_audio_flush_playback();bella_set_state(BellaState::Error);}
            continue;
        }
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
        xSemaphoreTake(g_tx_mutex,portMAX_DELAY);
        if(frame.generation!=g_generation.load()){xSemaphoreGive(g_tx_mutex);continue;}
        const esp_err_t result = i2s_channel_write(
            g_i2s_tx,
            stereo.data(),
            frame.samples * 2 * sizeof(int32_t),
            &bytes_written,
            150);
        xSemaphoreGive(g_tx_mutex);
        if(frame.generation!=g_generation.load())continue;
        if(result==ESP_OK&&bytes_written&&started_turn!=frame.turn_id){
            started_turn=frame.turn_id;
            report_playback("playback_started",frame.turn_id,"i2s_write_accepted",true);
            bella_set_state(BellaState::Speaking);
        }
        if (frame.sequence == 0) {
            ESP_LOGI(TAG,
                     "voice_timing trace_id=%s stage=device_i2s_first_write turn_id=%lu offset_from_chunk_start_ms=%lld bytes=%u",
                     frame.trace_id, static_cast<unsigned long>(frame.turn_id),
                     static_cast<long long>((esp_timer_get_time() - frame.chunk_started_us) / 1000),
                     static_cast<unsigned>(bytes_written));
        }
        if (result != ESP_OK || bytes_written != frame.samples * 2 * sizeof(int32_t)) {
            report_playback("playback_error",frame.turn_id,"i2s_error",false);
            bella_audio_flush_playback();bella_set_state(BellaState::Error);
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
        if (bella_ws_recording_elapsed_ms() >= BELLA_DEVICE_RECORDING_MAX_MS) {
            bella_ws_end_recording(turn_id);
            output_samples = 0;
            continue;
        }

        const size_t stereo_frames = bytes_read / (2 * sizeof(int32_t));
        for (size_t i = 0; i < stereo_frames; ++i) {
            // INMP441 L/R is wired to GND: read the left slot. Its 24-bit sample
            // is left-aligned in the configured 32-bit standard-mode slot.
            const int32_t sample = interleaved[i * 2];
            output[output_samples++] = static_cast<int16_t>(sample >> 16);
            if (output_samples == output.size()) {
                uint64_t sum_squares = 0;
                for (const int16_t sample : output) {
                    const int32_t value = sample;
                    sum_squares += static_cast<uint64_t>(value * value);
                }
                const double root_mean_square = std::sqrt(static_cast<double>(sum_squares) / output.size());
                g_mic_rms.store(static_cast<uint16_t>(std::min(32767.0, root_mean_square)));
                g_mic_frames.fetch_add(1);
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
    channel_config.auto_clear_after_cb=true;
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
    i2s_event_callbacks_t callbacks{};callbacks.on_sent=on_tx_sent;
    if(result==ESP_OK)result=i2s_channel_register_event_callback(g_i2s_tx,&callbacks,nullptr);
    g_tx_mutex=xSemaphoreCreateMutex();
    if(!g_tx_mutex)return false;
    if (result == ESP_OK) result = i2s_channel_enable(g_i2s_rx);
    if (result == ESP_OK) result = i2s_channel_enable(g_i2s_tx);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Could not configure full-duplex I2S: %s", esp_err_to_name(result));
        return false;
    }
    g_input_ready.store(true);
    g_output_ready.store(true);

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
    const uint32_t interrupted=g_audio_turn.exchange(0);
    g_generation.fetch_add(1);
    if (!g_playback_queue) return;
    SpeakerFrame discarded{};
    while (xQueueReceive(g_playback_queue, &discarded, 0) == pdTRUE) {}
    // Stop TX and replace every DMA descriptor with silence before re-enabling.
    // RX/shared clocks are not reassigned. A sample already on the wire cannot be recalled.
    if(g_tx_mutex&&g_i2s_tx){
        static const uint8_t silence[6*240*2*sizeof(int32_t)]{};
        xSemaphoreTake(g_tx_mutex,portMAX_DELAY);
        if(i2s_channel_disable(g_i2s_tx)==ESP_OK){
            size_t loaded=0;const auto cleared=i2s_channel_preload_data(g_i2s_tx,silence,sizeof(silence),&loaded);
            if(cleared==ESP_OK&&loaded==sizeof(silence))i2s_channel_enable(g_i2s_tx);
            else{ESP_LOGE(TAG,"TX silence preload failed; transmitter left disabled");report_playback("playback_error",interrupted,"i2s_error",false);}
        }
        xSemaphoreGive(g_tx_mutex);
    }
    report_playback("playback_interrupted",interrupted,"cancelled",false);
}

void bella_audio_begin_turn(uint32_t turn_id){
    if(g_audio_turn.load()==turn_id)return;
    bella_audio_flush_playback();g_audio_turn.store(turn_id);
}
bool bella_audio_finish_turn(uint32_t turn_id){
    if(!g_playback_queue||turn_id!=g_audio_turn.load())return false;
    SpeakerFrame frame{};frame.turn_id=turn_id;frame.generation=g_generation.load();frame.end_of_turn=true;
    return xQueueSend(g_playback_queue,&frame,pdMS_TO_TICKS(2000))==pdTRUE;
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
    frame.generation=g_generation.load();
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
    frame.generation=g_generation.load();
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

bool bella_audio_input_ready() { return g_input_ready.load(); }
bool bella_audio_output_ready() { return g_output_ready.load(); }
uint16_t bella_audio_last_mic_rms() { return g_mic_rms.load(); }
uint32_t bella_audio_mic_frame_count() { return g_mic_frames.load(); }
uint32_t bella_audio_tx_eof_count() { return g_tx_eofs.load(); }
