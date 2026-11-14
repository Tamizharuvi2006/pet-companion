# Bella Phase 1 build and flashing

## Prerequisites

- PlatformIO Core with the Espressif32 platform and ESP-IDF framework packages (the first build downloads the toolchain and ESP-IDF components).
- Correct board selected in `firmware/bella_esp32/platformio.ini` (`esp32dev` is the current generic classic ESP32 build target, not a verified identification of your physical board/module).
- USB data cable and a known COM port. The repo audit found no serial ports, so no board was available for identification or flashing at that time.

## Configure, build, and flash

1. Copy `firmware/bella_esp32/include/secrets.h.example` to `firmware/bella_esp32/include/secrets.h` and fill in local Wi-Fi, backend WebSocket URL, device ID, and a long random per-device token. This file is ignored by Git. Do not put provider/API keys in firmware.
2. Start the backend bound to the LAN interface: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`. Put the computer's reachable LAN address (not `127.0.0.1`) in the firmware URL. Restrict the Windows firewall rule to the private LAN.
3. Add the matching `device-id=token` to backend `.env` as `BELLA_DEVICE_TOKENS`. Never publish the token.
4. Build without flashing. PlatformIO rejected this checkout's path because it contains spaces, so build from a no-space copy/checkout (for example `C:\bella-backend`) with `pio run -d C:\bella-backend\firmware\bella_esp32`. The same applies to `firmware\bella_esp32_cam`. The current source was compiled successfully from temporary no-space validation copies; no upload was performed.
5. Identify the actual ESP32 model and COM port from the device manager, and verify power/wiring against `BELLA_PHASE1_WIRING.md`.
6. Only after the board, port, and safe wiring are confirmed, flash from the same no-space checkout/copy with `pio run -d C:\bella-backend\firmware\bella_esp32 -t upload --upload-port COMx` (replace `COMx`). No flash operation was performed as part of this implementation.

The main firmware compiles with servos disabled and unknown TFT rendering disabled. Servo 2 is GPIO12 and is independently disabled by `BELLA_SERVO2_GPIO12_ENABLED=0`; turning on the general servo flag does not enable Servo 2. To enable Servo 2 later, first identify the exact ESP32/module and flash voltage, inspect the GPIO12 reset pull state, and only then set `BELLA_GPIO12_STRAP_SAFE_CONFIRMED=1` together with the Servo 2 flag. A compile-time guard rejects Servo 2 enablement without that explicit confirmation. This flag cannot measure the hardware or prove the strap is safe. Espressif documents GPIO12/MTDI as the VDD_SDIO strap: it selects 1.8 V when high and the default 3.3 V when low, with module variants having different pull arrangements. Servo GPIOs initialize without a positioning pulse; a deliberate motion event is required to emit PWM. Keep servo power disconnected during reset/flash validation.

GPIO21 is reserved for the existing physical connection and is not assigned by Bella firmware. The source pin audit lists all planned GPIO uses; compare every wire against it before flashing. If legacy camera UART remains on GPIO14/15, GPIO14 overlaps Touch 3 and GPIO15 needs its own strap review. Do not automatically rewire any such conflict. The firmware audio, Wi-Fi, WebSocket, touch, and distance paths still require physical validation before being considered operational.

## ESP32-CAM

`firmware/bella_esp32_cam` builds a disabled-by-default project. Its optional AI-Thinker pin profile is a convenience only and is not selected by default. Confirm exact PCB and image sensor before enabling. The camera firmware uses its own Wi-Fi and exposes `/health` and authenticated `/snapshot`; configure backend `BELLA_CAMERA_ENABLED`, `BELLA_CAMERA_BASE_URL`, and `BELLA_CAMERA_TOKEN` only after LAN capture is tested.

## Secure remote deployment

Do not send device credentials across public plaintext `ws://`. For Railway use a `wss://` URL with certificate verification (ESP32 firmware uses the ESP certificate bundle when enabled) and a unique secret token. Store camera credentials only in backend environment variables.
