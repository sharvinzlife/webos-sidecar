#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_URL="http://127.0.0.1:3847"
NODE_COMPAT_SHIM="$ROOT_DIR/scripts/node-compat.cjs"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "node is required."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required."
  exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(\".\")[0]')"
if [ "$NODE_MAJOR" -ge 25 ]; then
  echo "Node $NODE_MAJOR detected. webOS Sidecar will inject a compatibility shim for the LG CLI."
elif [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Node 20+ is recommended. The repo pins Node 22 in .nvmrc."
fi

CREATED_VENV=0
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  CREATED_VENV=1
fi

source .venv/bin/activate
if [ "$CREATED_VENV" -eq 1 ]; then
  python -m pip install --upgrade pip
fi
python -m pip install -r requirements.txt

if [ ! -x "node_modules/.bin/ares" ]; then
  npm install
fi

export NODE_OPTIONS="--require=$NODE_COMPAT_SHIM ${NODE_OPTIONS:-}"

mkdir -p runtime/artifacts runtime/unpacked

echo "Launching webOS Sidecar on $APP_URL"
python -m uvicorn app.main:app --host 127.0.0.1 --port 3847 --reload &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

READY=0
for _ in $(seq 1 40); do
  if curl -fsS "$APP_URL/api/status" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "$READY" -ne 1 ]; then
  echo "The dashboard did not become ready in time."
  exit 1
fi

if command -v open >/dev/null 2>&1; then
  open "$APP_URL" >/dev/null 2>&1 || true
fi

echo "Dashboard is ready. Browser opening at $APP_URL"
wait "$SERVER_PID"
