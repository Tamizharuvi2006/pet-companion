#include "bella_config.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"
#include "bella_servo.h"
#include "bella_touch.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <array>

static const char *TAG = "bella_touch";
static constexpr gpio_num_t TOUCH_PINS[] = {
    static_cast<gpio_num_t>(BELLA_PIN_TOUCH_1), static_cast<gpio_num_t>(BELLA_PIN_TOUCH_2),
    static_cast<gpio_num_t>(BELLA_PIN_TOUCH_3), static_cast<gpio_num_t>(BELLA_PIN_TOUCH_4)};
static constexpr TickType_t DEBOUNCE_TICKS = pdMS_TO_TICKS(45);

struct DebounceState {
    bool raw = false;
    bool stable = false;
    TickType_t changed_at = 0;
};
static std::array<DebounceState, 4> g_inputs{};
static uint32_t g_active_turn = 0;

static bool read_pressed(gpio_num_t pin) {
    const bool high = gpio_get_level(pin) != 0;
    return BELLA_TOUCH_ACTIVE_HIGH ? high : !high;
}

static void on_press(size_t index) {
    switch (index) {
        case 0:
            if (g_active_turn != 0) {
                bella_ws_end_recording(g_active_turn);
                g_active_turn = 0;
            } else {
                g_active_turn = bella_ws_begin_recording();
            }
            break;
        case 1:
            if (g_active_turn != 0) {
                bella_ws_cancel(g_active_turn);
                g_active_turn = 0;
            } else if (bella_get_state() == BellaState::Speaking || bella_get_state() == BellaState::Processing) {
                bella_ws_cancel(0);
            }
            break;
        case 2:
            bella_set_pet_reaction();
            break;
        case 3: {
            const bool muted = bella_toggle_muted();
            ESP_LOGI(TAG, "speaker mute=%s", muted ? "true" : "false");
            break;
        }
        default:
            break;
    }
}

static void touch_task(void *) {
    for (size_t i = 0; i < 4; ++i) {
        const bool initial = read_pressed(TOUCH_PINS[i]);
        g_inputs[i] = {initial, initial, xTaskGetTickCount()};
    }
    while (true) {
        const TickType_t now = xTaskGetTickCount();
        for (size_t i = 0; i < g_inputs.size(); ++i) {
            const bool raw = read_pressed(TOUCH_PINS[i]);
            if (raw != g_inputs[i].raw) {
                g_inputs[i].raw = raw;
                g_inputs[i].changed_at = now;
            }
            if (raw != g_inputs[i].stable && now - g_inputs[i].changed_at >= DEBOUNCE_TICKS) {
                g_inputs[i].stable = raw;
                if (raw) on_press(i);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

void bella_touch_init() {
    gpio_config_t config{};
    config.pin_bit_mask = (1ULL << BELLA_PIN_TOUCH_1) | (1ULL << BELLA_PIN_TOUCH_2) |
                          (1ULL << BELLA_PIN_TOUCH_3) | (1ULL << BELLA_PIN_TOUCH_4);
    config.mode = GPIO_MODE_INPUT;
    config.pull_up_en = GPIO_PULLUP_DISABLE;
    config.pull_down_en = BELLA_TOUCH_ACTIVE_HIGH ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE;
    config.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&config));
    if (xTaskCreate(touch_task, "bella_touch", 3072, nullptr, 5, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Touch task creation failed");
    }
}
