#include "bella_config.h"
#include "bella_display.h"
#include "bella_face_renderer.h"
#include "bella_tft_profile.h"
#include "bella_device_ws.h"

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"
#include "esp_lcd_io_spi.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"
#include "nvs.h"

#if BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ILI9341_240X320
#include "esp_lcd_ili9341.h"
#elif BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ST7735_128X160
#include "esp_lcd_st7735.h"
#endif

#include <atomic>
#include <algorithm>
#include <cstdio>
#include <cstring>

static const char *TAG = "bella_face";
static std::atomic<BellaState> status{BellaState::Booting};
static QueueHandle_t events = nullptr;
static portMUX_TYPE geometry_lock = portMUX_INITIALIZER_UNLOCKED;
static portMUX_TYPE caption_lock = portMUX_INITIALIZER_UNLOCKED;
static BellaFaceGeometry geometry;
static std::atomic<bool> captions_enabled{true};
static std::atomic<bool> captions_persisted{false};
static char caption_text[256]{};
static std::atomic<bool> display_initialized{false};
static std::atomic<uint32_t> rendered_frames{0};
static std::atomic<uint32_t> render_errors{0};
static std::atomic<uint32_t> last_render_ms{0};

#if BELLA_TFT_PROFILE != BELLA_TFT_PROFILE_DIAGNOSTIC
static esp_lcd_panel_io_handle_t panel_io = nullptr;
static esp_lcd_panel_handle_t panel = nullptr;
static SemaphoreHandle_t color_done = nullptr;
static uint16_t *tile_buffer = nullptr;

static bool lcd_color_done(esp_lcd_panel_io_handle_t, esp_lcd_panel_io_event_data_t *, void *context) {
    auto *semaphore = static_cast<SemaphoreHandle_t>(context);
    BaseType_t woken = pdFALSE;
    if (semaphore) xSemaphoreGiveFromISR(semaphore, &woken);
    return woken == pdTRUE;
}

static bool init_tft_driver() {
    constexpr auto profile = bella_tft_profile();
    color_done = xSemaphoreCreateBinary();
    if (!color_done) return false;
    const size_t bytes = profile.tile_bytes;
    tile_buffer = static_cast<uint16_t *>(heap_caps_malloc(bytes, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));
    if (!tile_buffer) return false;

    spi_bus_config_t bus{};
    bus.sclk_io_num = BELLA_PIN_TFT_SCK;
    bus.mosi_io_num = BELLA_PIN_TFT_MOSI;
    bus.miso_io_num = BELLA_PIN_TFT_MISO;
    bus.quadwp_io_num = -1;
    bus.quadhd_io_num = -1;
    bus.max_transfer_sz = static_cast<int>(bytes);
    esp_err_t result = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "TFT SPI bus init failed: %s", esp_err_to_name(result));
        return false;
    }
    esp_lcd_panel_io_spi_config_t io_config{};
    io_config.cs_gpio_num = static_cast<gpio_num_t>(BELLA_PIN_TFT_CS);
    io_config.dc_gpio_num = static_cast<gpio_num_t>(BELLA_PIN_TFT_DC);
    io_config.spi_mode = 0;
    io_config.pclk_hz = profile.spi_hz;
    io_config.trans_queue_depth = 1;
    io_config.on_color_trans_done = lcd_color_done;
    io_config.user_ctx = color_done;
    io_config.lcd_cmd_bits = 8;
    io_config.lcd_param_bits = 8;
    result = esp_lcd_new_panel_io_spi(SPI2_HOST, &io_config, &panel_io);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "TFT panel IO init failed: %s", esp_err_to_name(result));
        return false;
    }

    esp_lcd_panel_dev_config_t device{};
    device.reset_gpio_num = static_cast<gpio_num_t>(BELLA_PIN_TFT_RESET);
    device.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
    device.bits_per_pixel = profile.bits_per_pixel;
#if BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ST7789_240X240
    result = esp_lcd_new_panel_st7789(panel_io, &device, &panel);
#elif BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ILI9341_240X320
    result = esp_lcd_new_panel_ili9341(panel_io, &device, &panel);
#elif BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ST7735_128X160
    result = esp_lcd_new_panel_st7735(panel_io, &device, &panel);
