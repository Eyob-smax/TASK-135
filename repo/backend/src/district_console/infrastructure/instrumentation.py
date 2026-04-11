"""
Startup, memory, scheduler, and crash-recovery instrumentation hooks.

All measurements are emitted as structured log records at INFO level.
No external metrics store or network call is used — fully offline.

``psutil`` is used for memory sampling if available; if not installed,
memory samples return zeros without raising an error.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

_log = logging.getLogger(__name__)

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


class InstrumentationHooks:
    """
    Lightweight instrumentation for offline desktop runtime monitoring.

    Startup timing:
        Call ``record_startup_time(elapsed_ms)`` after the bootstrap
        sequence finishes to capture how long initialisation took.

    Memory sampling:
        Call ``record_memory_sample()`` periodically (e.g., from the
        APScheduler every 30 minutes) to track resident set size.

    Scheduler ticks:
        Call ``record_scheduler_tick(job_id, elapsed_ms, success)``
        in the APScheduler job wrapper to log each job execution result.

    Recovery events:
        Call ``record_recovery_event(job_type, job_id, outcome)`` after
        each checkpoint resume attempt at startup.
    """

    def __init__(self) -> None:
        self._startup_stats: Optional[dict] = None
        self._last_memory: Optional[dict] = None

    # ------------------------------------------------------------------
    # Startup timing
    # ------------------------------------------------------------------

    def record_startup_time(self, elapsed_ms: int) -> None:
        """Record application startup duration in milliseconds."""
        self._startup_stats = {"elapsed_ms": elapsed_ms}
        _log.info(
            "district_console.startup",
            extra={"event": "startup_complete", "elapsed_ms": elapsed_ms},
        )

    def get_startup_stats(self) -> Optional[dict]:
        """Return the most recent startup stats dict, or None if not yet recorded."""
        return self._startup_stats

    # ------------------------------------------------------------------
    # Memory sampling
    # ------------------------------------------------------------------

    def record_memory_sample(self) -> dict:
        """
        Sample current process memory and return the stats dict.

        Returns a dict with keys ``rss_mb``, ``vms_mb``, ``timestamp_ms``.
        If psutil is not installed, rss_mb and vms_mb are 0.0.
        """
        if _HAS_PSUTIL:
            proc = _psutil.Process()
            mem = proc.memory_info()
            sample = {
                "rss_mb": round(mem.rss / (1024 * 1024), 2),
                "vms_mb": round(mem.vms / (1024 * 1024), 2),
                "timestamp_ms": int(time.monotonic() * 1000),
            }
        else:
            sample = {
                "rss_mb": 0.0,
                "vms_mb": 0.0,
                "timestamp_ms": int(time.monotonic() * 1000),
            }
        self._last_memory = sample
        _log.info(
            "district_console.memory",
            extra={"event": "memory_sample", **sample},
        )
        return sample

    def get_last_memory_sample(self) -> Optional[dict]:
        """Return the most recent memory sample, or None if none taken yet."""
        return self._last_memory

    # ------------------------------------------------------------------
    # Scheduler ticks
    # ------------------------------------------------------------------

    def record_scheduler_tick(
        self, job_id: str, elapsed_ms: int, success: bool
    ) -> None:
        """Record one APScheduler job execution result."""
        _log.info(
            "district_console.scheduler",
            extra={
                "event": "scheduler_tick",
                "job_id": job_id,
                "elapsed_ms": elapsed_ms,
                "success": success,
            },
        )

    # ------------------------------------------------------------------
    # Recovery events
    # ------------------------------------------------------------------

    def record_recovery_event(
        self, job_type: str, job_id: str, outcome: str
    ) -> None:
        """
        Record a checkpoint recovery attempt at startup.

        outcome values: "resumed", "expired", "abandoned", "skipped"
        """
        _log.info(
            "district_console.recovery",
            extra={
                "event": "checkpoint_recovery",
                "job_type": job_type,
                "job_id": job_id,
                "outcome": outcome,
            },
        )
