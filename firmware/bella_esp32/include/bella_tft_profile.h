#pragma once

#include <cstdint>

// A profile is an explicit build choice, never an auto-detected hardware claim.
#define BELLA_TFT_PROFILE_DIAGNOSTIC 0
#define BELLA_TFT_PROFILE_ST7789_240X240 1
#define BELLA_TFT_PROFILE_ILI9341_240X320 2
#define BELLA_TFT_PROFILE_ST7735_128X160 3

#ifndef BELLA_TFT_PROFILE
#define BELLA_TFT_PROFILE BELLA_TFT_PROFILE_DIAGNOSTIC
#endif

struct BellaTftProfile {
    const char *name;
    const char *controller;
    uint16_t width;
    uint16_t height;
    uint32_t spi_hz;
    uint8_t bits_per_pixel;
    uint8_t rotation_degrees;
    const char *backlight;
    uint16_t tile_rows;
    uint32_t tile_bytes;
};

constexpr BellaTftProfile bella_tft_profile() {
#if BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ST7789_240X240
    return {"st7789-240x240", "ST7789", 240, 240, 26000000, 16, 0,
            "not controlled (GPIO not assigned; module behavior must be checked)", 16, 240U * 16U * 2U};
#elif BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ILI9341_240X320
    return {"ili9341-240x320", "ILI9341", 240, 320, 26000000, 16, 0,
            "not controlled (GPIO not assigned; module behavior must be checked)", 16, 240U * 16U * 2U};
#elif BELLA_TFT_PROFILE == BELLA_TFT_PROFILE_ST7735_128X160
    return {"st7735-128x160", "ST7735", 128, 160, 26000000, 16, 0,
            "not controlled (GPIO not assigned; module behavior must be checked)", 16, 128U * 16U * 2U};
#else
    return {"diagnostic-disabled", "unidentified", 0, 0, 0, 0, 0,
            "not controlled", 0, 0};
#endif
}

static_assert(BELLA_TFT_PROFILE >= BELLA_TFT_PROFILE_DIAGNOSTIC &&
              BELLA_TFT_PROFILE <= BELLA_TFT_PROFILE_ST7735_128X160,
              "Unknown TFT profile; supported builds are diagnostic, ST7789 240x240, ILI9341 240x320, ST7735 128x160");
