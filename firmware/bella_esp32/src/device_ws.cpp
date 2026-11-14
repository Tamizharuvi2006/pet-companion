#include "bella_config.h"
#include "bella_audio_i2s.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"

#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include <atomic>
#include <cstdio>
#include <cstring>

static const char *TAG = "bella_ws";
static esp_websocket_client_handle_t g_client = nullptr;
static SemaphoreHandle_t g_send_mutex = nullptr;
static std::atomic<bool> g_socket_connected{false};
static std::atomic<bool> g_ready{false};
static std::atomic<bool> g_recording{false};
static std::atomic<uint32_t> g_turn_id{0};
static std::atomic<uint32_t> g_next_turn_id{0};
static std::atomic<bool> g_reconnect_requested{true};
static std::atomic<uint32_t> g_playback_turn{0};
static uint32_t g_expected_speaker_sequence = 0;
static char g_audio_trace_id[32]{};
static int64_t g_audio_chunk_started_us = 0;
static bool g_first_device_frame_logged = false;
static char g_text_fragments[4096]{};
static size_t g_text_expected = 0;
static uint8_t g_fragment_opcode = 0;

static uint32_t read_u32_le(const uint8_t *bytes) {
    return static_cast<uint32_t>(bytes[0]) |
           (static_cast<uint32_t>(bytes[1]) << 8) |
           (static_cast<uint32_t>(bytes[2]) << 16) |
           (static_cast<uint32_t>(bytes[3]) << 24);
}

static void write_u32_le(uint8_t *bytes, uint32_t value) {
    bytes[0] = static_cast<uint8_t>(value);
    bytes[1] = static_cast<uint8_t>(value >> 8);
    bytes[2] = static_cast<uint8_t>(value >> 16);
    bytes[3] = static_cast<uint8_t>(value >> 24);
}

static bool send_text_locked(const char *text) {
    if (!g_client || !g_socket_connected.load() || !text) return false;
    const int result = esp_websocket_client_send_text(
        g_client, text, std::strlen(text), pdMS_TO_TICKS(1500));
    return result == static_cast<int>(std::strlen(text));
}

static void on_text_message(const char *text, size_t length) {
    cJSON *root = cJSON_ParseWithLength(text, length);
    if (!root) {
        ESP_LOGW(TAG, "Ignoring invalid backend JSON message");
        return;
    }
    const cJSON *type_item = cJSON_GetObjectItemCaseSensitive(root, "type");
    const cJSON *turn_item = cJSON_GetObjectItemCaseSensitive(root, "turn_id");
    const char *type = cJSON_IsString(type_item) ? type_item->valuestring : "";
    const uint32_t turn_id = cJSON_IsNumber(turn_item) ? static_cast<uint32_t>(turn_item->valuedouble) : 0;

    if (std::strcmp(type, "device_ready") == 0) {
        g_ready.store(true);
        bella_set_state(BellaState::Idle);
        ESP_LOGI(TAG, "Authenticated device session ready");
    } else if (std::strcmp(type, "tts_chunk_start") == 0) {
        const cJSON *trace_item = cJSON_GetObjectItemCaseSensitive(root, "trace_id");
        std::snprintf(g_audio_trace_id, sizeof(g_audio_trace_id), "%s",
                      cJSON_IsString(trace_item) ? trace_item->valuestring : "untraced");
        g_audio_chunk_started_us = esp_timer_get_time();
        g_first_device_frame_logged = false;
        g_playback_turn.store(turn_id);
        g_expected_speaker_sequence = 0;
        bella_set_state(BellaState::Speaking);
    } else if (std::strcmp(type, "tts_chunk_end") == 0) {
        bella_audio_end_speaker_chunk(turn_id, g_audio_trace_id, g_audio_chunk_started_us);
    } else if (std::strcmp(type, "tts_chunk_abort") == 0) {
        const cJSON *trace_item = cJSON_GetObjectItemCaseSensitive(root, "trace_id");
        const cJSON *chunk_item = cJSON_GetObjectItemCaseSensitive(root, "chunk_id");
        bella_audio_flush_playback();
        g_expected_speaker_sequence = 0;
        ESP_LOGW(TAG,
                 "voice_timing trace_id=%s stage=device_audio_chunk_aborted turn_id=%lu chunk_id=%lu",
                 cJSON_IsString(trace_item) ? trace_item->valuestring : g_audio_trace_id,
                 static_cast<unsigned long>(turn_id),
                 static_cast<unsigned long>(cJSON_IsNumber(chunk_item) ? chunk_item->valuedouble : 0));
        bella_set_state(BellaState::Processing);
    } else if (std::strcmp(type, "turn_complete") == 0) {
        const cJSON *cancelled_item = cJSON_GetObjectItemCaseSensitive(root, "cancelled");
        g_recording.store(false);
        g_turn_id.store(0);
        g_playback_turn.store(0);
        if (cJSON_IsTrue(cancelled_item)) bella_audio_flush_playback();
        const cJSON *trace_item = cJSON_GetObjectItemCaseSensitive(root, "trace_id");
        ESP_LOGI(TAG, "voice_timing trace_id=%s stage=device_turn_complete_received turn_id=%lu",
                 cJSON_IsString(trace_item) ? trace_item->valuestring : g_audio_trace_id,
                 static_cast<unsigned long>(turn_id));
        bella_set_state(bella_is_muted() ? BellaState::Muted : BellaState::Idle);
    } else if (std::strcmp(type, "error") == 0) {
        const cJSON *code_item = cJSON_GetObjectItemCaseSensitive(root, "code");
        ESP_LOGW(TAG, "Backend device event error code=%s",
                 cJSON_IsString(code_item) ? code_item->valuestring : "unknown");
    } else if (std::strcmp(type, "pong") == 0 || std::strcmp(type, "reply_delta") == 0 ||
               std::strcmp(type, "transcript") == 0) {
        // Transcript/reply text is intentionally not logged or retained by firmware.
    }
    cJSON_Delete(root);
}

