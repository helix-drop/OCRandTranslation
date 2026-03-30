#!/bin/bash
# OCR Reader - managed launcher
# Closing the dedicated browser window also stops the app.

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
echo "  OCR Reader (managed window mode)"
echo "  Closing the dedicated browser window stops the app"
echo "========================================="
echo ""

"$VENV_DIR/bin/python" managed_launcher.py \
  --server-python "$VENV_DIR/bin/python" \
  --url "http://localhost:8080" \
  --cwd "$(pwd)"