#endif
    if (result == ESP_OK) result = esp_lcd_panel_reset(panel);
    if (result == ESP_OK) result = esp_lcd_panel_init(panel);
    if (result == ESP_OK) result = esp_lcd_panel_disp_on_off(panel, true);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "TFT controller init failed for %s: %s", profile.name, esp_err_to_name(result));
        return false;
    }
    ESP_LOGW(TAG, "Selected TFT build profile %s; this is not identification of the physical module", profile.name);
    return true;
}

static void draw_caption_overlay(uint16_t *pixels, int width, int height,
                                int first_row, int tile_rows, const char *text);

static bool draw_face(const BellaFaceGeometry &face, const char *caption) {
    constexpr auto profile = bella_tft_profile();
    for (int row = 0; row < profile.height; row += profile.tile_rows) {
        bella_face_renderer::render_tile(face, profile.width, profile.height, row,
                                         profile.tile_rows, tile_buffer);
        if (caption) {
            draw_caption_overlay(tile_buffer, profile.width, profile.height,
                                 row, profile.tile_rows, caption);
        }
        if (esp_lcd_panel_draw_bitmap(panel, 0, row, profile.width,
                                      row + profile.tile_rows, tile_buffer) != ESP_OK) return false;
        // The SPI driver owns the DMA buffer until its completion callback.
        if (xSemaphoreTake(color_done, pdMS_TO_TICKS(500)) != pdTRUE) return false;
    }
    return true;
}

static const uint8_t *glyph_rows(char input) {
    const char value = input >= 'a' && input <= 'z' ? static_cast<char>(input - 'a' + 'A') : input;
#define BELLA_GLYPH(ch, ...) case ch: { static const uint8_t rows[7] = __VA_ARGS__; return rows; }
    switch (value) {
        BELLA_GLYPH('A', {14,17,17,31,17,17,17}) BELLA_GLYPH('B', {30,17,17,30,17,17,30})
        BELLA_GLYPH('C', {14,17,16,16,16,17,14}) BELLA_GLYPH('D', {30,17,17,17,17,17,30})
        BELLA_GLYPH('E', {31,16,16,30,16,16,31}) BELLA_GLYPH('F', {31,16,16,30,16,16,16})
        BELLA_GLYPH('G', {14,17,16,23,17,17,15}) BELLA_GLYPH('H', {17,17,17,31,17,17,17})
        BELLA_GLYPH('I', {14,4,4,4,4,4,14}) BELLA_GLYPH('J', {7,2,2,2,18,18,12})
        BELLA_GLYPH('K', {17,18,20,24,20,18,17}) BELLA_GLYPH('L', {16,16,16,16,16,16,31})
        BELLA_GLYPH('M', {17,27,21,21,17,17,17}) BELLA_GLYPH('N', {17,25,21,19,17,17,17})
        BELLA_GLYPH('O', {14,17,17,17,17,17,14}) BELLA_GLYPH('P', {30,17,17,30,16,16,16})
        BELLA_GLYPH('Q', {14,17,17,17,21,18,13}) BELLA_GLYPH('R', {30,17,17,30,20,18,17})
        BELLA_GLYPH('S', {15,16,16,14,1,1,30}) BELLA_GLYPH('T', {31,4,4,4,4,4,4})
        BELLA_GLYPH('U', {17,17,17,17,17,17,14}) BELLA_GLYPH('V', {17,17,17,17,17,10,4})
        BELLA_GLYPH('W', {17,17,17,21,21,21,10}) BELLA_GLYPH('X', {17,17,10,4,10,17,17})
        BELLA_GLYPH('Y', {17,17,10,4,4,4,4}) BELLA_GLYPH('Z', {31,1,2,4,8,16,31})
        BELLA_GLYPH('0', {14,17,19,21,25,17,14}) BELLA_GLYPH('1', {4,12,4,4,4,4,14})
        BELLA_GLYPH('2', {14,17,1,2,4,8,31}) BELLA_GLYPH('3', {30,1,1,14,1,1,30})
        BELLA_GLYPH('4', {2,6,10,18,31,2,2}) BELLA_GLYPH('5', {31,16,16,30,1,1,30})
        BELLA_GLYPH('6', {14,16,16,30,17,17,14}) BELLA_GLYPH('7', {31,1,2,4,8,8,8})
        BELLA_GLYPH('8', {14,17,17,14,17,17,14}) BELLA_GLYPH('9', {14,17,17,15,1,1,14})
        BELLA_GLYPH('.', {0,0,0,0,0,6,6}) BELLA_GLYPH(',', {0,0,0,0,0,6,4})
        BELLA_GLYPH('!', {4,4,4,4,4,0,4}) BELLA_GLYPH('?', {14,17,1,2,4,0,4})
        BELLA_GLYPH('\'', {4,4,2,0,0,0,0}) BELLA_GLYPH('"', {10,10,5,0,0,0,0})
        BELLA_GLYPH(':', {0,6,6,0,6,6,0}) BELLA_GLYPH(';', {0,6,6,0,6,4,0})
        BELLA_GLYPH('-', {0,0,0,31,0,0,0}) BELLA_GLYPH('+', {0,4,4,31,4,4,0})
        BELLA_GLYPH('/', {1,2,2,4,8,8,16}) BELLA_GLYPH('(', {2,4,8,8,8,4,2})
        BELLA_GLYPH(')', {8,4,2,2,2,4,8}) BELLA_GLYPH('=', {0,0,31,0,31,0,0})
        BELLA_GLYPH(' ', {0,0,0,0,0,0,0})
        default: { static const uint8_t unknown[7] = {31,17,21,21,21,17,31}; return unknown; }
    }
#undef BELLA_GLYPH
}

