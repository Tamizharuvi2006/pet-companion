#include "bella_config.h"
#include "bella_servo.h"

#include "driver/ledc.h"
#include "driver/gpio.h"
#include "esp_log.h"

static const char *TAG = "bella_servo";
static constexpr uint32_t SERVO_HZ = 50;
static constexpr uint32_t SERVO_PERIOD_US = 20000;
static constexpr uint32_t SERVO_MIN_US = 600;
static constexpr uint32_t SERVO_MAX_US = 2300;

#if BELLA_SERVO_ENABLED
static uint32_t pulse_duty(uint32_t pulse_us) {
    return (pulse_us * ((1U << 16) - 1U)) / SERVO_PERIOD_US;
}
#endif

void bella_servo_init() {
#if BELLA_SERVO_ENABLED
    ledc_timer_config_t timer{};
    timer.speed_mode = LEDC_LOW_SPEED_MODE;
    timer.duty_resolution = LEDC_TIMER_16_BIT;
    timer.timer_num = LEDC_TIMER_0;
    timer.freq_hz = SERVO_HZ;
    timer.clk_cfg = LEDC_AUTO_CLK;
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    const gpio_num_t pins[] = {static_cast<gpio_num_t>(BELLA_PIN_SERVO_1), static_cast<gpio_num_t>(BELLA_PIN_SERVO_2)};
    const int channel_count = BELLA_SERVO2_GPIO12_ENABLED ? 2 : 1;
    for (int channel = 0; channel < channel_count; ++channel) {
        ledc_channel_config_t config{};
        config.gpio_num = pins[channel];
        config.speed_mode = LEDC_LOW_SPEED_MODE;
        config.channel = static_cast<ledc_channel_t>(channel);
        config.intr_type = LEDC_INTR_DISABLE;
        config.timer_sel = LEDC_TIMER_0;
        // Do not issue a positioning pulse during startup; an explicit motion event is required.
        config.duty = 0;
        config.hpoint = 0;
        ESP_ERROR_CHECK(ledc_channel_config(&config));
    }
    ESP_LOGW(TAG, "Servo 1 PWM enabled; Servo 2 GPIO12 %s", BELLA_SERVO2_GPIO12_ENABLED ? "enabled after strap confirmation" : "disabled");
#else
    ESP_LOGI(TAG, "Servo PWM disabled (safe default)");
#endif
}

void bella_servo_emote(unsigned int motion) {
#if BELLA_SERVO_ENABLED
    // Conservative fixed poses only; no unrestricted sweep. Future calibration can tune them.
    const uint32_t pulse = motion == 1 ? 1580 : 1500;
    const uint32_t safe_pulse = pulse < SERVO_MIN_US ? SERVO_MIN_US : (pulse > SERVO_MAX_US ? SERVO_MAX_US : pulse);
    const int channel_count = BELLA_SERVO2_GPIO12_ENABLED ? 2 : 1;
    for (int channel = 0; channel < channel_count; ++channel) {
        ledc_set_duty(LEDC_LOW_SPEED_MODE, static_cast<ledc_channel_t>(channel), pulse_duty(safe_pulse));
        ledc_update_duty(LEDC_LOW_SPEED_MODE, static_cast<ledc_channel_t>(channel));
    }
#else
    (void)motion;
#endif
}

void bella_servo_emergency_stop() {
#if BELLA_SERVO_ENABLED
    // Disable signal generation; this does not disconnect external servo power.
    ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
#if BELLA_SERVO2_GPIO12_ENABLED
    ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 0);
#endif
#endif
}
