#!/usr/bin/env bash
# Bring down the full ACAP stack (data kept), then quit Docker Desktop.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! docker info >/dev/null 2>&1; then
  echo "Docker not running — nothing to stop."
  exit 0
fi

echo "Stopping services..."
docker compose -p ai-civil-architecture \
  -f docker-compose.quickstart.yml \
  -f docker-compose.acap-local.yml \
  -f docker-compose.acap-deploy.yml down

echo "Quitting Docker Desktop..."
osascript -e 'quit app "Docker"' 2>/dev/null || true