static void draw_caption_overlay(uint16_t *pixels, int width, int height,
                                 int first_row, int tile_rows, const char *text) {
    if (!pixels || !text || !text[0]) return;
    const int scale = width >= 200 ? 2 : 1;
    const int char_width = 6 * scale;
    const int line_height = 8 * scale;
    const int chars_per_line = std::max(1, (width - 12) / char_width);
    const int line_count = std::clamp((height - 8) / line_height, 1, 3);
    const int area_height = line_count * line_height + 8;
    const int top = height - area_height;
    const size_t length = std::strlen(text);
    const size_t capacity = static_cast<size_t>(chars_per_line * line_count);
    const size_t start = length > capacity ? length - capacity : 0;
    constexpr uint16_t foreground = static_cast<uint16_t>(((240 >> 3) << 11) | ((239 >> 2) << 5) | (255 >> 3));

    for (int y = std::max(top, first_row); y < std::min(height, first_row + tile_rows); ++y) {
        const int local_y = y - first_row;
        // Dim the existing face pixels rather than replacing them: captions sit
        // on top of the animated face, so the eyes remain visible while Bella speaks.
        for (int x = 0; x < width; ++x) {
            const uint16_t pixel = pixels[local_y * width + x];
            const unsigned red = (pixel >> 11) & 0x1f;
            const unsigned green = (pixel >> 5) & 0x3f;
            const unsigned blue = pixel & 0x1f;
            pixels[local_y * width + x] = static_cast<uint16_t>(
                ((red * 2 / 5) << 11) | ((green * 2 / 5) << 5) | (blue * 2 / 5));
        }
    }
    for (size_t index = start; index < length; ++index) {
        const size_t relative = index - start;
        const int line = static_cast<int>(relative / chars_per_line);
        if (line >= line_count) break;
        const int x0 = 6 + static_cast<int>(relative % chars_per_line) * char_width;
        const int y0 = top + 4 + line * line_height;
        const uint8_t *rows = glyph_rows(text[index]);
        for (int gy = 0; gy < 7; ++gy) {
            const int y = y0 + gy * scale;
            if (y < first_row || y >= first_row + tile_rows) continue;
            for (int gx = 0; gx < 5; ++gx) {
                if ((rows[gy] & (1U << (4 - gx))) == 0) continue;
                const int x = x0 + gx * scale;
                for (int sy = 0; sy < scale; ++sy) {
                    for (int sx = 0; sx < scale; ++sx) {
                        const int px = x + sx;
                        const int py = y + sy;
                        if (px < width && py >= first_row && py < first_row + tile_rows)
                            pixels[(py - first_row) * width + px] = foreground;
                    }
                }
            }
        }
    }
}
#endif

struct FaceEvent { FaceState expression; unsigned duration_ms; unsigned pad; };

