#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$BACKEND_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PORT="${PORT:-9487}"
HOST="${HOST:-0.0.0.0}"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

if [ ! -x "$UV_BIN" ]; then
  echo "找不到 uv：$UV_BIN" >&2
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "安裝前端依賴..."
  (cd "$FRONTEND_DIR" && npm install)
fi

echo "建置前端..."
(cd "$FRONTEND_DIR" && npm run build)

mkdir -p "$BACKEND_DIR/data/media"

echo "同步後端依賴..."
(cd "$BACKEND_DIR" && "$UV_BIN" sync --extra llm --extra scrapers)

echo "啟動公開服務：http://$HOST:$PORT"
cd "$BACKEND_DIR"
exec "$UV_BIN" run uvicorn app.main:app --host "$HOST" --port "$PORT"
