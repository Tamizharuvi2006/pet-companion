import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from time import monotonic
import uuid


@dataclass(slots=True)
class DeviceRecord:
    device_id: str
    connected: bool = False
    firmware_version: str = "unknown"
    state: str = "DISCONNECTED"
    capabilities: dict[str, Any] = field(default_factory=dict)
    sensors: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: str | None = None
    last_error: str | None = None
    face_expression: str = 'idle'
    display_captions_enabled: bool = True
    display_captions_persisted: bool | None = None
    face_sequence: int = -1
    last_touch: int | None = None
    command_status: str | None = None
    command_id: str | None = None
    playback_turn: int | None = None
    playback_sequence: int = -1
    playback_status: str = 'not_reported'
    playback_basis: str | None = None
    playback_estimated: bool = True
    server_audio_complete: bool = False
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    command_sequence: int = 0


class DeviceRegistry:
    """Process-local device presence and reported health."""

    def __init__(self) -> None:
        self._records: dict[str, DeviceRecord] = {}
        self._lock = asyncio.Lock()
        self._commands: dict[str, dict[str, Any]] = {}
        self._command_deadlines: dict[str, float] = {}
        self._playback_deadlines: dict[str, float] = {}

    async def connected(
        self,
        device_id: str,
        firmware_version: str,
        capabilities: dict[str, Any],
        sensors: dict[str, Any],
    ) -> bool:
        async with self._lock:
            existing = self._records.get(device_id)
            if existing is not None and existing.connected:
                return False
            self._records[device_id] = DeviceRecord(
                device_id=device_id,
                connected=True,
                firmware_version=firmware_version,
                state="IDLE",
                capabilities=dict(capabilities),
                sensors=dict(sensors),
                last_heartbeat=_now(),
                display_captions_enabled=bool(capabilities.get('display_captions_enabled', True)),
                display_captions_persisted=capabilities.get('display_captions_persisted'),
            )
            return True

    async def heartbeat(
        self,
        device_id: str,
        *,
        state: str | None = None,
        sensors: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is None:
                return
            record.last_heartbeat = _now()
            if state is not None:
                record.state = state
            if sensors is not None:
                record.sensors = dict(sensors)

    async def failed(self, device_id: str, error: str) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                record.last_error = error[:160]

    async def camera_snapshot(self, device_id: str, size_bytes: int) -> None:
        async with self._lock:
            record = self._records.setdefault(device_id, DeviceRecord(device_id=device_id))
            record.last_heartbeat = _now()
            record.sensors["camera_available"] = True
            record.sensors["camera_last_snapshot_bytes"] = size_bytes

    async def disconnected(self, device_id: str) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                record.connected = False
                record.state = "DISCONNECTED"
                record.last_heartbeat = _now()
                record.face_expression = 'offline'
                if record.playback_status not in {'drained', 'error', 'not_reported'}:
                    record.playback_status = 'disconnected'
                self._commands.pop(device_id, None)
                if record.command_status == 'pending':
                    record.command_status = 'disconnected'

    async def command(self, device_id: str, expression: str, duration_ms: int) -> str | None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is None or not record.connected or not record.capabilities.get('face_protocol_v1'):
                return None
            command_id = uuid.uuid4().hex
            record.command_sequence += 1
            # Latest-event semantics: one waiting command per connected device.
            self._commands[device_id] = {'type': 'face_command', 'version': 1,
                'face_version': 1, 'command_id': command_id, 'expression': expression,
                'duration_ms': duration_ms, 'priority': 10, 'return_to_idle': True,
                'event_id': command_id, 'device_id': device_id, 'turn_id': None,
                'session_id': record.connection_id, 'sequence': record.command_sequence,
                'source': 'preview', 'destination': 'device', 'intensity': 1,
                'expires': monotonic()+15}
            record.command_status = 'pending'
            record.command_id = command_id
            self._command_deadlines[device_id] = monotonic()+15
            return command_id

    async def take_command(self, device_id: str) -> dict[str, Any] | None:
        async with self._lock:
            command = self._commands.pop(device_id, None)
            if command is None:
                return None
            expires = command.pop('expires')
            if monotonic() > expires:
                self._records[device_id].command_status = 'expired'
                return None
            return command

    async def acknowledge(self, device_id: str, command_id: str) -> None:
        async with self._lock:
            record = self._records[device_id]
            if record.command_id == command_id and record.command_status == 'pending' and monotonic() <= self._command_deadlines.get(device_id,0):
                record.command_status = 'accepted_by_engine'

    async def face_report(self, device_id: str, expression: str, sequence: int, touch_pad: int | None) -> None:
        async with self._lock:
            record = self._records[device_id]
            if sequence <= record.face_sequence:
                return
            record.face_sequence = sequence
            record.face_expression = expression
            if touch_pad is not None:
                record.last_touch = touch_pad

    async def set_display_captions(
        self, device_id: str, enabled: bool, persisted: bool | None = None
    ) -> None:
        async with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                record.display_captions_enabled = enabled
                record.capabilities['display_captions_enabled'] = enabled
                if persisted is not None:
                    record.display_captions_persisted = persisted
                    record.capabilities['display_captions_persisted'] = persisted

    async def snapshot(self, device_id: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            for key,deadline in list(self._playback_deadlines.items()):
                if monotonic()>deadline:
                    record=self._records.get(key)
                    if record and record.playback_status not in {'drained','interrupted','error','disconnected'}:
                        record.playback_status='ack_timeout'
                    self._playback_deadlines.pop(key,None)
            for key, deadline in list(self._command_deadlines.items()):
                if monotonic() > deadline:
                    record = self._records.get(key)
                    if record and record.command_status == 'pending':
                        record.command_status = 'ack_timeout'
                    self._command_deadlines.pop(key, None)
                    self._commands.pop(key, None)
            records = [self._records[device_id]] if device_id in self._records else [] if device_id else list(self._records.values())
            return [asdict(record) for record in records]

    async def begin_playback(self, device_id: str, turn_id: int) -> None:
        async with self._lock:
            record = self._records[device_id]
            record.playback_turn = turn_id
            record.playback_sequence = -1
            record.playback_status = 'awaiting_audio'
            record.server_audio_complete = False
            record.playback_basis = None
            self._playback_deadlines[device_id]=monotonic()+60

    async def audio_sent(self, device_id: str, turn_id: int) -> None:
        async with self._lock:
            record = self._records[device_id]
            if record.playback_turn == turn_id:
                record.server_audio_complete = True
                if record.playback_status == 'awaiting_audio':
                    record.playback_status = 'server_sent'

    async def cancel_playback(self, device_id: str) -> None:
        async with self._lock:
            self._records[device_id].playback_status = 'cancel_requested'

    async def playback_report(self, device_id: str, report: Any) -> bool:
        async with self._lock:
            record = self._records[device_id]
            if report.turn_id != record.playback_turn or report.sequence <= record.playback_sequence:
                return False
            if record.playback_status in {'drained', 'interrupted', 'error', 'disconnected', 'ack_timeout'}:
                return False
            if record.playback_status == 'cancel_requested' and report.event != 'playback_interrupted':
                return False
            if report.event == 'playback_drained' and not record.server_audio_complete:
                return False
            record.playback_sequence = report.sequence
            record.playback_status = report.event.removeprefix('playback_')
            record.playback_basis = report.basis
            record.playback_estimated = report.estimated
            if report.event == 'playback_started':
                record.state = 'SPEAKING'
            elif report.event in {'playback_drained','playback_interrupted'}:
                record.state = 'IDLE'
            if report.event == 'playback_error':
                record.last_error = 'device_playback_error'
            if record.playback_status in {'drained','interrupted','error'}:
                self._playback_deadlines.pop(device_id,None)
            return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
