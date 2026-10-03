#!/usr/bin/env bash
#
# Start TestLab locally (Django development server). Not a production deployment.
#
#   ./scripts/run_app.sh                 http://127.0.0.1:8000/ (this machine only)
#   ./scripts/run_app.sh --lan           also reachable from the network
#   ./scripts/run_app.sh --port 8001
#
# Thin wrapper around scripts/devenv.py run, shared with Windows (run_app.bat).
# Works from any directory. Run ./scripts/setup.sh first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$REPO_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "TestLab: no virtual environment at $REPO_DIR/.venv - run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$PYTHON" "$REPO_DIR/scripts/devenv.py" run "$@"
