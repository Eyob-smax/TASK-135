"""
QThread-based worker for running blocking API calls off the main thread.

Usage::

    worker = ApiWorker(client.login, "alice", "password123")
    worker.result.connect(on_success)
    worker.error.connect(on_error)
    worker.finished_clean.connect(lambda: btn.setEnabled(True))
    worker.start()

Workers are single-shot: create a new instance per operation.
Hold a reference to the worker on the owning widget (e.g. self._worker)
so Python's garbage collector does not delete the QThread while it runs.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal


class ApiWorker(QThread):
    """
    Runs a callable in a background QThread and emits result or error.

    Attributes
    ----------
    result : pyqtSignal(object)
        Emitted with the return value of the callable on success.
    error : pyqtSignal(Exception)
        Emitted with the exception on failure.
    finished_clean : pyqtSignal()
        Emitted after result or error, regardless of outcome.
        Use this to re-enable UI controls.
    """

    result: pyqtSignal = pyqtSignal(object)
    error: pyqtSignal = pyqtSignal(Exception)
    finished_clean: pyqtSignal = pyqtSignal()

    def __init__(self, fn: Callable[..., Any], *args: Any,
                 **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            value = self._fn(*self._args, **self._kwargs)
            self.result.emit(value)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(exc)
        finally:
            self.finished_clean.emit()
