"""Bounded MP3 framing checks used before exposing provider streams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


_BITRATES_MPEG1 = {
    3: (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0),
    2: (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0),
    1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
}
_BITRATES_MPEG2 = {
    3: (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    1: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_SAMPLE_RATES = {
    3: (44_100, 48_000, 32_000),
    2: (22_050, 24_000, 16_000),
    0: (11_025, 12_000, 8_000),
}
MAX_MP3_PROBE_BYTES = 512 * 1024


def _frame_header(data: bytes, offset: int) -> tuple[int, int, int, int] | None:
    if offset < 0 or offset + 4 > len(data):
        return None
    header = int.from_bytes(data[offset : offset + 4], "big")
    if (header >> 21) & 0x7FF != 0x7FF:
        return None
    version = (header >> 19) & 0b11
    layer = (header >> 17) & 0b11
    bitrate_index = (header >> 12) & 0b1111
    sample_index = (header >> 10) & 0b11
    padding = (header >> 9) & 1
    if version == 1 or layer == 0 or bitrate_index in {0, 15} or sample_index == 3:
        return None
    bitrates = _BITRATES_MPEG1 if version == 3 else _BITRATES_MPEG2
    bitrate = bitrates[layer][bitrate_index] * 1000
    sample_rate = _SAMPLE_RATES[version][sample_index]
    if layer == 3:
        frame_bytes = (12 * bitrate // sample_rate + padding) * 4
    elif layer == 1 and version != 3:
        frame_bytes = 72 * bitrate // sample_rate + padding
    else:
        frame_bytes = 144 * bitrate // sample_rate + padding
    if frame_bytes < 24:
        return None
    return frame_bytes, version, layer, sample_rate


def has_complete_mp3_frames(data: bytes, *, minimum_frames: int = 2) -> bool:
    """Return true for consecutive, complete MPEG audio frames (ID3v2 allowed).

    This validates framing only; it does not claim that a browser/decoder has
    successfully decoded or played the stream.
    """
    if minimum_frames < 1:
        raise ValueError("minimum_frames must be positive")
    scan_start = 0
    if data.startswith(b"ID3"):
        if len(data) < 10:
            return False
        size_bytes = data[6:10]
        if any(byte & 0x80 for byte in size_bytes):
            return False
        tag_size = (
            (size_bytes[0] << 21)
            | (size_bytes[1] << 14)
            | (size_bytes[2] << 7)
            | size_bytes[3]
        )
        has_footer = bool(data[5] & 0x10)
        scan_start = 10 + tag_size + (10 if has_footer else 0)
        if scan_start > len(data):
            return False

    offset = scan_start
    while offset + 4 <= len(data):
        first = _frame_header(data, offset)
        if first is None:
            offset += 1
            continue
        first_size, first_version, first_layer, first_rate = first
        next_offset = offset + first_size
        if next_offset + 4 > len(data):
            offset += 1
            continue
        frame_count = 1
        while frame_count < minimum_frames:
            next_header = _frame_header(data, next_offset)
            if next_header is None:
                break
            next_size, next_version, next_layer, next_rate = next_header
            if (next_version, next_layer, next_rate) != (
                first_version,
                first_layer,
                first_rate,
            ) or next_offset + next_size > len(data):
                break
            frame_count += 1
            next_offset += next_size
        if frame_count >= minimum_frames:
            return True
        offset += 1
    return False


async def first_valid_mp3_prefix(
    chunks: AsyncIterator[bytes], *, max_probe_bytes: int = MAX_MP3_PROBE_BYTES
) -> bytes:
    """Buffer only the bounded prefix needed to see two complete MP3 frames."""
    prefix = bytearray()
    next_probe_bytes = 0
    last_scanned_size = 0
    async for chunk in chunks:
        if not chunk:
            continue
        prefix.extend(chunk)
        if len(prefix) > max_probe_bytes:
            raise RuntimeError("TTS stream did not yield a valid MP3 prefix in time")
        # Probe every small network increment so ordinary MP3 streams start as
        # soon as two frames are available. For a malformed/large prefix, use
        # geometric checkpoints to avoid quadratic rescans. The scan itself is
        # CPU work, so keep it off the event loop.
        if len(prefix) <= 2 * 1024 or len(prefix) >= next_probe_bytes:
            candidate = bytes(prefix)
            if len(candidate) <= 2 * 1024:
                valid = has_complete_mp3_frames(candidate, minimum_frames=2)
            else:
                valid = await asyncio.to_thread(
                    has_complete_mp3_frames, candidate, minimum_frames=2
                )
            last_scanned_size = len(candidate)
            next_probe_bytes = (
                len(candidate) + 4 * 1024
                if len(candidate) < 16 * 1024
                else len(candidate) * 2
            )
            if valid:
                return candidate
    if len(prefix) > last_scanned_size:
        candidate = bytes(prefix)
        valid = await asyncio.to_thread(
            has_complete_mp3_frames, candidate, minimum_frames=2
        )
        if valid:
            return candidate
    raise RuntimeError("TTS stream ended before two complete MP3 frames arrived")
