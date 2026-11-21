#include "bella_config.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"
#include "bella_wifi.h"
#include "bella_provisioning.h"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include <cstring>

static const char *TAG = "bella_wifi";
static EventGroupHandle_t g_wifi_events = nullptr;
static constexpr EventBits_t WIFI_CONNECTED = BIT0;
static volatile bool g_wifi_up = false;

static void reconnect_task(void *) {
    uint8_t retries = 0;
    while (true) {
        if (g_wifi_up) {
            retries = 0;
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        const uint32_t delay_ms = retries >= 5 ? 30000U : (1000U << retries);
        vTaskDelay(pdMS_TO_TICKS(delay_ms));
        if (!g_wifi_up) {
            ESP_LOGI(TAG, "Attempting Wi-Fi reconnect");
            esp_wifi_connect();
            if (retries < 5) ++retries;
        }
    }
}

static void wifi_event_handler(void *, esp_event_base_t base, int32_t event_id, void *) {
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "Wi-Fi station started");
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        g_wifi_up = false;
        xEventGroupClearBits(g_wifi_events, WIFI_CONNECTED);
        bella_set_state(BellaState::Connecting);
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        g_wifi_up = true;
        xEventGroupSetBits(g_wifi_events, WIFI_CONNECTED);
        bella_set_state(BellaState::Connecting);
        bella_ws_start();
        ESP_LOGI(TAG, "Wi-Fi connected; backend connection starting");
    }
}

void bella_wifi_init() {
    if (!bella_provision_ready()) {
        ESP_LOGW(TAG, "Waiting for local USB-serial provisioning; network remains offline");
        return;
    }
    g_wifi_events = xEventGroupCreate();
    if (!g_wifi_events) {
        ESP_LOGE(TAG, "Could not allocate Wi-Fi event group");
        bella_set_state(BellaState::Error);
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
    std::strncpy(reinterpret_cast<char *>(wifi_config.sta.ssid), bella_provision_wifi_ssid(), sizeof(wifi_config.sta.ssid) - 1);
    std::strncpy(reinterpret_cast<char *>(wifi_config.sta.password), bella_provision_wifi_password(), sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.pmf_cfg.capable = true;
    wifi_config.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    if (xTaskCreate(reconnect_task, "bella_wifi_retry", 2048, nullptr, 4, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Wi-Fi reconnect task creation failed");
    }
}