static void on_binary_message(const uint8_t *bytes, size_t length) {
    constexpr size_t HEADER_BYTES = 12;
    if (length <= HEADER_BYTES || length > HEADER_BYTES + BELLA_AUDIO_FRAME_BYTES) {
        ESP_LOGW(TAG, "Rejecting speaker frame with invalid byte length");
        return;
    }
    const uint8_t message_type = bytes[0];
    const uint8_t version = bytes[1];
    const uint16_t flags = static_cast<uint16_t>(bytes[2]) |
                           (static_cast<uint16_t>(bytes[3]) << 8);
    const uint32_t turn_id = read_u32_le(bytes + 4);
    const uint32_t sequence = read_u32_le(bytes + 8);
    const size_t payload_length = length - HEADER_BYTES;
    if (message_type != 0x02 || version != BELLA_PROTOCOL_VERSION || flags != 0 ||
        payload_length % 2 != 0 || turn_id == 0 || turn_id != g_playback_turn.load()) {
        ESP_LOGW(TAG, "Rejecting stale or invalid speaker frame");
        return;
    }
    if (sequence != g_expected_speaker_sequence++) {
        bella_audio_flush_playback();
        ESP_LOGW(TAG, "Speaker frame sequence gap; flushed stale audio");
        return;
    }
    if (!g_first_device_frame_logged) {
        ESP_LOGI(TAG,
                 "voice_timing trace_id=%s stage=device_first_pcm_frame_received turn_id=%lu offset_from_chunk_start_ms=%lld bytes=%u",
                 g_audio_trace_id, static_cast<unsigned long>(turn_id),
                 static_cast<long long>((esp_timer_get_time() - g_audio_chunk_started_us) / 1000),
                 static_cast<unsigned>(payload_length));
        g_first_device_frame_logged = true;
    }
    if (!bella_audio_enqueue_speaker(
            turn_id, sequence, g_audio_trace_id, g_audio_chunk_started_us,
            bytes + HEADER_BYTES, payload_length)) {
        ESP_LOGE(TAG, "Bounded speaker queue could not accept frame");
    }
}

