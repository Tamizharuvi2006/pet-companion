# Bella Phase 1 wiring profile

This is the corrected *proposed* pin map from the project request, not a claim that the board or wires have been physically inspected. Confirm the exact DevKit/WROOM, each breakout-board voltage, and the power arrangement before connecting power.

## ESP32 DevKit connections

| Module | Pin | ESP32 |
|---|---|---:|
| SPI TFT (controller not identified) | CS / RST / DC | 5 / 4 / 2 |
| SPI TFT | MOSI / SCK / MISO | 23 / 18 / 19 |
| INMP441 | BCLK / WS / SD | 26 / 25 / 34 |
| INMP441 | L/R | GND (left channel) |
| MAX98357A | BCLK / LRC / DIN | 26 / 25 / 22 |
| TTP223 1–4 OUT | 1 / 2 / 3 / 4 | 32 / 33 / 14 / 27 |
| VL53L0X | SDA / SCL | 16 / 17 |
| SG90 1/2 signal | 1 / 2 | 13 / 12 |
| Existing physical connection (identity not provided) | Reserved, do not reassign | 21 |

Preserve the user's wiring: Servo 1 remains on GPIO13, Servo 2 remains on GPIO12, GPIO21 is reserved for its existing physical connection, and GPIO26 remains the shared I²S BCLK. Touch 4 is GPIO27 after physical rewiring. Do not move or repurpose another pin based on this document alone.

## GPIO allocation audit (firmware profile)

| GPIO | Bella profile use | Audit result |
|---:|---|---|
| 2 | TFT DC | ESP32 boot strap; verify TFT reset/startup loading |
| 4 | TFT reset | ESP32 boot strap; verify TFT reset/startup loading |
| 5 | TFT chip select | ESP32 boot strap; verify TFT reset/startup loading |
| 12 | Servo 2 signal | ESP32 MTDI/VDD_SDIO boot strap; firmware-gated and disabled by default |
| 13 | Servo 1 signal | Unique in the Bella profile |
| 14 | Touch 3 output | Potential conflict if a legacy camera-UART wire is still attached here |
| 16 / 17 | VL53L0X SDA / SCL | No duplicate Bella assignment |
| 18 / 19 / 23 | TFT SCK / MISO / MOSI | No duplicate Bella assignment |
| 21 | Reserved existing physical connection | Intentionally unused by Bella firmware; occupant still needs identification |
| 22 | Speaker I²S DIN | No duplicate Bella assignment |
| 25 | Shared I²S WS/LRC | Intentional mic/speaker full-duplex sharing |
| 26 | Shared I²S BCLK | Intentional mic/speaker full-duplex sharing; not Touch 4 |
| 27 | Touch 4 output | Use after physical rewiring from GPIO26 |
| 32 / 33 | Touch 1 / Touch 2 outputs | No duplicate Bella assignment |
| 34 | Microphone I²S data input | Input-only use |

No duplicate assignments exist in the declared Bella map except the intentional shared I²S WS and BCLK. GPIO21 is reserved because it is already occupied in the physical setup; its device/function was not identified, so inspect it and preserve it. The map is a firmware/configuration audit, not proof of every wire on the physical assembly. If the legacy camera UART is still attached to GPIO14/15, GPIO14 conflicts with Touch 3 and GPIO15 also needs a boot-strap review; stop before flashing and resolve only after inspecting the actual wiring. No automatic changes to those pins are authorized here.

The microphone and amplifier share BCLK and WS as one full-duplex I²S master clock. Firmware uses the ESP-IDF standard I²S driver and a common 16 kHz, 32-bit stereo hardware slot configuration; it converts the selected INMP441 left slot to mono signed 16-bit PCM for the network, and expands speaker PCM for the amplifier. Hardware compatibility still needs measurement on the actual modules.

## Power and boot safety

- Do not power SG90 servos from ESP32 3.3 V. Use a suitably rated regulated 5 V supply and common ground; keep USB/external supply from back-feeding each other.
- Verify the TFT and amplifier module's exact VIN/logic requirements. Connect TFT LED to 3.3 V only if its board supports that input.
- Do not tie MAX98357A `SPK-` to ground. It is a bridge output; connect only the speaker across `SPK+` and `SPK-`.
- Do not enable servo PWM until external power, common ground, mechanical limits, and signal wiring have been checked. Firmware defaults `BELLA_SERVO_ENABLED=0`.
- GPIO2 and GPIO5 are classic ESP32 strapping pins used by the proposed TFT profile. GPIO4 is the TFT reset pin but is not a classic ESP32 strapping pin; inspect attached module pulls on all three lines. GPIO12/MTDI remains the critical flash-voltage strap and must not be used by Servo 2 until its reset-level safety is verified.
- GPIO12/MTDI is sampled at reset to select VDD_SDIO flash voltage on classic ESP32. A high level selects 1.8 V; low selects the 3.3 V default. ESP32 modules differ: some 1.8 V-flash WROVER variants have an external GPIO12 pull-up, while 3.3 V variants generally require it low. Identify the exact module/flash and inspect external pull-ups/down circuitry before using GPIO12 for Servo 2. Do not add or remove a pull resistor based on a generic board name.
- The firmware defaults `BELLA_SERVO2_GPIO12_ENABLED=0`. Enabling it additionally requires setting `BELLA_GPIO12_STRAP_SAFE_CONFIRMED=1` only after the exact board/flash and reset-level checks have passed. This compile-time gate is a human confirmation, not automatic electrical validation. GPIO12 receives no servo PWM before firmware starts (the strap is sampled at reset); after initialization the signal remains low/no-pulse until an explicit motion event. Check that no external pull-up can drive GPIO12 above the ESP32's allowed input level, keep servo power disconnected during reset/flash tests, and once cleared test with the horn/mechanism unloaded and bounded movement.
- Confirm the VL53L0X breakout's pull-ups and I/O voltage before connection.

## Unknown board details / disabled peripherals

The TFT controller/resolution is unknown. The firmware has a diagnostic display adapter but does not select a display driver or draw guessed pixels. Identify the module marking/controller and resolution before enabling a driver.

The ESP32-CAM board and sensor are not confirmed. Its separate firmware builds with camera capture disabled. Do not set the optional AI-Thinker profile until the PCB and sensor are positively identified. The camera profile is separate Wi-Fi; if old GPIO14/15 UART wires remain, treat them as existing wiring and review the GPIO14/Touch 3 and GPIO15 strap conflicts before flashing. Do not rewire them without an explicit pin decision.

The input document does not establish that any of the proposed re-wiring has occurred. The firmware will report peripherals as unverified until physical tests are completed.
