# Bella Phase 2C expression and playback protocol

Control/audio protocol remains version 1. These are additive messages; old device clients can keep their existing audio path but will not provide Phase 2C playback evidence. No conversation text is included in expression or playback diagnostics.

## Expression envelope

`ExpressionEvent` in `app/device/face.py` and the shared browser controller define:

```json
{"version":1,"event_id":"unique-id","device_id":null,"turn_id":"capture-or-turn-id","session_id":"publisher-or-connection-id","destination":"browser","source":"conversation","priority":40,"sequence":1,"expression":"listening","duration_ms":60000,"intensity":1}
```

Expressions: idle, happy, love, excited, curious, surprised, sad, angry, sleepy, wink, listening, thinking, speaking, offline, error. Destinations are browser, device or simulation; browser events do not assert device playback. Sources/priorities: preview/touch 10, conversation 40, playback 60, connectivity 80, error 90. Browser priorities are derived from known sources rather than trusting a sender-supplied priority. Expiration uses receiver-local monotonic time, not subtraction of unsynchronized clocks. Idle clears that source; offline remains until an explicit recovery event. Other states expire. Sequence maps and retired-turn history are bounded to 64 entries.

Browser-to-Face-Studio adapter uses same-origin `BroadcastChannel('bella-expression-v1')`, not another voice endpoint. Open both pages under the **same origin and browser profile** (localhost and 127.0.0.1 are different origins). It carries only expression metadata, never transcript/audio/tokens. Listening/thinking adopts a new turn; retired turns and duplicate source sequences are rejected. Simulation uses its own instance of the same controller and does not broadcast synthetic playback as real activity.

Connected Device mode remains separately labeled and uses authenticated registry reports. Browser Voice mode follows the local browser output. Browser playback is deliberately **not** forwarded as an assertion of physical speaker activity. Safe face-only commands remain available for explicit device previews.

## Device commands and reports

`device_ready` now carries a random `connection_id`. Existing `face_command` additionally carries event_id, device_id, turn_id (null for preview), session_id (connection ID), sequence, source=preview, destination=device, intensity. Firmware rejects mismatched session IDs and non-increasing command sequences when present. Duration remains bounded to 250–5000 ms; local conversation state takes precedence over preview/touch effects. Legacy commands without the new metadata retain compatibility.

`face_ack` still means **accepted by the animation engine**, not drawn to TFT. Existing per-connection `face_report` sequences and touch IDs remain. Command acknowledgments are accepted only for the current command before its deadline. Queues use latest-event semantics and clear on disconnect. The status endpoint exposes command timeouts rather than silently treating a timeout as delivery.

## Playback evidence

```json
{"type":"playback_drained","version":1,"playback_version":1,"turn_id":7,"sequence":3,"basis":"dma_ring_fence","estimated":true}
```

| Event | Evidence / basis | Meaning |
| --- | --- | --- |
| `playback_started` | `i2s_write_accepted`, estimated=true | Device accepted a first successful PCM write into TX DMA; approximate start, not an exact first-sample/acoustic timestamp |
| `playback_drained` | `dma_ring_fence`, estimated=true | Queue reached final turn marker, then at least seven TX EOF callbacks occurred with unchanged cancellation generation; conservative bound, not exact last-sample/acoustic time |
| `playback_interrupted` | `cancelled` | Device invalidated the active generation and flushed playback; an already transmitted sample cannot be recalled |
| `playback_error` | `i2s_error` | Device write/drain/preload failed; no successful playback claim |

`simulated_dma` with estimated=true is allowed for explicit offline fake-device tests and is visibly labeled. Unknown events, mismatched evidence/event pairs, invalid IDs/sequences, or false exactness for estimated bases are rejected. Backend accepts reports only for the authenticated device's current playback turn, increasing sequence, nonterminal state, and expected lifecycle. Drain requires server_audio_complete first. A requested cancellation rejects late starts/drains; old turns cannot complete a new turn. A 60-second acknowledgment deadline becomes `ack_timeout`, not success. Disconnect invalidates pending playback and commands.

## Audio ordering and cancellation

The backend sends chunk-start → ordered PCM frames → chunk-end. `frame_count` is checked by firmware against the expected PCM sequence. `turn_complete` means generation/transmission has ended and queues a **final turn marker** behind PCM; it does not set idle while speaker work remains. At that marker, the speaker task waits for the DMA fence, reports drain, then returns local state to idle. A turn with no queued speaker audio can return idle without fabricating a drain report.

Generation-tagged speaker frames are bounded to eight queue entries. Writes and cancellation reset use a TX mutex. Cancellation changes generation first, removes queued frames, disables TX, preloads silence over all six configured DMA descriptors, then re-enables TX only if the full preload succeeds. RX pin/clock assignments are unchanged. Auto-clear-after-callback prevents stale DMA contents repeating during underrun. A 350 ms fence timeout reports failure; no estimated wall-clock sleep is declared an exact drain.

Face/telemetry sending uses an eight-entry nonblocking control queue and a separate sender task. Connection epochs discard queued events from older connections. If network telemetry cannot enqueue, it can be dropped; local touch/animation must continue, and backend acknowledgment deadlines expose missing evidence. Critical physical behavior still requires serial and hardware acceptance.

## Driver evidence and limitations

Inspected installed PlatformIO ESP-IDF 6.0.1 `components/esp_driver_i2s/i2s_common.c` and `include/driver/i2s_common.h`: writes copy into DMA buffers; TX EOF invokes `on_sent`; auto-clear can zero a completed buffer. The [Espressif v6.0 I²S reference](https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32/api-reference/peripherals/i2s.html) documents the DMA callback interface. The ring-fence interpretation is implementation-specific and deliberately labeled a conservative estimate. It does not prove DAC/amplifier/speaker output, eliminate already transmitted samples on cancellation, or establish exact acoustic start/end latency.
