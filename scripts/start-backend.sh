#!/usr/bin/env bash
set -euo pipefail

cd /home/steven/animal-welfare-verifier/backend
exec /home/steven/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
