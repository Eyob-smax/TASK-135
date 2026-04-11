"""
Unit tests for InstrumentationHooks — startup timing, memory sampling, scheduler ticks.
"""
from __future__ import annotations

import logging

from district_console.infrastructure.instrumentation import InstrumentationHooks


def test_record_startup_time_stores_stats():
    hooks = InstrumentationHooks()
    assert hooks.get_startup_stats() is None
    hooks.record_startup_time(1250)
    stats = hooks.get_startup_stats()
    assert stats is not None
    assert stats["elapsed_ms"] == 1250


def test_record_memory_sample_returns_keys():
    hooks = InstrumentationHooks()
    sample = hooks.record_memory_sample()
    assert "rss_mb" in sample
    assert "vms_mb" in sample
    assert "timestamp_ms" in sample
    assert isinstance(sample["timestamp_ms"], int)
    # rss_mb >= 0 (0 when psutil not installed)
    assert sample["rss_mb"] >= 0.0


def test_record_memory_sample_stored_for_retrieval():
    hooks = InstrumentationHooks()
    assert hooks.get_last_memory_sample() is None
    hooks.record_memory_sample()
    assert hooks.get_last_memory_sample() is not None


def test_record_scheduler_tick_emits_log(caplog):
    hooks = InstrumentationHooks()
    with caplog.at_level(logging.INFO, logger="district_console.infrastructure.instrumentation"):
        hooks.record_scheduler_tick("retry_events", 120, success=True)
    # The log message should contain scheduler context
    assert any("scheduler_tick" in r.message or "district_console.scheduler" in r.message
               for r in caplog.records)
