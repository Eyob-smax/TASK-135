"""
Keyboard-wedge barcode scanner input capture.

USB HID barcode scanners present as keyboard (HID) devices and inject
characters at machine speed — typically < 10 ms between keystrokes.
Manual typing is typically 100–300 ms between keystrokes.

This module provides BarcodeInputHandler: a character timing buffer that
distinguishes scanner input from manual typing based on inter-keystroke
interval. When a terminator character (newline, carriage return, or Tab)
is received and the buffer contains at least `min_scan_chars` characters
that arrived at scanner speed, the complete scanned value is returned.

Integration:
    Embed a BarcodeInputHandler in a QLineEdit subclass or connect it to
    the keyPressEvent of any input widget where scanner input is expected
    (location fields, item ID fields in relocations and count sessions).
    See ui/widgets/barcode_input_field.py for the PyQt6 integration.
"""
from __future__ import annotations

from typing import Optional

from district_console.domain.enums import DeviceSource


class BarcodeInputHandler:
    """
    Timing-based keyboard-wedge scanner capture helper.

    Characters arriving faster than ``max_manual_interval_ms`` are
    classified as scanner input.  When the terminator is received and the
    buffer holds at least ``min_scan_chars`` scanner-speed characters, the
    completed scan value is returned.

    Usage::

        handler = BarcodeInputHandler()
        import time
        for char in "ABC123\\n":
            ts_ms = int(time.monotonic() * 1000)
            result = handler.process_char(char, ts_ms)
            if result:
                print("Scanned:", result, "source:", handler.device_source())
    """

    _TERMINATORS: frozenset[str] = frozenset({"\n", "\r", "\t"})

    def __init__(
        self,
        min_scan_chars: int = 4,
        max_manual_interval_ms: int = 50,
    ) -> None:
        self._min_scan_chars = min_scan_chars
        self._max_manual_interval_ms = max_manual_interval_ms
        self._buffer: list[str] = []
        self._last_ts: Optional[int] = None
        self._is_scanner_mode: bool = False

    def process_char(self, char: str, now_ms: int) -> Optional[str]:
        """
        Feed a single character into the timing buffer.

        Returns:
            The complete scanned barcode string when a terminator is received
            and the buffer meets the minimum length + scanner-speed criteria.
            Returns ``None`` while still accumulating.
        """
        if char in self._TERMINATORS:
            if self._is_scanner_mode and len(self._buffer) >= self._min_scan_chars:
                value = "".join(self._buffer)
                self.reset()
                return value
            self.reset()
            return None

        if self._last_ts is not None:
            interval = now_ms - self._last_ts
            if interval <= self._max_manual_interval_ms:
                self._is_scanner_mode = True
            else:
                # Inter-key gap is too large — start fresh as manual input
                self.reset()
                self._is_scanner_mode = False

        self._buffer.append(char)
        self._last_ts = now_ms
        return None

    def device_source(self) -> DeviceSource:
        """Return the DeviceSource classification for the last completed scan."""
        return DeviceSource.USB_SCANNER if self._is_scanner_mode else DeviceSource.MANUAL

    def reset(self) -> None:
        """Clear the buffer and reset timing/mode state."""
        self._buffer = []
        self._last_ts = None
        self._is_scanner_mode = False
