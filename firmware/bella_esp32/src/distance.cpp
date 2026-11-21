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

#include <atomic>

static const char *TAG = "bella_distance";
static i2c_master_bus_handle_t g_i2c_bus = nullptr;
static vl53l0x_handle_t g_sensor = nullptr;
static std::atomic<bool> g_initialized{false}, g_has_valid_sample{false}, g_present{false};
static std::atomic<uint16_t> g_last_mm{0};
static std::atomic<uint32_t> g_invalid_count{0}, g_valid_count{0};
static uint8_t g_candidate_count = 0;

static void distance_task(void *) {
    uint32_t last_report_ms = 0;
    while (true) {
        bool ready = false;
        const esp_err_t ready_result = vl53l0x_get_ready(g_sensor, &ready);
        if (ready_result != ESP_OK) {
            g_invalid_count.fetch_add(1);
        } else if (ready) {
            vl53l0x_data_t data{};
            const esp_err_t data_result = vl53l0x_get_data(g_sensor, &data);
            // Reject invalid status, zero, and physically impossible/out-of-range readings.
            if (data_result != ESP_OK || !data.valid || data.distance_mm == 0 || data.distance_mm > 2000) {
                g_invalid_count.fetch_add(1);
                g_candidate_count = 0;
            } else {
                g_has_valid_sample.store(true);
                g_valid_count.fetch_add(1);
                g_last_mm.store(data.distance_mm);
                const bool currently_present = g_present.load();
                const bool candidate = currently_present
                    ? data.distance_mm < BELLA_PRESENCE_EXIT_MM
                    : data.distance_mm <= BELLA_PRESENCE_ENTER_MM;
                if (candidate) {
                    if (g_candidate_count < 3) ++g_candidate_count;
                } else {
                    g_candidate_count = 0;
                }
                bool changed = false;
                if (g_candidate_count >= 3 && candidate != currently_present) {
                    g_present.store(candidate);
                    g_candidate_count = 0;
                    changed = true;
                }
                const uint32_t now = static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS);
                if (changed || now - last_report_ms >= 1000) {
                    bella_set_presence(g_present.load(), data.distance_mm);
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
    if (result == ESP_OK) result = vl53l0x_create(&g_sensor, g_i2c_bus);
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
    g_initialized.store(true);
    if (xTaskCreate(distance_task, "bella_distance", 4096, nullptr, 3, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Distance task creation failed");
        g_initialized.store(false);
        (void)vl53l0x_stop_measurement(g_sensor, 500);
        (void)vl53l0x_destroy(g_sensor);
        g_sensor = nullptr;
        return;
    }
    ESP_LOGI(TAG, "VL53L0X ready; enter=%u mm exit=%u mm, 3-sample debounce",
             static_cast<unsigned>(BELLA_PRESENCE_ENTER_MM), static_cast<unsigned>(BELLA_PRESENCE_EXIT_MM));
}

bool bella_distance_initialized() { return g_initialized.load(); }
bool bella_distance_has_valid_sample() { return g_has_valid_sample.load(); }
uint16_t bella_distance_last_mm() { return g_last_mm.load(); }
uint32_t bella_distance_invalid_count() { return g_invalid_count.load(); }
uint32_t bella_distance_valid_count() { return g_valid_count.load(); }
