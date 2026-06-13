#!/usr/bin/env bash
# Production launcher — builds the frontend once, then runs uvicorn
# serving both the static bundle and the API from :8000.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"

cd "$REPO"

# ── Detect Python interpreter (Windows / macOS / Linux) ──
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    # Skip Windows Store shim (returns empty on --version)
    if "$cmd" --version >/dev/null 2>&1; then
      PYTHON="$cmd"
      break
    fi
  fi
done
if [ -z "$PYTHON" ]; then
  echo "[start-prod] Error: neither python3 nor python found in PATH." >&2
  exit 1
fi
echo "[start-prod] Using Python: $PYTHON ($($PYTHON --version))"

# ── Install backend deps ──
if ! "$PYTHON" -c "import fastapi" 2>/dev/null; then
  echo "[start-prod] Installing web-layer deps (web/backend/requirements.txt)…"
  if ! "$PYTHON" -m pip install -r web/backend/requirements.txt 2>/dev/null; then
    if [ "$(uname -s 2>/dev/null || true)" = "Linux" ]; then
      echo "[start-prod] Python is externally managed; retrying with --break-system-packages."
      "$PYTHON" -m pip install --break-system-packages -r web/backend/requirements.txt
    else
      "$PYTHON" -m pip install -r web/backend/requirements.txt
    fi
  fi
fi

# ── Install & build frontend ──
if [ ! -d "web/frontend/node_modules" ]; then
  echo "[start-prod] Installing frontend deps…"
  (cd web/frontend && npm install)
fi

echo "[start-prod] Building frontend…"
(cd web/frontend && npm run build)

echo "[start-prod] uvicorn → http://${HOST}:${PORT}"
exec "$PYTHON" -m uvicorn web.backend.app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
