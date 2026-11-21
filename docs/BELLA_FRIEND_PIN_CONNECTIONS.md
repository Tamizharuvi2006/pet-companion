# Bella ESP32 display and voice wiring — friend handout

Use this as a source-code pin map, not proof that the wires or modules have been
physically checked. **Power everything off before wiring. First identify the
exact ESP32 board/module, flash size, TFT controller/resolution, and each
breakout. If a marking or voltage is unknown, stop and send a clear photo to the
owner instead of guessing.** Connect by the printed `GPIOxx` label, not an
assumed `Dxx` alias.

## Voice hardware

| Device pin | Connect to ESP32 | Notes |
| --- | --- | --- |
| INMP441 `SCK` / `BCLK` | GPIO26 | Shared I²S bit clock. |
| INMP441 `WS` / `LRCLK` | GPIO25 | Shared I²S word/frame clock. |
| INMP441 `SD` / `DOUT` | GPIO34 | Microphone data into ESP32; GPIO34 is input-only, which is correct here. |
| INMP441 `L/R` | GND | Firmware reads the left I²S slot; do not leave this select pin floating. |
| INMP441 `VDD` and `GND` | Regulated supply appropriate to the identified module; common GND | The INMP441 IC range is 1.62–3.63 V. For a breakout, follow that board's markings/regulator and datasheet. |
| MAX98357A `BCLK` | GPIO26 | Same physical clock as microphone BCLK by design. |
| MAX98357A `LRC` / `LRCLK` | GPIO25 | Same physical clock as microphone WS by design. |
| MAX98357A `DIN` | GPIO22 | Speaker data from ESP32. |
| MAX98357A `VIN` / `GND` | Supply approved for the exact amplifier breakout; common GND with ESP32 | The IC is specified for 2.5–5.5 V, but verify the breakout's VIN and logic requirements. Do not guess from the IC name alone. |
| Speaker terminals | MAX98357A `OUT+` and `OUT−` | Connect the speaker across these two outputs. Neither terminal is ESP32 GND; never connect a speaker directly to ESP32 GPIO. |

The shared I²S clocks are intentional: **GPIO26 = BCLK**, **GPIO25 = WS/LRCLK**.
Keep wires short and ground shared. Do not power a servo from the ESP32 board's
3V3 output. Use only one power source for the ESP32 board at a time, following
the exact board's guide.

## TFT display — identify first, then choose one profile

| TFT signal | ESP32 GPIO |
| --- | ---: |
| `CS` | 5 |
| `RESET` / `RST` | 4 |
| `DC` / `A0` | 2 |
| `MOSI` / `SDA` | 23 |
| `SCLK` / `SCL` | 18 |
| `MISO` / `SDO` | 19 |

Use the TFT breakout's labeled signal names; `SDA`/`SCL` on an SPI TFT mean
MOSI/SCLK, not I²C. The firmware does not assign a backlight GPIO. Connect
`VCC`, `GND`, and `BL/LED` only according to the identified display board's
voltage and backlight requirements. Check its logic levels are ESP32-compatible.

The only compiled screen candidates are:

| Exact identified controller and native resolution | Build profile |
| --- | --- |
| ST7789, 240×240 | `st7789-240x240` |
| ILI9341, 240×320 | `ili9341-240x320` |
| ST7735, 128×160 | `st7735-128x160` |

If the controller/resolution does not match exactly, use `diagnostic` (no TFT
driver) and report the module markings. Do not flash an approximate profile.
GPIO2 and GPIO5 are ESP32 boot strapping pins; check the display breakout's
external pulls and reset-time levels. GPIO4 is not a classic ESP32 strapping pin,
but still check how the TFT reset line is pulled. GPIO12 is a separate,
critical flash-voltage strap described below.

## Existing wiring to preserve / do not enable for this test

| Function | GPIO / status |
| --- | --- |
| Touch 1 / 2 / 3 / 4 | 32 / 33 / 14 / 27; Touch 4 must be physically rewired to GPIO27. |
| VL53L0X SDA / SCL | 16 / 17, only if this sensor is present and verified. |
| Servo 1 signal | GPIO13; leave servo disabled/unpowered during display-and-voice bring-up. |
| Servo 2 signal | GPIO12; preserve this pin assignment but leave its signal wire disconnected and feature disabled. |
| Existing occupied connection | GPIO21; reserved—do not move or reuse it. |

