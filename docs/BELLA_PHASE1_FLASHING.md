# Bella firmware build, flash, and provisioning

This guide supersedes the original Phase 1 notes. Current firmware no longer reads Wi-Fi, device-token, or backend URL macros from `secrets.h`; do not copy the old example or embed credentials in firmware.

## Main ESP32

1. Identify the exact ESP32 board/module, flash size, occupied GPIOs, and attached boot-strapping pulls. Review [the final hardware profile matrix](BELLA_FINAL_HARDWARE_PROFILE_MATRIX.md). Keep Servo 2 on GPIO12 disabled until its reset strap is verified; GPIO21 remains reserved.
2. Install PlatformIO Core, connect the board, and identify its COM port.
3. From the repository root, build the diagnostic image without flashing:

   ```powershell
   .\scripts\build-firmware.ps1 -Profile diagnostic
   ```

   Use a display profile only when the exact physical TFT controller/resolution matches the matrix.
4. After the board, wiring, and COM port are physically checked, flash with the confirmation-gated helper:

   ```powershell
   .\scripts\flash-firmware.ps1 -Profile diagnostic -Port COM7 -Flash
   ```

   The helper requires typing `FLASH COM7` before writing. A build never flashes by itself.
5. Provision Wi-Fi, exact `wss://<host>/ws/device` URL, device ID, and the matching device token over local USB serial. Password/token prompts are hidden:

   ```powershell
   .\scripts\provision-device.ps1 -Port COM7
   ```

   The values are stored in the device's `bella` NVS namespace. NVS is not flash-encrypted. For a confirmed momentary TTP223 only, use the optional `touch4-ptt-momentary` profile; otherwise Touch 4 remains a short Wink reaction.

## Optional ESP32-CAM

Do not use the AI-Thinker profile unless the exact camera PCB and sensor match. The profile remains opt-in. After hardware identification, build/flash `camera-ai-thinker`, then provision over USB with:

```powershell
.\scripts\build-firmware.ps1 -Profile camera-ai-thinker
.\scripts\flash-firmware.ps1 -Profile camera-ai-thinker -Port COM8 -Flash
.\scripts\provision-camera.ps1 -Port COM8
```

Camera Wi-Fi and bearer token are stored in a separate `bella_cam` NVS namespace. The camera serves local HTTP; never expose port 80 or its bearer token over the public Internet. A Railway backend needs an owner-approved authenticated HTTPS/private-tunnel path before camera capture is enabled.

## Acceptance

Follow [the friend setup guide](BELLA_FRIEND_ONE_CLICK_SETUP.md) and [physical acceptance checklist](BELLA_PHYSICAL_ACCEPTANCE_CHECKLIST.md). Builds, mocked camera responses, and simulator tests are not physical acceptance. No firmware in this workspace was flashed.
