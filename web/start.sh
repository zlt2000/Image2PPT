#!/usr/bin/env bash
# Dev launcher — runs the FastAPI backend and the Vite dev server in
# parallel. Use this during development. For production, run
# start-prod.sh instead (builds the frontend, lets uvicorn serve it).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

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
  echo "[start] Error: neither python3 nor python found in PATH." >&2
  exit 1
fi
echo "[start] Using Python: $PYTHON ($($PYTHON --version))"

# ── Install backend deps ──
if ! "$PYTHON" -c "import fastapi" 2>/dev/null; then
  echo "[start] Installing web-layer deps (web/backend/requirements.txt)…"
  # Normal install first; on Linux with PEP 668, fall back to --break-system-packages
  if ! "$PYTHON" -m pip install -r web/backend/requirements.txt 2>/dev/null; then
    if [ "$(uname -s 2>/dev/null || true)" = "Linux" ]; then
      echo "[start] Python is externally managed; retrying with --break-system-packages."
      "$PYTHON" -m pip install --break-system-packages -r web/backend/requirements.txt
    else
      "$PYTHON" -m pip install -r web/backend/requirements.txt
    fi
  fi
fi

# ── Install frontend deps ──
if [ ! -d "web/frontend/node_modules" ]; then
  echo "[start] Installing frontend deps…"
  (cd web/frontend && npm install)
fi

# ── Cleanup: track PIDs so we can kill them on Windows/Git Bash ──
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo "[start] stopping…"
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "$FRONTEND_PID" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ── Backend on :8000 ──
echo "[start] backend → http://localhost:8000"
(cd "$REPO" && "$PYTHON" -m uvicorn web.backend.app.main:app --host 0.0.0.0 --port 8000 --reload) &
BACKEND_PID=$!

# ── Frontend on :5173, proxies /api + /ws to :8000 ──
echo "[start] frontend → http://localhost:5173"
(cd "$REPO/web/frontend" && npm run dev -- --host) &
FRONTEND_PID=$!

wait
