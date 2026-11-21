#include "bella_config.h"
#include "bella_backend_url_policy.h"
#include "bella_audio_i2s.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"
#include "bella_display.h"
#include "bella_distance.h"
#include "bella_provisioning.h"
#include "bella_tft_profile.h"
#include "esp_random.h"

#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "freertos/queue.h"

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
static std::atomic<int64_t> g_recording_started_us{0};
static std::atomic<bool> g_reconnect_requested{true};
static std::atomic<uint32_t> g_playback_turn{0};
static uint32_t g_expected_speaker_sequence = 0;
static char g_audio_trace_id[32]{};
static int64_t g_audio_chunk_started_us = 0;
static bool g_first_device_frame_logged = false;
static char g_text_fragments[4096]{};
static size_t g_text_expected = 0;
static uint8_t g_fragment_opcode = 0;
static char g_last_face_command[33]{};
static char g_face_session[33]{};
static uint32_t g_face_sequence=0;
static std::atomic<uint32_t> g_control_epoch{0};
static bool send_text_locked(const char *text);
struct ControlEvent { char json[384]; uint32_t epoch; };
static QueueHandle_t g_control_events=nullptr;
static void control_sender(void*){
    ControlEvent event{};
    while(true)if(xQueueReceive(g_control_events,&event,portMAX_DELAY)==pdTRUE){
        if(!g_send_mutex)continue;
        xSemaphoreTake(g_send_mutex,portMAX_DELAY);
        if(g_ready.load()&&event.epoch==g_control_epoch.load())send_text_locked(event.json);
        xSemaphoreGive(g_send_mutex);
    }
}
bool bella_ws_queue_control(const char *json){
    if(!g_control_events||!g_ready.load()||!json||std::strlen(json)>=384)return false;
    ControlEvent event{};event.epoch=g_control_epoch.load();std::snprintf(event.json,sizeof(event.json),"%s",json);
    return xQueueSend(g_control_events,&event,0)==pdTRUE;
}

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

    if (std::strcmp(type, "face_command") == 0) {
        const auto *id=cJSON_GetObjectItemCaseSensitive(root,"command_id");
        const auto *expression=cJSON_GetObjectItemCaseSensitive(root,"expression");
        const auto *duration=cJSON_GetObjectItemCaseSensitive(root,"duration_ms");
        const auto *version=cJSON_GetObjectItemCaseSensitive(root,"face_version");
        const auto *session=cJSON_GetObjectItemCaseSensitive(root,"session_id");
        const auto *sequence=cJSON_GetObjectItemCaseSensitive(root,"sequence");
        if(cJSON_IsString(session)&&std::strcmp(session->valuestring,g_face_session)!=0){cJSON_Delete(root);return;}
        if(cJSON_IsNumber(sequence)&&sequence->valuedouble<=g_face_sequence){cJSON_Delete(root);return;}
        if(cJSON_IsString(id)&&std::strlen(id->valuestring)==32&&cJSON_IsString(expression)&&cJSON_IsNumber(duration)&&cJSON_IsNumber(version)&&version->valueint==1){
            const bool duplicate=std::strcmp(g_last_face_command,id->valuestring)==0;
            if(duplicate||bella_display_expression(expression->valuestring,duration->valueint)){
                if(cJSON_IsNumber(sequence))g_face_sequence=static_cast<uint32_t>(sequence->valuedouble);
                std::snprintf(g_last_face_command,sizeof(g_last_face_command),"%s",id->valuestring);
                char ack[160];std::snprintf(ack,sizeof(ack),"{\"type\":\"face_ack\",\"version\":1,\"face_version\":1,\"command_id\":\"%s\"}",g_last_face_command);
                bella_ws_send_control(ack);
            }
        }
    } else if (std::strcmp(type, "device_ready") == 0) {
        const auto *session=cJSON_GetObjectItemCaseSensitive(root,"connection_id");
        std::snprintf(g_face_session,sizeof(g_face_session),"%s",cJSON_IsString(session)?session->valuestring:"");g_face_sequence=0;
        g_ready.store(true);
        bella_set_state(BellaState::Idle);
        ESP_LOGI(TAG, "Authenticated device session ready");
    } else if (std::strcmp(type, "display_settings") == 0) {
        const auto *enabled = cJSON_GetObjectItemCaseSensitive(root, "captions_enabled");
        const auto *command_id = cJSON_GetObjectItemCaseSensitive(root, "command_id");
        if (cJSON_IsBool(enabled) && cJSON_IsString(command_id) &&
            std::strlen(command_id->valuestring) == 32) {
            const bool captions_enabled = cJSON_IsTrue(enabled);
            const bool persisted = bella_display_set_captions_enabled(captions_enabled);
            char acknowledgement[192];
            std::snprintf(acknowledgement, sizeof(acknowledgement),
                "{\"type\":\"display_settings_ack\",\"version\":1,\"command_id\":\"%s\",\"captions_enabled\":%s,\"persisted\":%s}",
                command_id->valuestring, captions_enabled ? "true" : "false",
                persisted ? "true" : "false");
            (void)bella_ws_queue_control(acknowledgement);
            if (!persisted) ESP_LOGW(TAG, "Caption preference applied for this session but could not be saved");
        }
    } else if (std::strcmp(type, "tts_chunk_start") == 0) {
        if(!turn_id||turn_id!=g_turn_id.load()){cJSON_Delete(root);return;}
        const cJSON *trace_item = cJSON_GetObjectItemCaseSensitive(root, "trace_id");
        std::snprintf(g_audio_trace_id, sizeof(g_audio_trace_id), "%s",
                      cJSON_IsString(trace_item) ? trace_item->valuestring : "untraced");
        g_audio_chunk_started_us = esp_timer_get_time();
        g_first_device_frame_logged = false;
        g_playback_turn.store(turn_id);
        g_expected_speaker_sequence = 0;
        bella_audio_begin_turn(turn_id);
    } else if (std::strcmp(type, "tts_chunk_end") == 0) {
        if(turn_id!=g_playback_turn.load()){cJSON_Delete(root);return;}
        const auto *count=cJSON_GetObjectItemCaseSensitive(root,"frame_count");
        if(turn_id==g_playback_turn.load()&&cJSON_IsNumber(count)&&count->valuedouble==g_expected_speaker_sequence)
            bella_audio_end_speaker_chunk(turn_id, g_audio_trace_id, g_audio_chunk_started_us);
        else{bella_audio_flush_playback();g_playback_turn.store(0);bella_set_state(BellaState::Error);}
    } else if (std::strcmp(type, "tts_chunk_abort") == 0) {
        if(turn_id!=g_playback_turn.load()){cJSON_Delete(root);return;}
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
        if(!turn_id||(turn_id!=g_turn_id.load()&&turn_id!=g_playback_turn.load())){cJSON_Delete(root);return;}
        const cJSON *cancelled_item = cJSON_GetObjectItemCaseSensitive(root, "cancelled");
        g_recording.store(false);
        g_turn_id.store(0);
        if (cJSON_IsTrue(cancelled_item)) { bella_audio_flush_playback(); bella_set_state(BellaState::Idle); }
        else if(!bella_audio_finish_turn(turn_id)&&bella_get_state()!=BellaState::Error)bella_set_state(BellaState::Idle);
        const cJSON *trace_item = cJSON_GetObjectItemCaseSensitive(root, "trace_id");
        ESP_LOGI(TAG, "voice_timing trace_id=%s stage=device_turn_complete_received turn_id=%lu",
                 cJSON_IsString(trace_item) ? trace_item->valuestring : g_audio_trace_id,
                 static_cast<unsigned long>(turn_id));
        // Final idle comes from the speaker task's drain fence, not receipt of JSON.
    } else if (std::strcmp(type, "error") == 0) {
        if(turn_id&&turn_id!=g_turn_id.load()&&turn_id!=g_playback_turn.load()){cJSON_Delete(root);return;}
        bella_audio_flush_playback();g_playback_turn.store(0);bella_set_state(BellaState::Error);
        const cJSON *code_item = cJSON_GetObjectItemCaseSensitive(root, "code");
        ESP_LOGW(TAG, "Backend device event error code=%s",
                 cJSON_IsString(code_item) ? code_item->valuestring : "unknown");
    } else if (std::strcmp(type, "reply_delta") == 0) {
        const auto *reply_text = cJSON_GetObjectItemCaseSensitive(root, "text");
        const bool active_turn = turn_id != 0 &&
            (turn_id == g_turn_id.load() || turn_id == g_playback_turn.load());
        if (active_turn && cJSON_IsString(reply_text))
            bella_display_append_caption(reply_text->valuestring);
    } else if (std::strcmp(type, "pong") == 0 || std::strcmp(type, "transcript") == 0) {
        // User transcript text is intentionally not logged or retained by firmware.
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
        char hello[1200];
        std::snprintf(
            hello,
            sizeof(hello),
            "{\"type\":\"hello\",\"version\":1,\"device_id\":\"%s\",\"token\":\"%s\",\"firmware_version\":\"%s\",\"capabilities\":{\"face_protocol_v1\":true,\"audio_in\":true,\"audio_out\":true,\"touch\":true,\"distance\":true,\"caption_overlay_v1\":true,\"display_captions_enabled\":%s,\"display_captions_persisted\":%s,\"tft\":%s,\"tft_profile\":\"%s\",\"servo1_enabled\":%s,\"servo2_gpio12_enabled\":%s,\"camera\":\"separate_board_optional\",\"touch4_ptt_enabled\":%s},\"sensors\":{\"i2s_input_ready\":%s,\"i2s_output_ready\":%s,\"distance_initialized\":%s,\"display_initialized\":%s,\"servo2_gpio12_strap_gate_open\":%s}}",
            bella_provision_device_id(), bella_provision_device_token(), BELLA_FIRMWARE_VERSION,
            bella_display_captions_enabled() ? "true" : "false",
            bella_display_captions_persisted() ? "true" : "false",
            BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_DIAGNOSTIC ? "false" : "true",
            bella_display_profile_name(), BELLA_SERVO_ENABLED ? "true" : "false",
            BELLA_SERVO2_GPIO12_ENABLED ? "true" : "false",
            BELLA_TOUCH4_PTT_ENABLED ? "true" : "false",
            bella_audio_input_ready() ? "true" : "false",
            bella_audio_output_ready() ? "true" : "false",
            bella_distance_initialized() ? "true" : "false",
            bella_display_initialized() ? "true" : "false",
            BELLA_SERVO2_GPIO12_ENABLED && BELLA_GPIO12_STRAP_SAFE_CONFIRMED ? "true" : "false");
        xSemaphoreTake(g_send_mutex, portMAX_DELAY);
        const bool sent = send_text_locked(hello);
        xSemaphoreGive(g_send_mutex);
        if (!sent) ESP_LOGW(TAG, "Could not send hello message");
        bella_set_state(BellaState::Connecting);
        ESP_LOGI(TAG, "WebSocket transport connected; sending device hello");
    } else if (event_id == WEBSOCKET_EVENT_DISCONNECTED) {
        g_control_epoch.fetch_add(1);if(g_control_events)xQueueReset(g_control_events);
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
    if(!bella_backend_url_is_valid_wss(bella_provision_backend_url())){
        ESP_LOGE(TAG,"Secure wss:// backend URL required");return false;
    }
    if (!bella_provision_ready() || std::strlen(bella_provision_device_token()) < 16) {
        ESP_LOGE(TAG, "Device provisioning is missing or invalid");
        return false;
    }
    esp_websocket_client_config_t config{};
    config.uri = bella_provision_backend_url();
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
        vTaskDelay(pdMS_TO_TICKS(backoff_ms + esp_random()%500));
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
        char message[1100];
        std::snprintf(
            message,
            sizeof(message),
            "{\"type\":\"ping\",\"version\":1,\"state\":\"%s\",\"sensors\":{\"muted\":%s,\"i2s_input_ready\":%s,\"i2s_output_ready\":%s,\"mic_last_rms\":%u,\"mic_frames\":%lu,\"audio_dropped_frames\":%lu,\"i2s_tx_dma_eof_count\":%lu,\"touch_seen_mask\":%u,\"touch_pressed_mask\":%u,\"touch_event_count\":%lu,\"last_touch_pad\":%u,\"distance_initialized\":%s,\"distance_valid\":%s,\"distance_mm\":%u,\"distance_valid_samples\":%lu,\"distance_invalid_samples\":%lu,\"display_profile\":\"%s\",\"display_initialized\":%s,\"display_frames\":%lu,\"display_errors\":%lu,\"display_last_render_ms\":%lu,\"servo_enabled\":%s,\"servo2_gpio12_enabled\":%s,\"servo2_gpio12_strap_gate_open\":%s,\"camera_available\":false}}",
            bella_state_name(bella_get_state()), bella_is_muted() ? "true" : "false",
            bella_audio_input_ready() ? "true" : "false", bella_audio_output_ready() ? "true" : "false",
            static_cast<unsigned>(bella_audio_last_mic_rms()), static_cast<unsigned long>(bella_audio_mic_frame_count()),
            static_cast<unsigned long>(bella_audio_dropped_frames()), static_cast<unsigned long>(bella_audio_tx_eof_count()),
            static_cast<unsigned>(bella_touch_seen_mask()), static_cast<unsigned>(bella_touch_pressed_mask()),
            static_cast<unsigned long>(bella_touch_event_count()), bella_last_touch_pad(),
            bella_distance_initialized() ? "true" : "false", bella_distance_has_valid_sample() ? "true" : "false",
            static_cast<unsigned>(bella_distance_last_mm()), static_cast<unsigned long>(bella_distance_valid_count()),
            static_cast<unsigned long>(bella_distance_invalid_count()), bella_display_profile_name(),
            bella_display_initialized() ? "true" : "false", static_cast<unsigned long>(bella_display_frame_count()),
            static_cast<unsigned long>(bella_display_error_count()), static_cast<unsigned long>(bella_display_last_render_ms()),
            BELLA_SERVO_ENABLED ? "true" : "false", BELLA_SERVO2_GPIO12_ENABLED ? "true" : "false",
            BELLA_SERVO2_GPIO12_ENABLED && BELLA_GPIO12_STRAP_SAFE_CONFIRMED ? "true" : "false");
        bella_ws_send_control(message);
    }
}

