# Bella Phase 2A — Face prototype

## Implemented

Standalone preview: `/face.html` on the existing static server, or open
`app/frontend/face.html` locally. It uses canvas primitives, smooth time-based
morphing, randomized blinks, four simulated touch pads, mock conversation controls,
reduced motion and animation-speed controls. It makes no fetch, WebSocket, audio,
microphone or provider calls. Existing voice frontend and backend are unchanged.

States: IDLE, HAPPY, EXCITED, LOVE, CURIOUS, SURPRISED, SAD, ANGRY, SLEEPY,
WINK, LISTENING, THINKING, SPEAKING, OFFLINE, ERROR.

Touch mappings: 1 happy, 2 love, 3 curious, 4 wink. A latest-event slot holds an
emotion for 1.8 seconds; conversation/error/offline status takes precedence.
Rapid events within 250 ms are suppressed. Existing firmware inputs retain their
45 ms debounce and rising-edge detection. Legacy recording/cancellation/mute/pet
servo touch actions are disabled for this phase: touch now only updates a local
face model and logs the reaction.

`firmware/bella_esp32/include/bella_face.h` is an allocation-free generic C++
state/interpolation model. A future display-task owner must call tick and render
its values. It is not yet a physical display renderer, nor is it wired to the
display state callback. The simulator and firmware share documented semantics,
not a single executable implementation. Firmware integration remains partial.

## Hardware audit

The existing config matches TFT CS5/RST4/DC2/MOSI23/SCLK18/MISO19 and touch
32/33/14/27. These numeric assignments do not overlap the configured shared I2S
26/25, mic34, speaker22, distance16/17 or servo13/12. GPIO21 remains untouched.
Physical GPIO21 usage is unspecified and must be checked against real wiring.
GPIO12 servo strap guards remain unchanged and disabled by default. GPIO2 and
GPIO5 are also boot-strap-sensitive: physical startup wiring needs review.
GPIO4 is the TFT reset assignment, not a classic ESP32 strap pin.
Touch4 requires the previously specified physical move to GPIO27.

No controller, resolution or color format was confirmed. The existing display
module remains fail-closed; no TFT driver was enabled. No pins were reassigned,
firmware flashed, servo activated, .env edited, or Uvicorn restarted.

## Validation and remaining work

JavaScript syntax checked with node. Full Phase 2A automated interaction, parity,
host-C++ and firmware-build validation have not yet been completed. The previous
75-test Phase 1G result is historical, not a new Phase 2A regression result.

This is a partial prototype, not completed Phase 2A acceptance. Remaining:
connect a single-owner firmware animation task to display-state changes, add
deterministic engine/debounce/priority tests, browser playback-free visual tests,
run the full regression suite and firmware build, then identify TFT hardware
before implementing or physically validating a rendering backend.