static void websocket_event_handler(void *, esp_event_base_t, int32_t event_id, void *event_data) {
    auto *event = static_cast<esp_websocket_event_data_t *>(event_data);
    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        g_socket_connected.store(true);
        g_ready.store(false);
        g_reconnect_requested.store(false);
        char hello[768];
        std::snprintf(
            hello,
            sizeof(hello),
            "{\"type\":\"hello\",\"version\":1,\"device_id\":\"%s\",\"token\":\"%s\",\"firmware_version\":\"%s\",\"capabilities\":{\"audio_in\":true,\"audio_out\":true,\"touch\":true,\"distance\":true,\"tft\":false,\"servos\":%s},\"sensors\":{}}",
            BELLA_DEVICE_ID, BELLA_DEVICE_TOKEN, BELLA_FIRMWARE_VERSION,
            BELLA_SERVO_ENABLED ? "true" : "false");
        xSemaphoreTake(g_send_mutex, portMAX_DELAY);
        const bool sent = send_text_locked(hello);
        xSemaphoreGive(g_send_mutex);
        if (!sent) ESP_LOGW(TAG, "Could not send hello message");
        bella_set_state(BellaState::Connecting);
        ESP_LOGI(TAG, "WebSocket transport connected; sending device hello");
    } else if (event_id == WEBSOCKET_EVENT_DISCONNECTED) {
        g_socket_connected.store(false);
        g_ready.store(false);
        g_recording.store(false);
        g_turn_id.store(0);
        g_playback_turn.store(0);
        bella_audio_flush_playback();
        bella_set_state(BellaState::Disconnected);
        g_reconnect_requested.store(true);
        ESP_LOGW(TAG, "WebSocket disconnected; bounded reconnect scheduled");
    } else if (event_id == WEBSOCKET_EVENT_ERROR) {
        ESP_LOGW(TAG, "WebSocket transport error");
    } else if (event_id == WEBSOCKET_EVENT_DATA && event) {
        const size_t offset = static_cast<size_t>(event->payload_offset);
        const size_t total = static_cast<size_t>(event->payload_len);
        const size_t chunk = static_cast<size_t>(event->data_len);
        const uint8_t opcode = event->op_code;
        if (offset == 0) {
            g_fragment_opcode = opcode;
            g_text_expected = total;
        }
        if (offset + chunk > total || total > sizeof(g_text_fragments)) {
            ESP_LOGW(TAG, "Rejecting oversized/invalid WebSocket message");
            return;
        }
        if (g_fragment_opcode == 0x01 || g_fragment_opcode == 0x00) {
            std::memcpy(g_text_fragments + offset, event->data_ptr, chunk);
            if (offset + chunk == total) on_text_message(g_text_fragments, total);
        } else if (g_fragment_opcode == 0x02 && offset == 0 && chunk == total) {
            on_binary_message(reinterpret_cast<const uint8_t *>(event->data_ptr), total);
        } else {
            ESP_LOGW(TAG, "Unsupported fragmented binary frame");
        }
    }
}

static bool start_client() {
    if (std::strlen(BELLA_DEVICE_TOKEN) < 16) {
        ESP_LOGE(TAG, "Device token missing or too short; configure ignored secrets.h");
        return false;
    }
    esp_websocket_client_config_t config{};
    config.uri = BELLA_BACKEND_WS_URL;
    config.buffer_size = 2048;
    config.task_stack = 6144;
    config.network_timeout_ms = 10000;
    config.reconnect_timeout_ms = 1000;
    config.disable_auto_reconnect = true;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    g_client = esp_websocket_client_init(&config);
    if (!g_client) return false;
    esp_err_t result = esp_websocket_register_events(
        g_client, WEBSOCKET_EVENT_ANY, websocket_event_handler, nullptr);
    if (result == ESP_OK) result = esp_websocket_client_start(g_client);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Could not start device WebSocket: %s", esp_err_to_name(result));
        esp_websocket_client_destroy(g_client);
        g_client = nullptr;
        return false;
    }
    return true;
}

static void reconnect_task(void *) {
    uint32_t backoff_ms = 1000;
    while (true) {
        if (!g_reconnect_requested.load()) {
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }
        wifi_ap_record_t ap_info{};
        if (esp_wifi_sta_get_ap_info(&ap_info) != ESP_OK) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        xSemaphoreTake(g_send_mutex, portMAX_DELAY);
        esp_websocket_client_handle_t old_client = g_client;
        g_client = nullptr;
        g_socket_connected.store(false);
        g_ready.store(false);
        g_reconnect_requested.store(false);
        xSemaphoreGive(g_send_mutex);
        if (old_client) {
            (void)esp_websocket_client_stop(old_client);
            (void)esp_websocket_client_destroy(old_client);
        }
        vTaskDelay(pdMS_TO_TICKS(backoff_ms));
        ESP_LOGI(TAG, "Starting backend reconnect attempt after %lu ms", static_cast<unsigned long>(backoff_ms));
        if (!start_client()) g_reconnect_requested.store(true);
        backoff_ms = backoff_ms >= 15000 ? 30000 : backoff_ms * 2;
        while (g_socket_connected.load()) {
            backoff_ms = 1000;
            vTaskDelay(pdMS_TO_TICKS(500));
        }
    }
}

