# Bella Render demo — friend hardware handoff

This is the guide to give your hardware helper together with the repository. It
connects the ESP32 hardware to the same Bella service that hosts the browser
demo. The browser and ESP32 use separate WebSocket paths on that one service.

## Links and source

- Browser demo: <https://pet-companion-ha0f.onrender.com/>
- Service health: <https://pet-companion-ha0f.onrender.com/health>
- Hardware Doctor: <https://pet-companion-ha0f.onrender.com/doctor.html>
- Face Studio: <https://pet-companion-ha0f.onrender.com/face.html>
- Source repository: <https://github.com/Tamizharuvi2006/pet-companion>
- ESP32 device WebSocket: `wss://pet-companion-ha0f.onrender.com/ws/device`
- Browser chat WebSocket: `wss://pet-companion-ha0f.onrender.com/ws/chat`

The ESP32 must use `/ws/device`; `/ws/chat` is the browser audio protocol and
is not compatible with the firmware. The Render service may take a while to
wake before the page or device can connect.

## Before the friend starts — owner setup

The presentation browser is intentionally unauthenticated. Keep this demo
private to the presentation: anyone with the public link can use the site and
may consume the owner's OpenRouter credits. The owner does not need to add
`BELLA_ACCESS_PASSWORD` or `BELLA_SESSION_SECRET` for this demo.

For this short presentation, the owner may temporarily enable tokenless ESP
connections. This leaves the public device voice endpoint open to any internet
client, not only the friend, and callers may consume the owner's OpenRouter
credits. Re-enable device authentication after the demonstration. Before
provisioning, the owner must:

1. Confirm the Render service has `ENVIRONMENT=development` for this
   presentation-only, no-login setup.
2. In the Render service environment, set `BELLA_DEVICE_AUTH_REQUIRED=false`
   and save/deploy. This switch is off by default in source and disables only
   the token check on `/ws/device`.
3. Choose a valid device ID, for example `bella-demo-01`; it does not need a
   server token-map entry while demo mode is enabled.
4. Leave the device-token prompt blank when the friend provisions over USB.
5. Confirm `GET /health` returns `200` and, if using the combined audio path,
   that the Render variable `VOICE_ENGINE_DEFAULT` is `gpt_audio_mini`.

With demo authentication disabled, the WSS endpoint accepts any valid device
ID without a token; do not treat the unlisted URL as access control. The
OpenRouter credential stays on the server; the ESP32 does not need it. Never
send the Wi-Fi password or any server/provider credentials to GPT. After the
presentation, set `BELLA_DEVICE_AUTH_REQUIRED=true`, redeploy, and provision a
unique token for any device that should remain connected.

## What hardware this firmware expects

The main firmware targets a **classic ESP32 Dev Module (`esp32dev`)** with a
configured 4 MB flash partition. This does not prove that the friend's board
has that module or flash. First photograph and identify the exact board/module,
flash marking/capacity, USB port and every attached breakout. If the board is
an ESP32-S2/S3/C3, has unknown flash, or does not match the project target,
stop and ask the owner before building or flashing.

The source pin map is below. These are configured assignments, not evidence
that anyone has verified the physical wires. Power off and unplug the board
before wiring. Use printed `GPIOxx` labels, not assumed `Dxx` aliases.

