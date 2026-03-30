#!/bin/bash
# OCR Reader - standard launcher
# Creates a virtualenv, installs deps, and starts the app.

cd "$(dirname "$0")"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "Virtual environment ready."
fi

source "$VENV_DIR/bin/activate"

MARKER="$VENV_DIR/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    echo "Installing dependencies..."
    pip install -q -r requirements.txt
    touch "$MARKER"
    echo "Dependencies ready."
fi

echo ""
echo "========================================="
echo "  OCR Reader"
echo "  Browser URL: http://localhost:8080"
echo "========================================="
echo ""

open_browser() {
    local url="$1"
    if command -v open >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1
    else
        echo "No browser opener detected. Open this URL manually: $url"
    fi
}

(sleep 1 && open_browser "http://localhost:8080") &

python3 app.py
