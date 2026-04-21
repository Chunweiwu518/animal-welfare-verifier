#!/usr/bin/env bash
# Monthly full-platform crawl: runs all 8 available pipelines across the watchlist.
# Invoked by systemd timer on the 1st of each month.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

cd "$BACKEND_DIR"

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

if [ -d "$HOME/.nvm/versions/node" ]; then
    export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node/" 2>/dev/null | tail -1)/bin:$PATH"
fi

echo "[$(date -Iseconds)] Starting monthly full crawl (all pipelines × watchlist)..."
python -m scripts.run_pipeline --pipeline all "$@"
echo "[$(date -Iseconds)] Monthly full crawl finished."