BellaFaceGeometry bella_display_snapshot() {
    portENTER_CRITICAL(&geometry_lock);
    const auto copy = geometry;
    portEXIT_CRITICAL(&geometry_lock);
    return copy;
}

const char *bella_display_profile_name() { return bella_tft_profile().name; }
bool bella_display_initialized() { return display_initialized.load(); }
uint32_t bella_display_frame_count() { return rendered_frames.load(); }
uint32_t bella_display_error_count() { return render_errors.load(); }
uint32_t bella_display_last_render_ms() { return last_render_ms.load(); }

bool bella_display_captions_enabled() { return captions_enabled.load(); }
bool bella_display_captions_persisted() { return captions_persisted.load(); }

void bella_display_clear_caption() {
    portENTER_CRITICAL(&caption_lock);
    caption_text[0] = '\0';
    portEXIT_CRITICAL(&caption_lock);
}

bool bella_display_set_captions_enabled(bool enabled) {
    captions_enabled.store(enabled);
    bella_display_clear_caption();
    nvs_handle_t handle{};
    if (nvs_open("bella", NVS_READWRITE, &handle) != ESP_OK) {
        captions_persisted.store(false);
        return false;
    }
    const esp_err_t value_result = nvs_set_u8(handle, "captions", enabled ? 1 : 0);
    const esp_err_t commit_result = value_result == ESP_OK ? nvs_commit(handle) : value_result;
    nvs_close(handle);
    const bool saved = commit_result == ESP_OK;
    captions_persisted.store(saved);
    return saved;
}

void bella_display_append_caption(const char *text) {
    if (!captions_enabled.load() || !text) return;
    portENTER_CRITICAL(&caption_lock);
    size_t length = std::strlen(caption_text);
    for (const unsigned char *cursor = reinterpret_cast<const unsigned char *>(text); *cursor; ++cursor) {
        char value = static_cast<char>(*cursor);
        if ((*cursor & 0xC0) == 0x80) continue;
        if (*cursor >= 0x80) value = '?';
        else if (value == '\n' || value == '\r' || value == '\t') value = ' ';
        if (value < 32 || value > 126) continue;
        if (length >= sizeof(caption_text) - 2) {
            constexpr size_t keep = 160;
            std::memmove(caption_text, caption_text + length - keep, keep);
            length = keep;
            caption_text[length] = '\0';
        }
        caption_text[length++] = value;
        caption_text[length] = '\0';
    }
    portEXIT_CRITICAL(&caption_lock);
}

bool bella_display_expression(const char *expression, unsigned duration_ms) {
    if (!events || !expression || duration_ms < 250 || duration_ms > 5000) return false;
    static constexpr const char *names[] = {"idle", "happy", "excited", "love", "curious", "surprised", "sad", "angry", "sleepy", "wink", "listening", "thinking", "speaking", "offline", "error"};
    for (unsigned i = 0; i < 15; ++i) {
        if (std::strcmp(expression, names[i]) == 0) {
            const FaceEvent event{static_cast<FaceState>(i), duration_ms, 0};
            return xQueueOverwrite(events, &event) == pdPASS;
        }
    }
    return false;
}

void bella_display_touch(unsigned pad) {
    if (!events || pad > 3) return;
    constexpr FaceState mapping[] = {FaceState::Happy, FaceState::Love, FaceState::Curious, FaceState::Wink};
    const FaceEvent event{mapping[pad], 1800, pad + 1};
    (void)xQueueOverwrite(events, &event);
}

void bella_display_presence(bool present) {
    if (!present || !events) return;
    const FaceEvent event{FaceState::Curious, 1400, 0};
    (void)xQueueOverwrite(events, &event);
}

static FaceState conversation(BellaState state) {
    switch (state) {
        case BellaState::Listening: return FaceState::Listening;
        case BellaState::Processing: return FaceState::Thinking;
        case BellaState::Speaking: return FaceState::Speaking;
        case BellaState::Error: return FaceState::Error;
        case BellaState::Booting: case BellaState::Connecting: case BellaState::Disconnected: return FaceState::Offline;
        default: return FaceState::Idle;
    }
}