| Part / signal | ESP32 GPIO | Connection notes |
| --- | ---: | --- |
| INMP441 SCK/BCLK | 26 | Shared I²S bit clock with the speaker amp. |
| INMP441 WS/LRCLK | 25 | Shared I²S frame clock with the speaker amp. |
| INMP441 SD/DOUT | 34 | Mic data into ESP32; GPIO34 is input-only. |
| INMP441 L/R | GND | Firmware expects the left I²S slot; do not leave floating. |
| MAX98357A BCLK | 26 | Same shared I²S clock. |
| MAX98357A LRC/LRCLK | 25 | Same shared I²S frame clock. |
| MAX98357A DIN | 22 | Speaker data from ESP32. |
| Speaker | Amp OUT+ and OUT− | Connect across the two amp outputs; neither output is ESP32 GND. |
| TFT CS / RESET / DC | 5 / 4 / 2 | Check strap-pin pulls on GPIO5 and GPIO2; inspect reset pulls on GPIO4. |
| TFT MOSI / SCLK / MISO | 23 / 18 / 19 | TFT labels SDA/SCL may mean SPI MOSI/SCLK; verify its datasheet. |
| Touch 1 / 2 / 3 / 4 signal | 32 / 33 / 14 / 27 | Touch 4 must be physically rewired to GPIO27 first. |
| VL53L0X SDA / SCL | 16 / 17 | Optional; connect only if this exact sensor is present and verified. |
| Servo 1 signal | 13 | Preserve assignment; leave disconnected and disabled for first bring-up. |
| Servo 2 signal | 12 | Preserve assignment; leave disconnected and disabled for first bring-up. |
| Existing connection | 21 | Reserved. Do not move, reuse, or reassign it. |

Use only supplies and logic levels approved for the exact breakout boards.
INMP441 and MAX98357A breakout boards can differ; do not infer their supply
requirements from the chip name alone. Use a common ground where required.
Never power a servo from the ESP32 3V3 pin, and do not connect a speaker
directly to an ESP32 GPIO. Do not power the board simultaneously from USB and
an external source unless the exact board documentation permits it.

### GPIO12 and all pin-conflict checks are mandatory

GPIO12/MTDI is a classic ESP32 boot-strapping pin that affects flash voltage
selection at reset. A pull-up from Servo 2 or another breakout can prevent a
3.3 V-flash board from booting. Keep Servo 2's signal wire disconnected and
both servo outputs disabled. Do not enable Servo 2 until the exact board and
flash are identified, external pull-ups/pull-downs are inspected, and its
reset-time level is confirmed by the owner. GPIO2 and GPIO5 are also classic
ESP32 strapping pins; check the display breakout's reset-time pulls. GPIO21
remains reserved exactly as wired.

Before flashing, the friend must send the owner:

- clear board/module and display front/back photos with part markings visible;
- the exact TFT controller and native resolution;
- a full list of every occupied GPIO and attached device;
- confirmation that Touch 4 was rewired to GPIO27;
- any conflict with the table above, especially GPIO12, GPIO21, GPIO2 or GPIO5.

Do not solve a conflict by moving a pin or editing firmware. Stop and report it
to the owner first. The optional ESP32-CAM is a separate board and is not part
of this display-and-voice bring-up. Do not connect a camera or servos for the
first test.

## Select the display profile only after identifying the panel

The default `diagnostic` firmware disables the TFT driver. It is useful to
check Wi-Fi, device authentication and audio, but it will **not** show the
animated face on the TFT. To render the face, the physical controller and
resolution must exactly match one supported profile:

| Identified TFT | Build profile |
| --- | --- |
| ST7789, 240×240 | `st7789-240x240` |
| ILI9341, 240×320 | `ili9341-240x320` |
| ST7735, 128×160 | `st7735-128x160` |

If the marking/resolution is unknown or does not match exactly, do not guess
or flash a near-match. Send the photos and part number to the owner. Backlight
control is not assigned to a GPIO in the current firmware; follow the exact
display breakout documentation for VCC, GND, BL/LED and logic levels.

## Build, review, flash, and provision

The repo contains the firmware and helper scripts; a web link alone cannot
build or provision the board. On the friend's Windows PC:

