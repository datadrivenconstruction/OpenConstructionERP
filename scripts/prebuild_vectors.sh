#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

echo "==> Ensuring Qdrant service is running"
sudo systemctl start openconstructionerp-qdrant.service

echo "==> Running vector prebuild/backfill pass"
export PYTHONPATH="$BACKEND_DIR${PYTHONPATH:+:$PYTHONPATH}"
export OE_COST_VECTOR_FORCE_BACKFILL=1
cd "$BACKEND_DIR"

/usr/bin/python - <<'PY'
import asyncio

from app.main import _auto_backfill_vector_collections, _init_vector_db

_init_vector_db()
asyncio.run(_auto_backfill_vector_collections())
PY

echo "==> Current public status"
for attempt in $(seq 1 20); do
	if curl --fail --silent --show-error http://127.0.0.1:8081/api/system/status; then
		echo
		break
	fi
	if [[ "$attempt" -eq 20 ]]; then
		echo "Local API did not become ready in time" >&2
		exit 1
	fi
	sleep 1
done

echo "Vector prebuild pass complete"