#!/usr/bin/env bash
# run_tests.sh — Docker-first test runner for District Console
#
# Usage:
#   ./run_tests.sh                     Run default backend suite (unit + API; excludes UI)
#   ./run_tests.sh unit                Run backend unit tests only (excludes UI)
#   ./run_tests.sh api                 Run only api_tests/
#   ./run_tests.sh ui                  Run only UI widget tests
#   ./run_tests.sh -k "test_auth"      Pass extra pytest args (forwarded to container)
#   ./run_tests.sh --cov               Enable coverage reporting (+90% gate)
#
# Tests MUST be run inside the Docker container (never directly on the host).
# The container provides the correct Python version, Qt display env, and all
# runtime dependencies. Coverage is measured against src/district_console only.
#
# Coverage is optional. Use --cov to enable coverage reporting and fail-under gate.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Keep compose output stable in scripted runs.
export COMPOSE_IGNORE_ORPHANS="${COMPOSE_IGNORE_ORPHANS:-True}"

# Resolve compose command across environments.
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo "ERROR: Docker Compose is not available. Install Docker Desktop / Compose plugin." >&2
    exit 127
fi

# Runtime test key is auto-provisioned when not provided by the caller.
if [[ -z "${DC_KEY_ENCRYPTION_KEY:-}" ]]; then
    export DC_KEY_ENCRYPTION_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    echo "==> DC_KEY_ENCRYPTION_KEY not set; using dockerized test default key."
fi

if [[ ! "${DC_KEY_ENCRYPTION_KEY}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "ERROR: DC_KEY_ENCRYPTION_KEY must be exactly 64 hex characters." >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Argument parsing — detect shorthand aliases before forwarding to pytest
# ---------------------------------------------------------------------------

PYTEST_ARGS=()
SUITE_FILTER=""
ENABLE_COV=true

for arg in "$@"; do
    case "$arg" in
        unit)
            SUITE_FILTER="unit"
            ;;
        api)
            SUITE_FILTER="api"
            ;;
        ui)
            SUITE_FILTER="ui"
            ;;
        --cov)
            ENABLE_COV=true
            ;;
        --no-cov)
            ENABLE_COV=false
            ;;
        *)
            PYTEST_ARGS+=("$arg")
            ;;
    esac
done

# Build testpaths and pytest options based on suite filter.
BACKEND_UNIT_PATHS=(
    "unit_tests/application/"
    "unit_tests/bootstrap/"
    "unit_tests/domain/"
    "unit_tests/infrastructure/"
    "unit_tests/test_package_imports.py"
)
UI_TEST_PATHS=("unit_tests/ui/")

TEST_PATHS=("${BACKEND_UNIT_PATHS[@]}" "api_tests/")
if [[ "$SUITE_FILTER" == "unit" ]]; then
    TEST_PATHS=("${BACKEND_UNIT_PATHS[@]}")
elif [[ "$SUITE_FILTER" == "api" ]]; then
    TEST_PATHS=("api_tests/")
elif [[ "$SUITE_FILTER" == "ui" ]]; then
    TEST_PATHS=("${UI_TEST_PATHS[@]}")
fi

PYTEST_CMD=(python -m pytest)
PYTEST_CMD+=("${TEST_PATHS[@]}")
if [[ "$ENABLE_COV" == true ]]; then
    PYTEST_CMD+=(--cov=district_console --cov-report=term-missing --cov-fail-under=90)
else
    PYTEST_CMD+=(--no-cov)
fi
PYTEST_CMD+=(-v)
PYTEST_CMD+=("${PYTEST_ARGS[@]}")

# ---------------------------------------------------------------------------
# Build and run
# ---------------------------------------------------------------------------

echo "==> Building test image..."
"${COMPOSE_CMD[@]}" build test

echo "==> Running test suite inside container..."
echo "    Command: ${PYTEST_CMD[*]}"

"${COMPOSE_CMD[@]}" run --rm test "${PYTEST_CMD[@]}"
