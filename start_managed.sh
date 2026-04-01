#!/bin/bash
# OCR Reader launcher (normal browser mode)

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
echo "=================================="
echo "  OCR Reader (normal browser mode)"
echo "=================================="
echo ""

APP_URL="http://localhost:8080"
"$VENV_DIR/bin/python" app.py &
SERVER_PID=$!

cleanup() {
    if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
        kill "$SERVER_PID" >/dev/null 2>&1
    fi
}
trap cleanup EXIT INT TERM

# Wait until the local server is ready, then open with default browser.
for _ in $(seq 1 60); do
    if curl -sSf "$APP_URL" >/dev/null 2>&1; then
        open "$APP_URL" >/dev/null 2>&1 || true
        break
    fi
    sleep 0.5
done

wait "$SERVER_PID"
