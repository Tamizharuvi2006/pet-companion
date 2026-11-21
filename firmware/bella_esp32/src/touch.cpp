#include "bella_config.h"
#include "bella_touch.h"
#include "bella_touch_gesture.h"
#include "bella_display.h"
#include "bella_device_ws.h"
#include "bella_runtime.h"

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
static constexpr uint32_t PTT_HOLD_MS = BELLA_TOUCH4_PTT_LONG_PRESS_MS;

struct DebounceState { bool raw = false; bool stable = false; TickType_t changed_at = 0; };
static std::array<DebounceState, 4> g_inputs{};
static BellaTouch4Gesture g_touch4_gesture;
static uint32_t g_ptt_turn = 0;

static bool read_pressed(gpio_num_t pin) {
    const bool high = gpio_get_level(pin) != 0;
    return BELLA_TOUCH_ACTIVE_HIGH ? high : !high;
}

static uint32_t now_ms() {
    return static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS);
}

static void on_short_press(size_t index) {
    // The four established short-tap mappings remain visual/local only.
    bella_display_touch(static_cast<unsigned>(index));
}

static void handle_ptt_action(BellaTouch4Action action) {
    switch (action) {
        case BellaTouch4Action::StartPushToTalk:
            g_ptt_turn = bella_ws_begin_recording();
            if (g_ptt_turn == 0) {
                ESP_LOGW(TAG, "Touch 4 long-press was explicit, but voice recording is unavailable");
                bella_display_expression("offline", 1200);
            } else {
                ESP_LOGI(TAG, "Push-to-talk recording started by Touch 4 long press");
            }
            break;
        case BellaTouch4Action::StopPushToTalk:
            if (g_ptt_turn != 0) bella_ws_end_recording(g_ptt_turn);
            g_ptt_turn = 0;
            break;
        case BellaTouch4Action::ShortTap:
            on_short_press(3);
            break;
        case BellaTouch4Action::None:
            break;
    }
}

static void touch_task(void *) {
    for (size_t i = 0; i < g_inputs.size(); ++i) {
        const bool initial = read_pressed(TOUCH_PINS[i]);
        g_inputs[i] = {initial, initial, xTaskGetTickCount()};
    }
    while (true) {
        const TickType_t tick = xTaskGetTickCount();
        const uint32_t clock = now_ms();
        for (size_t i = 0; i < g_inputs.size(); ++i) {
            const bool raw = read_pressed(TOUCH_PINS[i]);
            if (raw != g_inputs[i].raw) {
                g_inputs[i].raw = raw;
                g_inputs[i].changed_at = tick;
            }
            if (raw != g_inputs[i].stable && tick - g_inputs[i].changed_at >= DEBOUNCE_TICKS) {
                g_inputs[i].stable = raw;
                bella_set_touch_event(static_cast<unsigned>(i + 1), raw);
                if (i == 3 && BELLA_TOUCH4_PTT_ENABLED) {
                    if (raw) g_touch4_gesture.press(clock);
                    else handle_ptt_action(g_touch4_gesture.release());
                } else if (raw) {
                    on_short_press(i);
                }
            }
            if (i == 3 && g_inputs[i].stable && BELLA_TOUCH4_PTT_ENABLED) {
                handle_ptt_action(g_touch4_gesture.poll(clock, PTT_HOLD_MS, true));
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
#if BELLA_TOUCH4_PTT_ENABLED
    ESP_LOGW(TAG, "Touch 4 long-press PTT compiled in; use only with verified momentary TTP223 mode");
#else
    ESP_LOGI(TAG, "Touch 4 remains short-tap Wink; PTT is disabled pending TTP223 mode confirmation");
#endif
}
