from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from district_console.bootstrap.__main__ import main


def test_main_exits_with_run_application_status(monkeypatch):
    fake_app_module = SimpleNamespace(run_application=lambda: 7)
    monkeypatch.setitem(sys.modules, "district_console.ui.app", fake_app_module)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 7
