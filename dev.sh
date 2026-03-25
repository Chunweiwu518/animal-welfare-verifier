#!/bin/bash
# 動保評價 — 本地開發環境啟動腳本
# - 前端 (Vite):    localhost:9488  [HMR hot-reload]
# - 後端 (FastAPI): localhost:9487  [uvicorn --reload]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python3"

LOG_DIR="$PROJECT_ROOT/.dev-logs"
mkdir -p "$LOG_DIR"

# ── 顏色 ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[dev]${NC} $1"; }
warn() { echo -e "${YELLOW}[dev]${NC} $1"; }
err()  { echo -e "${RED}[dev]${NC} $1"; }

# ── 清理殘留進程 ──
PIDS=()

kill_stale() {
    local pattern=$1
    local pids
    pids=$(lsof -ti:"$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        warn "清理殘留進程 (port $pattern): $pids"
        kill $pids 2>/dev/null || true
        sleep 1
        kill -9 $pids 2>/dev/null || true
    fi
}

log "=== 清理殘留進程 ==="
kill_stale 9487
kill_stale 9488

cleanup() {
    echo ""
    warn "正在停止所有服務..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    kill_stale 9487
    kill_stale 9488
    log "所有服務已停止 ✓"
    exit 0
}

trap cleanup SIGINT SIGTERM

# ── 檢查環境 ──
log "=== 檢查環境 ==="

if [ ! -f "$VENV_PYTHON" ]; then
    err "Python venv 不存在: $VENV_PYTHON"
    err "請先執行: cd backend && python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
fi
log "Python venv ✓"

if [ ! -f "$BACKEND_DIR/.env" ]; then
    warn ".env 不存在，後端將使用預設值"
else
    log ".env ✓"
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    warn "node_modules 不存在，安裝中..."
    (cd "$FRONTEND_DIR" && npm install)
fi
log "node_modules ✓"

# ── 確保上傳目錄存在 ──
mkdir -p "$BACKEND_DIR/data/media"

# ── 啟動後端 ──
log "=== 啟動 Backend (port 9487, --reload) ==="
(
    cd "$BACKEND_DIR"
    exec "$VENV_PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port 9487 --reload \
        > "$LOG_DIR/backend.log" 2>&1
) &
PIDS+=($!)
log "Backend PID: $!"

# ── 啟動前端 ──
log "=== 啟動 Frontend (port 9488, HMR) ==="
(
    cd "$FRONTEND_DIR"
    exec npx vite --host 0.0.0.0 --port 9488 \
        > "$LOG_DIR/frontend.log" 2>&1
) &
PIDS+=($!)
log "Frontend PID: $!"

# ── 等待啟動 ──
sleep 3

echo ""
echo "============================================"
log "🐾 動保評價 開發環境已啟動！"
echo "============================================"
echo ""
echo "  Frontend (HMR):     http://localhost:9488"
echo "  Backend  (reload):  http://localhost:9487"
echo "  API Docs:           http://localhost:9487/docs"
echo ""
echo "  Log 位置: $LOG_DIR/"
echo "    tail -f $LOG_DIR/backend.log"
echo "    tail -f $LOG_DIR/frontend.log"
echo ""
echo "  按 Ctrl+C 停止所有服務"
echo "============================================"

wait
