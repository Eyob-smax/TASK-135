"""
CLI entry point for the ``district-console`` command defined in pyproject.toml.

Delegates to ``ui.app.run_application()`` which owns the full Qt lifecycle.
"""
from __future__ import annotations

import sys


def main() -> None:
    from district_console.ui.app import run_application
    sys.exit(run_application())


if __name__ == "__main__":
    main()
