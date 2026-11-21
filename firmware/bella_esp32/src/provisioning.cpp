#include "bella_provisioning.h"
#include "bella_backend_url_policy.h"

#include "cJSON.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "nvs.h"
#include "nvs_flash.h"

#include <cstdio>
#include <cstring>

namespace {
constexpr const char *TAG = "bella_provision";
struct Config {
    char ssid[33]{};
    char password[65]{};
    char backend_url[193]{};
    char device_id[65]{};
    char device_token[193]{};
};
Config g_config{};
bool g_ready = false;

bool read_string(nvs_handle_t handle, const char *key, char *out, size_t capacity) {
    size_t length = capacity;
    const esp_err_t result = nvs_get_str(handle, key, out, &length);
    return result == ESP_OK && length > 0 && length <= capacity && out[length - 1] == '\0';
}

bool valid_device_id(const char *value) {
    const size_t length = std::strlen(value);
    if (length == 0 || length > 64) return false;
    for (size_t i = 0; i < length; ++i) {
        const char c = value[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.')) return false;
    }
    return true;
}

bool valid_config(const Config &config) {
    const size_t ssid_length = std::strlen(config.ssid);
    const size_t password_length = std::strlen(config.password);
    const size_t url_length = std::strlen(config.backend_url);
    const size_t token_length = std::strlen(config.device_token);
    return ssid_length > 0 && ssid_length <= 32 &&
           password_length >= 8 && password_length <= 64 &&
           url_length > 12 && url_length <= 192 &&
           bella_backend_url_is_valid_wss(config.backend_url) &&
           valid_device_id(config.device_id) && token_length >= 16 && token_length <= 192 &&
           std::strspn(config.device_token, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-") == token_length;
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
    if (nvs_open("bella", NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_set_str(handle, "wifi_ssid", config.ssid);
    if (result == ESP_OK) result = nvs_set_str(handle, "wifi_password", config.password);
    if (result == ESP_OK) result = nvs_set_str(handle, "backend_url", config.backend_url);
    if (result == ESP_OK) result = nvs_set_str(handle, "device_id", config.device_id);
    if (result == ESP_OK) result = nvs_set_str(handle, "device_token", config.device_token);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}

bool accept_line(const char *line) {
    constexpr char prefix[] = "BELLA1:";
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
        json_string(root, "backend_ws_url", candidate.backend_url, sizeof(candidate.backend_url)) &&
        json_string(root, "device_id", candidate.device_id, sizeof(candidate.device_id)) &&
        json_string(root, "device_token", candidate.device_token, sizeof(candidate.device_token));
    cJSON_Delete(root);
    if (!parsed || !valid_config(candidate) || !save_config(candidate)) return false;
    g_config = candidate;
    g_ready = true;
    return true;
}

void serial_task(void *) {
    std::printf("BELLA-PROVISION READY\r\n");
    std::printf("Send one BELLA1:<base64-json> line. Credentials are never echoed by firmware.\r\n");
    char line[1100]{};
    while (true) {
        if (!std::fgets(line, sizeof(line), stdin)) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        const size_t length = std::strlen(line);
        if (length == 0 || length >= sizeof(line) - 1 || line[length - 1] != '\n') {
            std::printf("BELLA-PROVISION REJECTED\r\n");
            int ch = 0;
            while ((ch = std::fgetc(stdin)) != '\n' && ch != EOF) {}
            continue;
        }
        line[length - 1] = '\0';
        if (length > 1 && line[length - 2] == '\r') line[length - 2] = '\0';
        if (std::strcmp(line, "BELLA-PROVISION?") == 0) {
            std::printf("BELLA-PROVISION READY\r\n");
            continue;
        }
        if (std::strcmp(line, "BELLA-PROVISION-RESET") == 0) {
            nvs_handle_t handle{};
            if (nvs_open("bella", NVS_READWRITE, &handle) == ESP_OK) {
                const esp_err_t erased = nvs_erase_all(handle);
                const esp_err_t committed = erased == ESP_OK ? nvs_commit(handle) : erased;
                nvs_close(handle);
                if (committed == ESP_OK) {
                    std::printf("BELLA-PROVISION RESET; rebooting\r\n");
                    vTaskDelay(pdMS_TO_TICKS(300));
                    esp_restart();
                }
            }
            std::printf("BELLA-PROVISION RESET-FAILED\r\n");
            continue;
        }
        if (accept_line(line)) {
            std::printf("BELLA-PROVISION SAVED; rebooting\r\n");
            vTaskDelay(pdMS_TO_TICKS(300));
            esp_restart();
        }
        std::printf("BELLA-PROVISION REJECTED; check format and lengths\r\n");
    }
}
} // namespace

bool bella_provision_load() {
    Config candidate{};
    nvs_handle_t handle{};
    if (nvs_open("bella", NVS_READONLY, &handle) != ESP_OK) return false;
    const bool loaded = read_string(handle, "wifi_ssid", candidate.ssid, sizeof(candidate.ssid)) &&
        read_string(handle, "wifi_password", candidate.password, sizeof(candidate.password)) &&
        read_string(handle, "backend_url", candidate.backend_url, sizeof(candidate.backend_url)) &&
        read_string(handle, "device_id", candidate.device_id, sizeof(candidate.device_id)) &&
        read_string(handle, "device_token", candidate.device_token, sizeof(candidate.device_token));
    nvs_close(handle);
    if (!loaded || !valid_config(candidate)) return false;
    g_config = candidate;
    g_ready = true;
    return true;
}

bool bella_provision_ready() { return g_ready; }
const char *bella_provision_wifi_ssid() { return g_config.ssid; }
const char *bella_provision_wifi_password() { return g_config.password; }
const char *bella_provision_backend_url() { return g_config.backend_url; }
const char *bella_provision_device_id() { return g_config.device_id; }
const char *bella_provision_device_token() { return g_config.device_token; }

void bella_provision_start_serial() {
    if (xTaskCreate(serial_task, "bella_provision", 4096, nullptr, 2, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Could not create local USB-serial provisioning task");
    }
}
