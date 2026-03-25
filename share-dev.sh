#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
LOG_DIR="$PROJECT_ROOT/.dev-logs"
CLOUDFLARED_DIR="$PROJECT_ROOT/.dev-tools"
CLOUDFLARED_BIN="$CLOUDFLARED_DIR/cloudflared"
APP_LOG="$LOG_DIR/share-dev-app.log"
TUNNEL_LOG="$LOG_DIR/share-dev-tunnel.log"
FRONTEND_URL="http://127.0.0.1:9488"
HEALTH_URL="http://127.0.0.1:9487/api/health"

mkdir -p "$LOG_DIR" "$CLOUDFLARED_DIR"

log() {
    printf '[share-dev] %s\n' "$1"
}

err() {
    printf '[share-dev] %s\n' "$1" >&2
}

wait_for_http() {
    local url="$1"
    local timeout_seconds="$2"
    local elapsed=0

    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    return 1
}

cleanup() {
    local exit_code=$?
    if [ -n "${TUNNEL_PID:-}" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
        kill "$TUNNEL_PID" 2>/dev/null || true
        wait "$TUNNEL_PID" 2>/dev/null || true
    fi
    if [ -n "${APP_PID:-}" ] && kill -0 "$APP_PID" 2>/dev/null; then
        kill "$APP_PID" 2>/dev/null || true
        wait "$APP_PID" 2>/dev/null || true
    fi
    exit "$exit_code"
}

trap cleanup EXIT INT TERM

ensure_cloudflared() {
    if [ -x "$CLOUDFLARED_BIN" ]; then
        return 0
    fi

    log "下載 cloudflared..."
    curl -L "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" -o "$CLOUDFLARED_BIN"
    chmod +x "$CLOUDFLARED_BIN"
}

extract_tunnel_url() {
    grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "$TUNNEL_LOG" | tail -n 1
}

wait_for_tunnel_url() {
    local timeout_seconds=30
    local elapsed=0

    while [ "$elapsed" -lt "$timeout_seconds" ]; do
        local url
        url="$(extract_tunnel_url || true)"
        if [ -n "$url" ]; then
            printf '%s\n' "$url"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    return 1
}

: > "$APP_LOG"
: > "$TUNNEL_LOG"

ensure_cloudflared

chmod +x "$PROJECT_ROOT/dev.sh"
log "啟動開發環境..."
"$PROJECT_ROOT/dev.sh" >"$APP_LOG" 2>&1 &
APP_PID=$!

log "等待前後端服務啟動..."
if ! wait_for_http "$HEALTH_URL" 45; then
    err "後端未能在預期時間內啟動，請查看 $APP_LOG"
    exit 1
fi

if ! wait_for_http "$FRONTEND_URL" 45; then
    err "前端未能在預期時間內啟動，請查看 $APP_LOG"
    exit 1
fi

log "開啟 Cloudflare Tunnel..."
"$CLOUDFLARED_BIN" tunnel --url "$FRONTEND_URL" >"$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

PUBLIC_URL="$(wait_for_tunnel_url)" || {
    err "Cloudflare Tunnel 建立失敗，請查看 $TUNNEL_LOG"
    exit 1
}

log "開發環境已對外分享"
printf '本機前端: %s\n' "$FRONTEND_URL"
printf '本機後端: http://127.0.0.1:9487\n'
printf '對外網址: %s\n' "$PUBLIC_URL"
printf '應用程式日誌: %s\n' "$APP_LOG"
printf 'Tunnel 日誌: %s\n' "$TUNNEL_LOG"
printf '按 Ctrl+C 可同時停止開發環境與 Tunnel\n'

wait "$APP_PID"
