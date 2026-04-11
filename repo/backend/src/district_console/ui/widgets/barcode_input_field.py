"""
Barcode scanner-aware QLineEdit widget.

Wraps BarcodeInputHandler to classify keyboard input as USB_SCANNER or
MANUAL based on inter-keystroke timing. When a complete scan is detected,
emits the ``scan_completed`` signal with the scanned value and its
DeviceSource classification.

Usage::

    field = BarcodeInputField()
    field.scan_completed.connect(lambda value, source: ...)
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QWidget

from district_console.domain.enums import DeviceSource
from district_console.infrastructure.barcode_input import BarcodeInputHandler


class BarcodeInputField(QLineEdit):
    """
    QLineEdit subclass with keyboard-wedge scanner detection.

    Signals:
        scan_completed(value: str, source: DeviceSource)
            Emitted when a complete barcode scan is detected (scanner speed
            + terminator received). The field text is set to ``value`` and
            the field is cleared after the signal fires.
    """

    scan_completed = pyqtSignal(str, object)  # value, DeviceSource

    def __init__(
        self,
        min_scan_chars: int = 4,
        max_manual_interval_ms: int = 50,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._handler = BarcodeInputHandler(
            min_scan_chars=min_scan_chars,
            max_manual_interval_ms=max_manual_interval_ms,
        )
        self.setPlaceholderText("Scan barcode or type…")

    def keyPressEvent(self, event) -> None:
        key_text = event.text()
        now_ms = int(time.monotonic() * 1000)

        if key_text:
            result = self._handler.process_char(key_text, now_ms)
            if result is not None:
                # Complete scan detected
                source = self._handler.device_source()
                self._handler.reset()
                self.scan_completed.emit(result, source)
                # Set field text to scanned value for visual confirmation
                self.setText(result)
                return

        # Fall through to default handling for regular typing
        super().keyPressEvent(event)
