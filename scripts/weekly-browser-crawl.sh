#!/usr/bin/env bash
# Weekly background crawl using agent-browser.
# Called by systemd timer or cron.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

cd "$BACKEND_DIR"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Ensure npx (agent-browser) is on PATH
export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node/" 2>/dev/null | tail -1)/bin:$PATH"

echo "[$(date -Iseconds)] Starting weekly browser crawl..."
python -m scripts.weekly_browser_crawl "$@"
echo "[$(date -Iseconds)] Weekly browser crawl finished."
