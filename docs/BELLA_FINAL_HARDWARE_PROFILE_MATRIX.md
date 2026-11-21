# Bella Final Hardware Profile Matrix

Every entry is a compile-time candidate, not an identified physical part. Default firmware selects the diagnostic-disabled TFT. Never flash a display candidate until its controller, resolution, board, and wiring match the actual module.

## ESP32 firmware profiles

| Build script profile | PlatformIO environment | Driver/feature | Resolution / format | SPI / rotation | Memory and backlight |
|---|---|---|---|---|---|
| `diagnostic` | `bella_esp32` | TFT driver disabled | none | none | no display buffer; backlight not controlled |
| `st7789-240x240` | `bella_esp32_st7789_240x240` | ESP-IDF ST7789 | 240×240 RGB565 | 26 MHz, rotation 0 | 16-row internal DMA tile, 7,680 bytes; no backlight GPIO assigned |
| `ili9341-240x320` | `bella_esp32_ili9341_240x320` | Espressif ILI9341 component | 240×320 RGB565 | 26 MHz, rotation 0 | 16-row internal DMA tile, 7,680 bytes; no backlight GPIO assigned |
| `st7735-128x160` | `bella_esp32_st7735_128x160` | Waveshare `esp_lcd_st7735` component | 128×160 RGB565 | 26 MHz, rotation 0 | 16-row internal DMA tile, 4,096 bytes; no backlight GPIO assigned |
| `touch4-ptt-momentary` | `bella_esp32_touch4_ptt_momentary` | Base diagnostic TFT + explicit Touch 4 long-press PTT | no TFT selected | no TFT selected | PTT profile is only for a physically verified momentary TTP223; toggle/latch mode is unsupported |

Camera profiles build in the separate `firmware/bella_esp32_cam` project:

| Build script profile | PlatformIO environment | Behavior |
|---|---|---|
| `camera-disabled` | `bella_esp32_cam` | Camera pin map disabled; after local USB/NVS Wi-Fi provisioning, health reports degraded/disabled state |
| `camera-ai-thinker` | `bella_esp32_cam_ai_thinker` | Candidate AI-Thinker/OV2640 pin map; select only after exact PCB and sensor identification; Wi-Fi/token are provisioned locally to NVS |

The ST7735 candidate uses a published `esp_lcd` component, but a generic controller driver does not settle the module’s tab color, RAM offsets, backlight polarity or breakout wiring; inspect the exact display first. [Component registry reference](https://components.espressif.com/components/waveshare/esp_lcd_st7735/versions/2.0.0/readme?language=en)

## Board/toolchain target

- PlatformIO board target: `esp32dev` / Espressif ESP32 Dev Module.
- Toolchain observed: Espressif32 7.0.1, ESP-IDF 6.0.1.
- Partition configuration selects a 4 MiB target with about 3 MiB app partition. This does not prove the actual board’s flash size, module variant, boot voltage strap, USB bridge, PSRAM or antenna.
- The source-only hardware renderer uses no full-screen framebuffer or PSRAM. Build memory reports are in the completion report; runtime heap and achievable frame rate need device measurement.

## Preserved physical GPIO map

| Function | GPIO |
|---|---:|
| TFT CS / RESET / DC | 5 / 4 / 2 |
| TFT MOSI / SCK / MISO | 23 / 18 / 19 |
| INMP441 BCLK / WS / SD | 26 / 25 / 34 |
| MAX98357A BCLK / LRC / DIN | 26 / 25 / 22 |
| Touch sensor 1 / 2 / 3 / 4 | 32 / 33 / 14 / 27 |
| VL53L0X SDA / SCL | 16 / 17 |
| Servo 1 | 13, disabled by default |
| Servo 2 | 12, safety-gated and disabled by default |
| Reserved existing connection | GPIO21; unchanged |

Shared I²S clocks on GPIO26/25 are intentional. Touch 4 is GPIO27 only after the stated physical rewiring. On the classic ESP32, GPIO2, GPIO5, GPIO12/MTDI and GPIO15 are strapping pins; GPIO4 is not, though the TFT reset line's external pull should still be inspected. GPIO12 must remain disconnected from Servo 2 until the exact board/flash voltage, strap circuit, external pulls, and reset level are confirmed. GPIO14 has a legacy camera conflict; the camera is on a separate board in its optional profile. No other pins are automatically reassigned. See [`BELLA_FRIEND_PIN_CONNECTIONS.md`](BELLA_FRIEND_PIN_CONNECTIONS.md) before physical wiring.

## Profile selection gates

1. Read the ESP32 module label and record the exact module/board and flash capacity.
2. Read the TFT controller marking or vendor listing; record controller, native resolution, panel variant/tab, flex/breakout, voltage and backlight wiring.
3. Compare every occupied GPIO with this map and the board’s boot strap pins.
4. Choose exactly one display profile. If the display is not one of the declared profiles, do not guess or flash; record the part number for a driver/offset profile.
5. Keep servo and camera outputs disabled until the physical checklist authorizes their separate test.

## Not yet supported or established

- ST7735 80×160/128×128 modules and variants with different address-window offsets: no profile.
- Unknown controller, parallel/RGB display, touchscreen or display backlight pin: no profile.
- GPIO21 remains reserved; it is not reused.
- Physical camera model and its public/private network path are not established by firmware compilation.
