# Friend's Bella hardware handoff

No hardware was flashed or physically validated. Do not guess the display driver.

## Parts and wiring from source configuration

ESP32 development-module profile (actual board/flash must be confirmed), INMP441 microphone, MAX98357A amplifier/speaker, four TTP223 pads, TFT of unknown controller/resolution, VL53L0X, and two planned servos. ESP32-CAM is a separate existing project, not activated in this phase.

| Connection | Source-configured GPIO |
| --- | --- |
| TFT CS / reset / DC | 5 / 4 / 2 |
| TFT MOSI / SCLK / MISO | 23 / 18 / 19 |
| Shared I2S BCLK / WS | 26 / 25 |
| Microphone data / speaker data | 34 / 22 |
| Touch 1 / 2 / 3 / 4 | 32 / 33 / 14 / 27 |
| VL53L0X SDA / SCL | 16 / 17 |
| Servo 1 / Servo 2 | 13 / 12; disabled by default |
| GPIO21 | Reserved for existing physical connection; do not repurpose |

These are source assignments, not verified physical wiring. Touch4 must actually be rewired to GPIO27. Confirm TFT controller, dimensions, rotation, supply/logic levels and SPI compatibility before enabling rendering. GPIO2/5 are strap-sensitive; review their reset pulls. GPIO12/MTDI can select flash voltage at reset: verify exact board/flash voltage and external pull-ups before enabling Servo2. Keep all servo enable/safety flags off during this handoff. Check the complete physical occupied-pin list before flashing.

## Configure and build

1. Install PlatformIO with the existing pinned `espressif32@7.0.1` / ESP-IDF project. Board profile is `esp32dev`, configured for 4 MB flash; confirm this matches the actual module first.
2. Copy `firmware/bella_esp32/include/secrets.h.example` to ignored `secrets.h`. Privately configure SSID, password, `wss://<developer-provided-host>/ws/device`, device ID and the matching device-only credential. Never add OpenRouter or Railway account credentials. Do not commit or share this file.
3. Leave `BELLA_ALLOW_INSECURE_LOCAL_WS=0` and certificate verification enabled. A public HTTPS deployment requires WSS. No TFT driver/rotation/resolution setting is enabled while the display is unidentified.
4. Build from a path without spaces. On Windows, when drive R is unused:

```powershell
subst R: 'D:\final year project\backend'
pio run -d R:\firmware\bella_esp32
```

For your own checkout, substitute its real path. The drive alias works around ESP-IDF rejecting whitespace; it does not copy/move the project. Remove only your alias afterward with `subst R: /D`.

5. **Only after wiring/board review and the hardware owner's approval**, flash and monitor (replace COM port):

```powershell
pio run -d R:\firmware\bella_esp32 -t upload --upload-port COM7
pio device monitor -d R:\firmware\bella_esp32 --port COM7
```

## First connection checks

Power safely; confirm Wi-Fi connects, then serial reports authenticated device session ready. Developer signs into hosted `/face.html`, selects Connected Device mode and sees presence/heartbeat. Touch pads should map to happy/love/curious/wink without voice requests or servo movement. Dashboard distinguishes conversation state and reported face state.

The generic face task runs locally at approximately 30 Hz with a bounded latest-event queue. **No pixels will appear on the physical TFT yet**: its driver remains intentionally disabled. An engine acknowledgement is not proof of screen rendering. Test losing/recovering Wi-Fi and backend connectivity; expect offline state and reconnect, then fresh reports. Do not run paid voice tests without the developer's separate authorization.

Return: actual board and flash marking, TFT controller/resolution/rotation, redacted build/boot and connection logs, per-pad results, disconnect/reconnect behavior and any reset failures. Never send tokens/passwords, ignored configuration files or unredacted auth payloads.
