#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="animal-welfare-crawl4ai"
IMAGE_NAME="unclecode/crawl4ai:basic"
PORT="11235"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "crawl4ai is already running at http://127.0.0.1:${PORT}"
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  docker start "${CONTAINER_NAME}" >/dev/null
  echo "crawl4ai started at http://127.0.0.1:${PORT}"
  exit 0
fi

docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${PORT}:11235" \
  "${IMAGE_NAME}" >/dev/null

echo "crawl4ai started at http://127.0.0.1:${PORT}"