The declared GPIO map has no duplicate assignment except the intentional shared
I²S clocks. If the friend's physical board has any other device on an assigned
pin, stop and send the full pin list; do not move pins in firmware. GPIO14 is
Touch 3, so an old camera signal wired there conflicts. Bella's optional camera
is a separate ESP32-CAM board, not part of this main-board display/voice test.

### GPIO12 / Servo 2 boot safety

On the classic ESP32, GPIO12/MTDI is sampled at reset and affects flash supply
selection: high selects 1.8 V, while low or unconnected selects the default
3.3 V. A pull-up from a servo, peripheral, or breakout can stop a 3.3 V-flash
board from booting. Before anyone connects or enables Servo 2, record the exact
ESP32 module and flash type, inspect the board schematic and all external
pull-ups/pull-downs, and verify the reset level. The software safety gate is not
a substitute for that physical check. Keep both servo outputs disabled for the
friend's initial display/microphone/speaker test.

## Voice, animated face, and optional captions

After the owner has selected the exact TFT profile and flashed the matching
firmware, the device uses one authenticated `wss://<host>/ws/device` connection
for microphone audio, reply text, and speaker audio. Keep the face animation
running at all times. Reply text is sent to the display incrementally and is
overlaid only during speaker playback when captions are enabled. Captions
default to on and are stored in device NVS:

- Say “captions off”, “hide text”, or “face only” to keep the animated face but
  hide Bella's words.
- Say “captions on”, “show captions”, or “show text” to show the reply while
  Bella speaks.

These voice controls currently recognize explicit English phrases. The prompt
asks Bella to answer in the user's language, but transcription and voice
availability vary by language. The current TFT font covers basic Latin
characters only; text in other scripts is not yet legible even if audio works.
Do not promise universal language/display support until tested with the actual
language and panel. Read [`BELLA_VOICE_ENGINE_COMPARISON.md`](BELLA_VOICE_ENGINE_COMPARISON.md)
for the browser/device audio paths and the current Audio Mini API caveat.

The default is `VOICE_ENGINE_DEFAULT=gpt_audio_mini` in Railway variables. The
device still uses the configured OpenRouter speech recognizer before GPT Audio
Mini; GPT Audio Mini generates the reply text and audio together. Its PCM output
is resampled to the established 16 kHz speaker protocol. No GPIO changes are
needed for captions. Do not flash or change the physical pin map for this feature.

## Bring-up order

1. With all power disconnected, photograph the board and module labels and the
   TFT controller/resolution. Audit every occupied GPIO against the tables.
2. Wire only the identified microphone and amplifier/speaker first. Check all
   voltage ratings, common ground, and the speaker's differential `OUT+`/`OUT−`
   wiring.
3. Build the `diagnostic` profile first; it keeps the display driver off while
   the device/network/voice path is checked. From the repository root:

   ```powershell
   .\scripts\build-firmware.ps1 -Profile diagnostic
   ```

4. Flash only after board, wiring, and COM port have been checked and the owner
   has approved the physical step. Follow `BELLA_FRIEND_HARDWARE_SETUP.md` for
   the explicit confirmation prompt and USB/NVS provisioning. Never put Wi-Fi,
   OpenRouter, or device credentials in Git or source files.
5. Only after the TFT marking matches one profile, rebuild with that exact
   profile. Check the hosted `/doctor.html` device evidence and then have the
   owner authorize any paid live speech turn. A successful build or heartbeat
   does not prove visible pixels or audible speaker output.

## References

- Pin assignments and profiles: [`BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md`](BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md)
- Full friend setup and provisioning: [`BELLA_FRIEND_HARDWARE_SETUP.md`](BELLA_FRIEND_HARDWARE_SETUP.md)
- Espressif [ESP32 boot-mode and strapping-pin notes](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html)
- TDK/InvenSense [INMP441 datasheet](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf)
- Analog Devices [MAX98357A/MAX98357B datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf)
