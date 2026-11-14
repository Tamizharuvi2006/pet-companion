from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PinUse:
    owner: str
    signal: str
    shared_bus: str | None = None


PIN_MAP: dict[int, tuple[PinUse, ...]] = {
    2: (PinUse("tft", "dc"),),
    4: (PinUse("tft", "reset"),),
    5: (PinUse("tft", "cs"),),
    12: (PinUse("servo2", "signal"),),
    13: (PinUse("servo1", "signal"),),
    14: (PinUse("touch3", "output"),),
    16: (PinUse("vl53l0x", "sda"),),
    17: (PinUse("vl53l0x", "scl"),),
    18: (PinUse("tft", "sck"),),
    19: (PinUse("tft", "miso"),),
    21: (PinUse("existing_hardware", "reserved"),),
    22: (PinUse("i2s", "speaker_din"),),
    23: (PinUse("tft", "mosi"),),
    25: (
        PinUse("i2s_mic", "ws", "i2s_full_duplex"),
        PinUse("i2s_speaker", "ws", "i2s_full_duplex"),
    ),
    26: (
        PinUse("i2s_mic", "bclk", "i2s_full_duplex"),
        PinUse("i2s_speaker", "bclk", "i2s_full_duplex"),
    ),
    27: (PinUse("touch4", "output"),),
    32: (PinUse("touch1", "output"),),
    33: (PinUse("touch2", "output"),),
    34: (PinUse("i2s", "microphone_din"),),
}

BOOT_STRAP_PINS = frozenset({2, 4, 5, 12, 15})
BOOT_STRAP_WARNINGS = {
    2: "GPIO2 is a boot strap; verify connected TFT circuitry does not interfere with boot or flashing",
    4: "GPIO4 is a boot strap; verify connected TFT circuitry does not interfere with boot or flashing",
    5: "GPIO5 is a boot strap; verify connected TFT circuitry does not interfere with boot or flashing",
    12: (
        "GPIO12/MTDI selects ESP32 VDD_SDIO flash voltage at reset; identify the exact board/flash and "
        "check external pulls before enabling Servo 2"
    ),
}


def validate_pin_map(pin_map: dict[int, tuple[PinUse, ...]] = PIN_MAP) -> list[str]:
    """Return conflicts; explicitly allow only the shared I2S clock wires."""
    errors: list[str] = []
    for pin, assignments in pin_map.items():
        if len(assignments) <= 1:
            continue
        buses = {assignment.shared_bus for assignment in assignments}
        signals = {assignment.signal for assignment in assignments}
        if (
            buses == {"i2s_full_duplex"}
            and len(signals) == 1
            and signals <= {"bclk", "ws"}
        ):
            continue
        owners = ", ".join(f"{entry.owner}.{entry.signal}" for entry in assignments)
        errors.append(f"GPIO{pin} is assigned more than once: {owners}")
    if 26 in pin_map and any(entry.owner.startswith("touch") for entry in pin_map[26]):
        errors.append("GPIO26 is an I2S bit clock and must not be a touch input")
    return errors
