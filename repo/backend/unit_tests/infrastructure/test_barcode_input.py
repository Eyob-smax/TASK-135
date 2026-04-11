"""
Unit tests for BarcodeInputHandler — scanner vs manual timing classification.
"""
from __future__ import annotations

from district_console.domain.enums import DeviceSource
from district_console.infrastructure.barcode_input import BarcodeInputHandler


def _scanner_feed(handler: BarcodeInputHandler, text: str, start_ms: int = 1000) -> str | None:
    """
    Feed characters at scanner speed (10 ms apart), including a final newline.
    Returns the result from the terminator character.
    """
    result = None
    t = start_ms
    for char in text:
        r = handler.process_char(char, t)
        if r is not None:
            result = r
        t += 10  # 10 ms — well within scanner threshold of 50 ms
    return result


def test_scanner_speed_completes_scan():
    handler = BarcodeInputHandler(min_scan_chars=4, max_manual_interval_ms=50)
    result = _scanner_feed(handler, "ABC123\n")
    assert result == "ABC123"


def test_scanner_speed_device_source_is_usb_scanner():
    handler = BarcodeInputHandler(min_scan_chars=4, max_manual_interval_ms=50)
    _scanner_feed(handler, "XYZ789\n")
    # After a completed scan, device_source reflects the last classification
    # (handler is reset after scan, so we check before reset by not processing terminator)
    handler2 = BarcodeInputHandler()
    t = 1000
    for char in "ITEM01":
        handler2.process_char(char, t)
        t += 10
    assert handler2.device_source() == DeviceSource.USB_SCANNER


def test_manual_speed_does_not_complete_scan():
    handler = BarcodeInputHandler(min_scan_chars=4, max_manual_interval_ms=50)
    # Feed characters at manual speed (200 ms apart)
    t = 1000
    result = None
    for char in "ABC\n":
        r = handler.process_char(char, t)
        if r is not None:
            result = r
        t += 200  # 200 ms — exceeds threshold, resets each time
    assert result is None


def test_scan_below_min_chars_does_not_complete():
    handler = BarcodeInputHandler(min_scan_chars=4, max_manual_interval_ms=50)
    # Only 3 chars — below min_scan_chars=4
    result = _scanner_feed(handler, "AB\n")
    assert result is None


def test_reset_clears_buffer():
    handler = BarcodeInputHandler(min_scan_chars=4, max_manual_interval_ms=50)
    # Feed some chars
    for char in "ABC":
        handler.process_char(char, 1000 + 10)
    handler.reset()
    assert handler._buffer == []
    assert handler._last_ts is None
    assert handler._is_scanner_mode is False
