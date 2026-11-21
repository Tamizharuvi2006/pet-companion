#include "bella_audio_i2s.h"
#include "bella_device_ws.h"
#include "bella_distance.h"
#include "bella_display.h"
#include "bella_runtime.h"
#include "bella_servo.h"
#include "bella_touch.h"
#include "bella_wifi.h"
#include "bella_provisioning.h"

#include "esp_err.h"
#include "esp_log.h"
#include "nvs_flash.h"

static const char *TAG = "bella_main";

extern "C" void app_main(void) {
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES || nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_result);
    (void)bella_provision_load();

    bella_runtime_init();
    bella_display_init();
    bella_servo_init();
    if (!bella_audio_init()) {
        bella_set_state(BellaState::Error);
        ESP_LOGE(TAG, "I2S audio unavailable; device will remain diagnostic-only");
    }
    bella_touch_init();
    bella_distance_init();
    bella_ws_init();
    bella_provision_start_serial();
    bella_set_state(BellaState::Connecting);
    bella_wifi_init();
}
