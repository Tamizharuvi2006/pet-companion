# Bella Friend Setup — Windows, No Source-Code Editing

This guide is for the first physical bring-up after the owner confirms the Railway device token and the friend identifies the actual boards/modules. The friend should only identify, wire, choose a matching profile, build/flash, provision and report diagnostics—never edit Python/C++ source or guess a profile.

## Before the friend starts (owner)

1. Review the local code and docs; configure the production Railway variables listed in `BELLA_RAILWAY_RELEASE_CHECKLIST.md` and deploy through the owner’s normal reviewed release process.
2. Add a random device token under the exact device ID to Railway’s `BELLA_DEVICE_TOKENS`. Keep the token private; it is entered into the provisioning tool, not committed to Git.
3. Send the friend this repository snapshot plus a copy of the GPIO map and physical checklist. Do not send `.env`, provider API keys, browser session secrets, or Railway dashboard access.
4. Provide the exact device ID and the secure endpoint `wss://<your-railway-host>/ws/device` privately. The ID must match the configured server token entry.

## Identify hardware before profile selection

Ask the friend to photograph/record (with private network/passwords out of frame):

- ESP32 board/module label and flash size, USB-UART bridge, and any PSRAM label.
- TFT controller marking/vendor part number, native resolution, module/tab variant, and backlight pin/polarity.
- INMP441, MAX98357A, touch-board and VL53L0X markings; verify logic voltage and common ground from their datasheets.
- Whether each TTP223 output is momentary or toggle/latch.
- Servo model, supply voltage/current, neutral pulse information and whether anything pulls GPIO12 during reset.
- Camera PCB and sensor marking if the separate camera board is included.

Compare the occupied connections against `BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md`. GPIO21 stays reserved; Servo 2 stays on GPIO12 but disabled; shared I²S clocks remain GPIO26/25. If any part does not match, stop and send the part number instead of adapting pins or choosing “close enough.”

## Build and flash the primary board

Install Git and PlatformIO Core (or the PlatformIO IDE extension) on Windows, open PowerShell in the repository folder, and connect only the confirmed ESP32 board by USB. `pio` must be on PATH. The first build downloads pinned ESP-IDF/component dependencies and can take several minutes.

From `D:\final year project\backend`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-firmware.ps1 -Profile diagnostic
```

Only after the board and wiring are confirmed, identify the serial port in Device Manager, then run (replace `COM5` with the exact detected port):

```powershell
.\scripts\flash-firmware.ps1 -Profile diagnostic -Port COM5 -Flash
```

The script verifies the port and asks for the exact phrase `FLASH COM5` before upload. This is an explicit destructive flash step; it is intentionally not run automatically. Use a display profile only after the matrix’s exact controller/resolution/board conditions match, e.g. `-Profile st7789-240x240`. PTT is only selectable with `-Profile touch4-ptt-momentary` after confirming momentary—not toggle—TTP223 operation. No servo-enabled profile is supplied.

## Provision Wi-Fi and device identity

Connect the target by USB and run:

```powershell
.\scripts\provision-device.ps1 -Port COM5
```

Enter the Wi-Fi SSID, `wss://<host>/ws/device`, exact device ID and matching Railway device token when prompted. Password and token prompts are hidden. The tool sends them only over the attached USB serial link and firmware stores them in its `bella` NVS namespace; the firmware does not print them. NVS flash encryption is not enabled, so someone with physical flash access may recover credentials. Use a dedicated/revocable device token and do not expose the USB serial session or share diagnostic photos containing secrets.

The device should reboot, join Wi-Fi and authenticate its WSS device session. Serial output must not show credential values. If provisioning must be cleared, use the explicit reset flow; it requires a second confirmation and erases only Bella’s provisioning NVS namespace:

```powershell
.\scripts\provision-device.ps1 -Port COM5 -Reset
```

Then provision again. Do not mass-erase flash or alter bootloader/partition settings unless the board-specific recovery procedure requires it.

## Optional separate camera board

Camera support is optional. Do not connect or flash it until the exact camera PCB and sensor have been identified. The only enabled pin candidate is AI-Thinker/OV2640; it is not a generic ESP32-CAM profile. From the repository root, the owner/friend can build and then, after verifying the board and COM port, flash it with:

```powershell
.\scripts\build-firmware.ps1 -Profile camera-ai-thinker
.\scripts\flash-firmware.ps1 -Profile camera-ai-thinker -Port COM6 -Flash
.\scripts\provision-camera.ps1 -Port COM6
```

The camera provisioning tool asks for Wi-Fi and a dedicated random camera token; the password and token prompts are hidden, and the values are stored in the camera board's separate `bella_cam` NVS namespace. It does not require creating or editing `secrets.h`. NVS is not flash-encrypted, so use physical access controls and rotate the token if exposed. `-Reset` on the provisioning script requires an exact typed confirmation and erases only `bella_cam` values.

The camera board serves authenticated snapshots over local HTTP. Do not expose its port 80 to the Internet or send the bearer token over a public network. A Railway-hosted backend generally cannot reach a private LAN address; keep the backend camera feature disabled until the owner provides an approved authenticated HTTPS/private-tunnel path.

## Check Hardware Doctor and return results

1. Open the owner-supplied Bella site and sign in.
2. Visit `/doctor.html`, select the device and click **Refresh evidence**.
3. Save the sanitized JSON report and return it with the board/module identifiers and physical test checklist.
4. A `PASS` means only the corresponding device evidence was reported. Display-visible, speaker-audible and physical safety checks stay pending until a person verifies them.
5. A camera frame is captured only after the authorized owner presses the explicit capture button; do not expose the separate camera board’s HTTP port publicly.

Do not run paid voice tests as part of Hardware Doctor. Voice acceptance requires the owner’s separate authorization. Do not connect or activate servos/camera until their specific checklist steps are approved.