void bella_ws_init() {
    g_control_events=xQueueCreate(8,sizeof(ControlEvent));
    if(!g_control_events||xTaskCreate(control_sender,"bella_control",3072,nullptr,4,nullptr)!=pdPASS){ESP_LOGE(TAG,"Control telemetry task unavailable");return;}
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
uint32_t bella_ws_recording_elapsed_ms() {
    const int64_t started = g_recording_started_us.load();
    if (!started || !g_recording.load()) return 0;
    return static_cast<uint32_t>((esp_timer_get_time() - started) / 1000);
}

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
    bella_audio_flush_playback();g_playback_turn.store(0);
    uint32_t turn_id = g_next_turn_id.fetch_add(1) + 1;
    if (turn_id == 0) turn_id = g_next_turn_id.fetch_add(1) + 1;
    char message[256];
    std::snprintf(message, sizeof(message),
                  "{\"type\":\"recording_start\",\"version\":1,\"turn_id\":%lu,\"sample_rate_hz\":16000,\"channels\":1,\"bits_per_sample\":16,\"codec\":\"pcm_s16le\"}",
                  static_cast<unsigned long>(turn_id));
    if (!bella_ws_send_control(message)) return 0;
    g_turn_id.store(turn_id);
    g_recording.store(true);
    g_recording_started_us.store(esp_timer_get_time());
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
