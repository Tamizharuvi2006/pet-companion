#include "bella_config.h"
#include "bella_display.h"

#include "esp_log.h"

static const char *TAG = "bella_display";
static BellaState g_display_state = BellaState::Booting;

void bella_display_init() {
#if BELLA_TFT_CONTROLLER_CONFIRMED
    // Intentionally fail closed: add the verified controller and resolution driver here.
    ESP_LOGE(TAG, "TFT profile enabled without a reviewed controller driver");
#else
    ESP_LOGW(TAG, "TFT disabled: controller/resolution not identified; GPIO profile only");
#endif
}

void bella_display_set_state(BellaState state, const char *diagnostic) {
    g_display_state = state;
    ESP_LOGI(TAG, "display state=%s%s%s", bella_state_name(g_display_state),
             diagnostic ? " diagnostic=" : "", diagnostic ? diagnostic : "");
}
