#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
QDRANT_SERVICE_NAME="openconstructionerp-qdrant.service"
SERVICE_NAME="openconstructionerp.service"

echo "==> Building frontend"
cd "$FRONTEND_DIR"
npm run build

echo "==> Ensuring Qdrant service is running"
sudo systemctl start "$QDRANT_SERVICE_NAME"

echo "==> Restarting backend service"
sudo systemctl restart "$SERVICE_NAME"

echo "==> Validating and reloading nginx"
sudo nginx -t
sudo systemctl reload nginx

echo "==> Smoke checking public site"
curl --fail --silent --show-error https://construction.frappe.mn/api/system/status >/dev/null
curl --fail --silent --show-error https://construction.frappe.mn >/dev/null

echo "Deployment complete: https://construction.frappe.mn"