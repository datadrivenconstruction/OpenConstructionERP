#!/usr/bin/env bash
# Open Docker Desktop, wait for daemon, bring up the full ACAP stack.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

DC=(docker compose -p ai-civil-architecture \
  -f docker-compose.quickstart.yml \
  -f docker-compose.acap-local.yml \
  -f docker-compose.acap-deploy.yml)

if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker
  until docker info >/dev/null 2>&1; do sleep 2; done   # wait for daemon
fi

echo "Bringing up services..."
"${DC[@]}" up -d --build
"${DC[@]}" ps
