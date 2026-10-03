#!/usr/bin/env bash
#
# TestLab - development setup (Linux / macOS). Safe to run again.
#
#   ./scripts/setup.sh
#
# Thin wrapper: finds a Python 3.12+ and runs scripts/devenv.py setup, which
# holds the logic shared with Windows (setup.bat).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# An explicit interpreter wins: TESTLAB_PYTHON=/opt/python3.12/bin/python3 ./scripts/setup.sh
PYTHON="${TESTLAB_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    for candidate in python3.12 python3.13 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "TestLab: Python 3 was not found. Install Python 3.12 (e.g. apt install python3.12 python3.12-venv)." >&2
    exit 1
fi

# Debian/Ubuntu ship the venv module separately.
if ! "$PYTHON" -c "import venv, ensurepip" >/dev/null 2>&1; then
    echo "TestLab: $PYTHON cannot create virtual environments (the venv/ensurepip module is missing)." >&2
    echo "On Debian/Ubuntu install it with:  sudo apt install python3-venv  (or python3.12-venv)" >&2
    exit 1
fi

exec "$PYTHON" "$REPO_DIR/scripts/devenv.py" setup "$@"
