#include "bella_cam_provisioning.h"
#include "bella_cam_policy.h"

#include "cJSON.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "nvs.h"

#include <cstdio>
#include <cstring>

namespace {
constexpr const char *TAG = "bella_cam_provision";
struct Config {
    char ssid[33]{};
    char password[65]{};
    char token[193]{};
};
Config g_config{};
bool g_ready = false;

bool read_string(nvs_handle_t handle, const char *key, char *out, size_t capacity) {
    size_t length = capacity;
    const esp_err_t result = nvs_get_str(handle, key, out, &length);
    return result == ESP_OK && length > 0 && length <= capacity && out[length - 1] == '\0';
}

bool valid_config(const Config &config) {
    return bella_cam_policy::valid_ssid(config.ssid) &&
        bella_cam_policy::valid_password(config.password) &&
        bella_cam_policy::valid_token(config.token);
}

bool json_string(const cJSON *root, const char *key, char *out, size_t capacity) {
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsString(value) || !value->valuestring) return false;
    const size_t length = std::strlen(value->valuestring);
    if (length == 0 || length >= capacity) return false;
    std::memcpy(out, value->valuestring, length + 1);
    return true;
}

bool save_config(const Config &config) {
    nvs_handle_t handle{};
    if (nvs_open("bella_cam", NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_set_str(handle, "wifi_ssid", config.ssid);
    if (result == ESP_OK) result = nvs_set_str(handle, "wifi_password", config.password);
    if (result == ESP_OK) result = nvs_set_str(handle, "camera_token", config.token);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}

bool accept_line(const char *line) {
    constexpr char prefix[] = "BELLA-CAM1:";
    if (std::strncmp(line, prefix, sizeof(prefix) - 1) != 0) return false;
    const char *encoded = line + sizeof(prefix) - 1;
    const size_t encoded_length = std::strlen(encoded);
    if (encoded_length == 0 || encoded_length > 1024) return false;
    unsigned char decoded[768]{};
    size_t decoded_length = 0;
    if (mbedtls_base64_decode(decoded, sizeof(decoded) - 1, &decoded_length,
                              reinterpret_cast<const unsigned char *>(encoded), encoded_length) != 0 ||
        decoded_length == 0) return false;
    decoded[decoded_length] = '\0';
    cJSON *root = cJSON_ParseWithLength(reinterpret_cast<const char *>(decoded), decoded_length);
    if (!root) return false;
    Config candidate{};
    const bool parsed = json_string(root, "ssid", candidate.ssid, sizeof(candidate.ssid)) &&
        json_string(root, "password", candidate.password, sizeof(candidate.password)) &&
        json_string(root, "camera_token", candidate.token, sizeof(candidate.token));
    cJSON_Delete(root);
    if (!parsed || !valid_config(candidate) || !save_config(candidate)) return false;
    g_config = candidate;
    g_ready = true;
    return true;
}

void serial_task(void *) {
    std::printf("BELLA-CAM-PROVISION READY\r\n");
    char line[1100]{};
    while (true) {
        if (!std::fgets(line, sizeof(line), stdin)) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        const size_t length = std::strlen(line);
        if (length == 0 || length >= sizeof(line) - 1 || line[length - 1] != '\n') {
            std::printf("BELLA-CAM-PROVISION REJECTED\r\n");
            int ch = 0;
            while ((ch = std::fgetc(stdin)) != '\n' && ch != EOF) {}
            continue;
        }
        line[length - 1] = '\0';
        if (length > 1 && line[length - 2] == '\r') line[length - 2] = '\0';
        if (std::strcmp(line, "BELLA-CAM-PROVISION?") == 0) {
            std::printf("BELLA-CAM-PROVISION READY\r\n");
            continue;
        }
        if (std::strcmp(line, "BELLA-CAM-PROVISION-RESET") == 0) {
            nvs_handle_t handle{};
            if (nvs_open("bella_cam", NVS_READWRITE, &handle) == ESP_OK) {
                const esp_err_t erased = nvs_erase_all(handle);
                const esp_err_t committed = erased == ESP_OK ? nvs_commit(handle) : erased;
                nvs_close(handle);
                if (committed == ESP_OK) {
                    std::printf("BELLA-CAM-PROVISION RESET; rebooting\r\n");
                    vTaskDelay(pdMS_TO_TICKS(300));
                    esp_restart();
                }
            }
            std::printf("BELLA-CAM-PROVISION RESET-FAILED\r\n");
            continue;
        }
        if (accept_line(line)) {
            std::printf("BELLA-CAM-PROVISION SAVED; rebooting\r\n");
            vTaskDelay(pdMS_TO_TICKS(300));
            esp_restart();
        }
        std::printf("BELLA-CAM-PROVISION REJECTED; check format and lengths\r\n");
    }
}
} // namespace

bool bella_cam_provision_load() {
    Config candidate{};
    nvs_handle_t handle{};
    if (nvs_open("bella_cam", NVS_READONLY, &handle) != ESP_OK) return false;
    const bool loaded = read_string(handle, "wifi_ssid", candidate.ssid, sizeof(candidate.ssid)) &&
        read_string(handle, "wifi_password", candidate.password, sizeof(candidate.password)) &&
        read_string(handle, "camera_token", candidate.token, sizeof(candidate.token));
    nvs_close(handle);
    if (!loaded || !valid_config(candidate)) return false;
    g_config = candidate;
    g_ready = true;
    return true;
}

bool bella_cam_provision_ready() { return g_ready; }
const char *bella_cam_wifi_ssid() { return g_config.ssid; }
const char *bella_cam_wifi_password() { return g_config.password; }
const char *bella_cam_token() { return g_config.token; }

void bella_cam_provision_start_serial() {
    if (xTaskCreate(serial_task, "bella_cam_provision", 4096, nullptr, 2, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Could not create local USB-serial provisioning task");
    }
}