1. Clone or download the source repository and install PlatformIO Core (`pio`).
2. Open PowerShell in the repository root. Build the safe diagnostic profile
   first, with no upload:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\scripts\build-firmware.ps1 -Profile diagnostic
   ```

3. For a visible TFT, first identify the exact display and choose its matching
   profile from the table above. Then build that profile. Building does not
   modify the board.
4. Send the owner the complete board/flash/pin audit above. **Wait for the
   owner's approval before flashing.** Do not flash if any conflict or unknown
   board/display detail remains.
5. After approval only, identify the correct COM port in Device Manager and
   run the matching profile. Example for a confirmed ST7789 and COM5:

   ```powershell
   .\scripts\flash-firmware.ps1 -Profile st7789-240x240 -Port COM5 -Flash
   ```

   The script asks for the exact confirmation `FLASH COM5`. That prompt is a
   final safeguard, not a replacement for the owner's approval and pin audit.
6. After the approved firmware is flashed, provision Wi-Fi and the device
   identity over USB. This is a local command; Wi-Fi password and device token
   are hidden at their prompts:

   ```powershell
   .\scripts\provision-device.ps1 -Port COM5
   ```

   Enter the Wi-Fi credentials, the Render device URL above, and the exact
   device ID/token supplied privately by the owner. Provisioning stores
   credentials in device NVS; this firmware does not enable flash encryption,
   so use a trusted device and do not share it with credentials still stored.

The friend must not edit GPIO mappings, enable servos/camera, commit/push code,
change Render settings, or put any credential in source files.

## Verify the connection and demo

1. Open the health link and confirm `200` before the device connects. A free
   Render service may sleep; allow it time to wake.
2. Boot the ESP32 and check the serial monitor at **115200 baud**. Confirm Wi-Fi
   connected, TLS/WSS connected, and the server accepted the device hello. Do
   not copy serial output that contains credentials (the firmware should not
   print them).
3. Open `/doctor.html`, select the device ID, and inspect read-only checks for
   authenticated connection, microphone/speaker readiness and display status.
   A heartbeat/build result is not proof that the TFT pixels or speaker sound
   work; look at the panel and listen to the speaker too.
4. Confirm the eyes animate locally. Test touch pads only after their physical
   GPIOs are checked. Captions default on and can be changed by voice with
   “captions off” / “face only” or “captions on” / “show captions.” The current
   TFT font is basic Latin; do not assume other scripts render correctly.
5. A voice turn uses the server's configured OpenRouter speech recognition
   and reply audio. It can consume API credits. Ask the owner before making the
   first live voice request; start with one short phrase. No provider key is
   needed on the ESP32.
6. Return the exact board/TFT part numbers, profile built/flashed, redacted
   serial logs, doctor results, whether the face visibly rendered, whether
   speech was audible/complete, and any reset/disconnect errors. Never include
   Wi-Fi passwords, device tokens, OpenRouter keys or unredacted provisioning
   payloads in GPT, screenshots, Git or this report.

## Copy/paste prompt for your GPT

Attach this handoff and the repository (or give GPT the source-repository
link), then paste:

> Help me bring up Bella's ESP32 display-and-voice hardware using the attached
> Render handoff and source. First ask me for photos/markings of the exact
> ESP32 board, flash and TFT, plus a full list of occupied GPIOs. Do not guess
> the display profile, change any pin, or enable servos/camera. Preserve Servo 1
> GPIO13, Servo 2 GPIO12 (disconnected and disabled), reserved GPIO21, shared
> I²S BCLK GPIO26, and Touch 4 GPIO27 after physical rewiring. Check classic
> ESP32 strap-pin safety, especially GPIO12, and stop on any unknown/conflict.
> Guide me through a build first; before any flash, require that I report the
> board/pin audit to Bella's owner and obtain the owner's approval. Use the
> Render `wss://pet-companion-ha0f.onrender.com/ws/device` endpoint. Never ask
> me to paste Wi-Fi credentials, device tokens, OpenRouter keys or other
> secrets into chat; tell me to enter them only into the local hidden USB
> provisioning prompts. Do not push code or change Render settings. Clearly
> distinguish firmware build success from actual screen pixels, audible
> speaker output and successful cloud voice acceptance.

## Source documents

- [`BELLA_FRIEND_PIN_CONNECTIONS.md`](BELLA_FRIEND_PIN_CONNECTIONS.md) —
  connector-level wiring, electrical cautions and the GPIO12 strap check.
- [`BELLA_FRIEND_HARDWARE_SETUP.md`](BELLA_FRIEND_HARDWARE_SETUP.md) —
  existing handoff and evidence requirements.
- [`BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md`](BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md) —
  exact firmware/display profiles and board target.
- [`BELLA_PHASE1_PROTOCOL.md`](BELLA_PHASE1_PROTOCOL.md) — device WebSocket
  and audio framing details.
