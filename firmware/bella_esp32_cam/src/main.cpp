#include "cam_config.h"

#include "esp_camera.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include <cstdio>
#include <cstring>

static const char *TAG = "bella_camera";
static httpd_handle_t g_http_server = nullptr;
static volatile bool g_wifi_connected = false;
static volatile bool g_camera_ready = false;

static void wifi_reconnect_task(void *) {
    uint8_t retries = 0;
    while (true) {
        if (g_wifi_connected) {
            retries = 0;
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        const uint32_t delay_ms = retries >= 5 ? 30000U : (1000U << retries);
        vTaskDelay(pdMS_TO_TICKS(delay_ms));
        if (!g_wifi_connected) {
            ESP_LOGI(TAG, "Attempting camera Wi-Fi reconnect");
            esp_wifi_connect();
            if (retries < 5) ++retries;
        }
    }
}

static bool constant_time_equal(const char *left, const char *right) {
    if (!left || !right) return false;
    const size_t left_len = std::strlen(left);
    const size_t right_len = std::strlen(right);
    size_t diff = left_len ^ right_len;
    const size_t count = left_len > right_len ? left_len : right_len;
    for (size_t i = 0; i < count; ++i) {
        const unsigned char a = i < left_len ? static_cast<unsigned char>(left[i]) : 0;
        const unsigned char b = i < right_len ? static_cast<unsigned char>(right[i]) : 0;
        diff |= static_cast<size_t>(a ^ b);
    }
    return diff == 0;
}

static esp_err_t send_unavailable(httpd_req_t *request, const char *message) {
    httpd_resp_set_status(request, "503 Service Unavailable");
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    return httpd_resp_send(request, message, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t health_handler(httpd_req_t *request) {
    const char *body = g_camera_ready ? "{\"status\":\"ok\",\"camera\":\"ready\"}" :
                                       "{\"status\":\"degraded\",\"camera\":\"disabled_or_unidentified\"}";
    httpd_resp_set_type(request, "application/json");
    return httpd_resp_send(request, body, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t snapshot_handler(httpd_req_t *request) {
    if (std::strlen(BELLA_CAM_TOKEN) < 16) {
        return send_unavailable(request, "Camera token not configured");
    }
    char authorization[320]{};
    if (httpd_req_get_hdr_value_str(request, "Authorization", authorization, sizeof(authorization)) != ESP_OK) {
        httpd_resp_set_status(request, "401 Unauthorized");
        return httpd_resp_send(request, "Unauthorized", HTTPD_RESP_USE_STRLEN);
    }
    char expected[320]{};
    std::snprintf(expected, sizeof(expected), "Bearer %s", BELLA_CAM_TOKEN);
    if (!constant_time_equal(authorization, expected)) {
        httpd_resp_set_status(request, "401 Unauthorized");
        return httpd_resp_send(request, "Unauthorized", HTTPD_RESP_USE_STRLEN);
    }
    if (!g_camera_ready) {
        return send_unavailable(request, "Camera profile is disabled or unavailable");
    }

    camera_fb_t *frame = esp_camera_fb_get();
    if (!frame || frame->format != PIXFORMAT_JPEG || frame->len == 0 || frame->len > BELLA_CAM_MAX_JPEG_BYTES) {
        if (frame) esp_camera_fb_return(frame);
        return send_unavailable(request, "JPEG capture failed or exceeded limit");
    }
    httpd_resp_set_type(request, "image/jpeg");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    const esp_err_t result = httpd_resp_send(request, reinterpret_cast<const char *>(frame->buf), frame->len);
    esp_camera_fb_return(frame);
    return result;
}

static esp_err_t camera_init_profile() {
#if BELLA_CAM_PROFILE_AI_THINKER
    // Enable only after the PCB and OV2640-compatible sensor are confirmed.
    camera_config_t config{};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = 5;
    config.pin_d1 = 18;
    config.pin_d2 = 19;
    config.pin_d3 = 21;
    config.pin_d4 = 36;
    config.pin_d5 = 39;
    config.pin_d6 = 34;
    config.pin_d7 = 35;
    config.pin_xclk = 0;
    config.pin_pclk = 22;
    config.pin_vsync = 25;
    config.pin_href = 23;
    config.pin_sccb_sda = 26;
    config.pin_sccb_scl = 27;
    config.pin_pwdn = 32;
    config.pin_reset = -1;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 18;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    const esp_err_t result = esp_camera_init(&config);
    if (result == ESP_OK) g_camera_ready = true;
    return result;
#else
    ESP_LOGW(TAG, "Camera capture disabled: confirm board and image sensor before selecting a pin profile");
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

static void start_http_server() {
    if (g_http_server) return;
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    config.max_uri_handlers = 4;
    config.stack_size = 6144;
    if (httpd_start(&g_http_server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "Could not start local camera HTTP service");
        return;
    }
    const httpd_uri_t health_uri = {.uri = "/health", .method = HTTP_GET, .handler = health_handler, .user_ctx = nullptr};
    const httpd_uri_t snapshot_uri = {.uri = "/snapshot", .method = HTTP_GET, .handler = snapshot_handler, .user_ctx = nullptr};
    httpd_register_uri_handler(g_http_server, &health_uri);
    httpd_register_uri_handler(g_http_server, &snapshot_uri);
    ESP_LOGI(TAG, "Local camera service listening on port 80 (snapshot requires Bearer token)");
}

static void wifi_event_handler(void *, esp_event_base_t base, int32_t event_id, void *) {
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "Camera Wi-Fi station started");
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        g_wifi_connected = false;
        ESP_LOGW(TAG, "Wi-Fi disconnected; bounded reconnect task will retry");
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        g_wifi_connected = true;
        start_http_server();
        ESP_LOGI(TAG, "Camera board joined Wi-Fi independently");
    }
}

extern "C" void app_main(void) {
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(result);

    const esp_err_t camera_result = camera_init_profile();
    if (camera_result != ESP_OK) {
        ESP_LOGW(TAG, "Camera not initialized: %s", esp_err_to_name(camera_result));
    }
    if (std::strlen(BELLA_CAM_WIFI_SSID) == 0 || std::strlen(BELLA_CAM_TOKEN) < 16) {
        ESP_LOGE(TAG, "Wi-Fi or camera token is missing; configure ignored include/secrets.h");
        return;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, nullptr));
    wifi_config_t wifi_config{};
    std::strncpy(reinterpret_cast<char *>(wifi_config.sta.ssid), BELLA_CAM_WIFI_SSID, sizeof(wifi_config.sta.ssid) - 1);
    std::strncpy(reinterpret_cast<char *>(wifi_config.sta.password), BELLA_CAM_WIFI_PASSWORD, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    if (xTaskCreate(wifi_reconnect_task, "bella_cam_retry", 2048, nullptr, 4, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Camera Wi-Fi retry task creation failed");
    }
    while (!g_wifi_connected) vTaskDelay(pdMS_TO_TICKS(1000));
}