static void animate(void *) {
    BellaFace face;
    uint32_t sequence = 0, last_report = 0, last_touch = 0, error_since = 0;
    bool touched = false;
    while (true) {
        const uint32_t now = static_cast<uint32_t>(esp_timer_get_time() / 1000);
        FaceEvent event{};
        unsigned pad = 0;
        if (xQueueReceive(events, &event, 0) == pdPASS) {
            if (event.pad == 0 || !touched || uint32_t(now - last_touch) >= 250) {
                face.emotion = event.expression;
                face.until = now + event.duration_ms;
                pad = event.pad;
                if (pad) { touched = true; last_touch = now; }
            }
        }
        face.status = conversation(status.load());
        face.tick(now, 0.033f);
        if (face.status == FaceState::Error) {
            if (!error_since) error_since = now;
            if (uint32_t(now - error_since) > 2200) bella_set_state(bella_ws_is_ready() ? BellaState::Idle : BellaState::Disconnected);
        } else error_since = 0;
        const auto next = face.geometry(now);
        portENTER_CRITICAL(&geometry_lock);
        geometry = next;
        portEXIT_CRITICAL(&geometry_lock);

#if BELLA_TFT_PROFILE != BELLA_TFT_PROFILE_DIAGNOSTIC
        if (display_initialized.load()) {
            const int64_t started = esp_timer_get_time();
            char caption[sizeof(caption_text)]{};
            const char *caption_overlay = nullptr;
            if (captions_enabled.load() && status.load() == BellaState::Speaking) {
                portENTER_CRITICAL(&caption_lock);
                std::memcpy(caption, caption_text, sizeof(caption));
                portEXIT_CRITICAL(&caption_lock);
                if (caption[0]) caption_overlay = caption;
            }
            const bool rendered = draw_face(next, caption_overlay);
            if (rendered) {
                rendered_frames.fetch_add(1);
                last_render_ms.store(static_cast<uint32_t>((esp_timer_get_time() - started) / 1000));
            } else {
                render_errors.fetch_add(1);
            }
        }
#endif

        if (bella_ws_is_ready() && (pad || uint32_t(now - last_report) >= 2000)) {
            char report[256];
            std::snprintf(report, sizeof(report),
                "{\"type\":\"face_report\",\"version\":1,\"face_version\":1,\"sequence\":%lu,\"expression\":\"%s\",\"touch_pad\":%s}",
                static_cast<unsigned long>(sequence++),
                bella_state_name(bella_get_state()),
                pad == 1 ? "1" : pad == 2 ? "2" : pad == 3 ? "3" : pad == 4 ? "4" : "null");
            (void)bella_ws_queue_control(report);
            last_report = now;
        }
        vTaskDelay(pdMS_TO_TICKS(33));
    }
}

void bella_display_init() {
    nvs_handle_t handle{};
    uint8_t saved = 1;
    if (nvs_open("bella", NVS_READWRITE, &handle) == ESP_OK) {
        if (nvs_get_u8(handle, "captions", &saved) != ESP_OK) {
            saved = 1;
            const esp_err_t value_result = nvs_set_u8(handle, "captions", saved);
            const esp_err_t commit_result = value_result == ESP_OK ? nvs_commit(handle) : value_result;
            captions_persisted.store(commit_result == ESP_OK);
        } else {
            captions_persisted.store(true);
        }
        nvs_close(handle);
    } else captions_persisted.store(false);
    captions_enabled.store(saved != 0);
    events = xQueueCreate(1, sizeof(FaceEvent));
    if (!events) {
        ESP_LOGE(TAG, "Face event queue allocation failed");
        return;
    }
#if BELLA_TFT_PROFILE != BELLA_TFT_PROFILE_DIAGNOSTIC
    display_initialized.store(init_tft_driver());
    if (!display_initialized.load()) render_errors.fetch_add(1);
#else
    ESP_LOGW(TAG, "TFT driver disabled; identify the panel before selecting a profile");
#endif
    if (xTaskCreate(animate, "bella_face", 4096, nullptr, 3, nullptr) != pdPASS) {
        ESP_LOGE(TAG, "Face task creation failed");
        return;
    }
    ESP_LOGI(TAG, "Face animation engine ready; profile=%s driver=%s",
             bella_display_profile_name(), display_initialized.load() ? "initialized" : "pending");
}

void bella_display_set_state(BellaState value, const char *) {
    status.store(value);
    if (value != BellaState::Speaking) bella_display_clear_caption();
}
