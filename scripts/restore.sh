#!/usr/bin/env bash
# Restore a scripts/backup.sh dump into a Postgres database in the Docker stack.
#
# Usage:  scripts/restore.sh <backup.sql.gz> [target_db]
#   target_db defaults to POSTGRES_DB (openestimate) — the LIVE database.
#   Pass a scratch name (e.g. openestimate_drill) to restore WITHOUT touching
#   production; scripts/restore-drill.sh uses that to prove a backup is good.
#
# DESTRUCTIVE when target_db is the live DB: existing objects are overwritten.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DUMP="${1:?usage: restore.sh <backup.sql.gz> [target_db]}"
[ -f "$DUMP" ] || { echo "no such dump: $DUMP" >&2; exit 1; }

[ -f .env ] && set -a && . ./.env && set +a
PG_USER="${POSTGRES_USER:-oe}"
TARGET_DB="${2:-${POSTGRES_DB:-openestimate}}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.quickstart.yml -f docker-compose.acap-local.yml}"

echo "Restoring '$DUMP' -> database '$TARGET_DB' (existing objects overwritten)."

# Ensure the target DB exists (idempotent — ignore "already exists").
docker compose $COMPOSE_FILES exec -T postgres \
  psql -U "$PG_USER" -d postgres -c "CREATE DATABASE \"$TARGET_DB\";" 2>/dev/null || true

gunzip -c "$DUMP" | docker compose $COMPOSE_FILES exec -T postgres \
  psql -v ON_ERROR_STOP=0 -U "$PG_USER" -d "$TARGET_DB" >/dev/null

echo "restore complete -> $TARGET_DB"
