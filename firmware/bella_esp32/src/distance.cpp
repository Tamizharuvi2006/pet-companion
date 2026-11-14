#include "bella_config.h"
#include "bella_distance.h"
#include "bella_display.h"
#include "bella_runtime.h"

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
extern "C" {
#include "vl53l0x.h"
}

static const char *TAG = "bella_distance";
static i2c_master_bus_handle_t g_i2c_bus = nullptr;
static vl53l0x_handle_t g_sensor = nullptr;
static bool g_present = false;
static uint8_t g_candidate_count = 0;

static void distance_task(void *) {
    uint32_t last_report_ms = 0;
    while (true) {
        bool ready = false;
        if (vl53l0x_get_ready(g_sensor, &ready) == ESP_OK && ready) {
            vl53l0x_data_t data{};
            if (vl53l0x_get_data(g_sensor, &data) == ESP_OK && data.valid) {
                const bool candidate = g_present ? data.distance_mm < 900 : data.distance_mm <= 700;
                bool changed = false;
                if (candidate) {
                    if (g_candidate_count < 3) ++g_candidate_count;
                } else {
                    g_candidate_count = 0;
                }
                if (g_candidate_count >= 3 && candidate != g_present) {
                    g_present = candidate;
                    g_candidate_count = 0;
                    changed = true;
                }
                const uint32_t now = static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS);
                if (changed || now - last_report_ms >= 1000) {
                    bella_set_presence(g_present, data.distance_mm);
                    last_report_ms = now;
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void bella_distance_init() {
    i2c_master_bus_config_t bus_config{};
    bus_config.i2c_port = I2C_NUM_0;
    bus_config.sda_io_num = static_cast<gpio_num_t>(BELLA_PIN_VL53L0X_SDA);
    bus_config.scl_io_num = static_cast<gpio_num_t>(BELLA_PIN_VL53L0X_SCL);
    bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_config.glitch_ignore_cnt = 7;
    bus_config.flags.enable_internal_pullup = true;
    esp_err_t result = i2c_new_master_bus(&bus_config, &g_i2c_bus);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Could not create VL53L0X I2C bus: %s", esp_err_to_name(result));
        bella_display_set_state(bella_get_state(), "distance sensor bus unavailable");
        return;
    }
    result = vl53l0x_create(&g_sensor, g_i2c_bus);
    if (result == ESP_OK) result = vl53l0x_init(g_sensor);
    if (result == ESP_OK) result = vl53l0x_set_profile(g_sensor, VL53L0X_PROFILE_HIGH_SPEED);
    if (result == ESP_OK) result = vl53l0x_set_mode(g_sensor, VL53L0X_MODE_CONTINUOUS_TIMED);
    if (result == ESP_OK) result = vl53l0x_set_inter_measurement(g_sensor, 100);
    if (result == ESP_OK) result = vl53l0x_start_measurement(g_sensor);
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "VL53L0X unavailable/uninitialized: %s", esp_err_to_name(result));
        if (g_sensor) (void)vl53l0x_destroy(g_sensor);
        g_sensor = nullptr;
        return;
    }
    if (xTaskCreate(distance_task, "bella_distance", 4096, nullptr, 3, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Distance task creation failed");
        (void)vl53l0x_stop_measurement(g_sensor, 500);
        (void)vl53l0x_destroy(g_sensor);
        g_sensor = nullptr;
        return;
    }
    ESP_LOGI(TAG, "VL53L0X ranging enabled; presence threshold 700 mm, release 900 mm, 3-sample debounce");
}