static void heartbeat_task(void *) {
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
        if (!g_ready.load()) continue;
        char message[256];
        std::snprintf(
            message,
            sizeof(message),
            "{\"type\":\"ping\",\"version\":1,\"state\":\"%s\",\"sensors\":{\"muted\":%s,\"dropped_audio_frames\":%lu}}",
            bella_state_name(bella_get_state()), bella_is_muted() ? "true" : "false",
            static_cast<unsigned long>(bella_audio_dropped_frames()));
        bella_ws_send_control(message);
    }
}

void bella_ws_init() {
    g_send_mutex = xSemaphoreCreateMutex();
    if (!g_send_mutex) {
        ESP_LOGE(TAG, "Could not allocate WebSocket send mutex");
        return;
    }
    if (xTaskCreate(reconnect_task, "bella_ws_retry", 4096, nullptr, 5, nullptr) != pdPASS ||
        xTaskCreate(heartbeat_task, "bella_ws_ping", 3072, nullptr, 4, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "WebSocket service task creation failed");
    }
}

void bella_ws_start() {
    g_reconnect_requested.store(true);
}

bool bella_ws_is_ready() { return g_ready.load(); }
bool bella_ws_is_recording() { return g_recording.load(); }
uint32_t bella_ws_current_turn_id() { return g_turn_id.load(); }

bool bella_ws_send_control(const char *json) {
    if (!g_send_mutex || !json || !g_socket_connected.load()) return false;
    xSemaphoreTake(g_send_mutex, portMAX_DELAY);
    const bool sent = send_text_locked(json);
    xSemaphoreGive(g_send_mutex);
    return sent;
}

bool bella_ws_send_audio(const uint8_t *pcm, size_t length, uint32_t turn_id, uint32_t sequence) {
    constexpr size_t HEADER_BYTES = 12;
    if (!g_send_mutex || !pcm || length == 0 || length > BELLA_AUDIO_FRAME_BYTES || length % 2 != 0 ||
        !g_ready.load() || !g_recording.load() || turn_id != g_turn_id.load()) return false;
    uint8_t frame[HEADER_BYTES + BELLA_AUDIO_FRAME_BYTES]{};
    frame[0] = 0x01;
    frame[1] = BELLA_PROTOCOL_VERSION;
    frame[2] = 0;
    frame[3] = 0;
    write_u32_le(frame + 4, turn_id);
    write_u32_le(frame + 8, sequence);
    std::memcpy(frame + HEADER_BYTES, pcm, length);
    xSemaphoreTake(g_send_mutex, portMAX_DELAY);
    const int sent = g_socket_connected.load()
        ? esp_websocket_client_send_bin(g_client, reinterpret_cast<const char *>(frame),
                                        HEADER_BYTES + length, pdMS_TO_TICKS(1500))
        : -1;
    xSemaphoreGive(g_send_mutex);
    return sent == static_cast<int>(HEADER_BYTES + length);
}

uint32_t bella_ws_begin_recording() {
    if (!g_ready.load() || g_recording.load()) return 0;
    uint32_t turn_id = g_next_turn_id.fetch_add(1) + 1;
    if (turn_id == 0) turn_id = g_next_turn_id.fetch_add(1) + 1;
    char message[256];
    std::snprintf(message, sizeof(message),
                  "{\"type\":\"recording_start\",\"version\":1,\"turn_id\":%lu,\"sample_rate_hz\":16000,\"channels\":1,\"bits_per_sample\":16,\"codec\":\"pcm_s16le\"}",
                  static_cast<unsigned long>(turn_id));
    if (!bella_ws_send_control(message)) return 0;
    g_turn_id.store(turn_id);
    g_recording.store(true);
    bella_set_state(BellaState::Listening);
    return turn_id;
}

void bella_ws_end_recording(uint32_t turn_id) {
    if (turn_id == 0 || turn_id != g_turn_id.load() || !g_recording.exchange(false)) return;
    char message[128];
    std::snprintf(message, sizeof(message),
                  "{\"type\":\"recording_end\",\"version\":1,\"turn_id\":%lu}",
                  static_cast<unsigned long>(turn_id));
    bella_ws_send_control(message);
    bella_set_state(BellaState::Processing);
}

void bella_ws_cancel(uint32_t turn_id) {
    const uint32_t active_turn = turn_id == 0 ? g_turn_id.load() : turn_id;
    char message[128];
    std::snprintf(message, sizeof(message),
                  "{\"type\":\"cancel\",\"version\":1,\"turn_id\":%lu}",
                  static_cast<unsigned long>(active_turn));
    g_recording.store(false);
    bella_audio_flush_playback();
    bella_ws_send_control(message);
    g_turn_id.store(0);
    bella_set_state(bella_is_muted() ? BellaState::Muted : BellaState::Idle);
}
