#!/usr/bin/env bash
# Start TestLab locally for development and testing (Django development server).
# Developer convenience only — not for production deployment.
#
# Uses the existing virtual environment in <repo>/.venv; installs nothing.
# Applies pending migrations to the configured development database (never
# deletes or recreates it), then serves on http://127.0.0.1:8000/.
set -euo pipefail

# Repository root = parent of this script's directory, wherever it is launched from.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$REPO_DIR/.venv"
URL="http://127.0.0.1:8000/"

setup_help() {
    cat >&2 <<EOF

Create the development environment once, in $REPO_DIR:

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"
    .venv/bin/python app/manage.py createsuperuser

(Requires Python 3.12+. See README.md, "Development setup".)
EOF
}

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "TestLab: no Python virtual environment found at $VENV_DIR" >&2
    setup_help
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! python -c "import django, dj_database_url, docxtpl" >/dev/null 2>&1; then
    echo "TestLab: the virtual environment at $VENV_DIR is missing required packages." >&2
    setup_help
    exit 1
fi

cd "$REPO_DIR/app"

echo "TestLab: applying pending database migrations (if any)..."
python manage.py migrate --noinput

echo
echo "  TestLab is starting at:  $URL"
echo "  (stop the server with Ctrl+C)"
echo
exec python manage.py runserver 127.0.0.1:8000
