#!/usr/bin/env bash
set -euo pipefail

cd /home/steven/animal-welfare-verifier/frontend

if [ ! -d dist ]; then
  npm run build
fi

exec npm run preview -- --host 0.0.0.0 --port 3010
