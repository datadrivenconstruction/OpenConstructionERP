#!/usr/bin/env bash
# Restore drill (data-loss guard) — proves a backup is actually restorable,
# WITHOUT touching the live database. Backs up the live DB, restores the dump
# into a throwaway scratch DB, compares a key table's row count, then drops the
# scratch DB. A backup you never restore is a backup you don't have.
#
# Usage:  scripts/restore-drill.sh
# Exit 0 only if the scratch restore's row count matches the live DB.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

[ -f .env ] && set -a && . ./.env && set +a
PG_USER="${POSTGRES_USER:-oe}"
PG_DB="${POSTGRES_DB:-openestimate}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.quickstart.yml -f docker-compose.acap-local.yml}"
SCRATCH="${PG_DB}_drill"
PROBE_TABLE="oe_acap_ahsp_coefficient"  # a seeded ACAP table with a stable count

psql() { docker compose $COMPOSE_FILES exec -T postgres psql -tA -U "$PG_USER" "$@"; }

echo "1/4 backing up live DB '$PG_DB'..."
DUMP="$(mktemp -t acap-drill-XXXX.sql.gz)"
docker compose $COMPOSE_FILES exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" | gzip > "$DUMP"

echo "2/4 (re)creating scratch DB '$SCRATCH'..."
psql -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\";" >/dev/null
psql -d postgres -c "CREATE DATABASE \"$SCRATCH\";" >/dev/null

echo "3/4 restoring dump into '$SCRATCH'..."
gunzip -c "$DUMP" | docker compose $COMPOSE_FILES exec -T postgres \
  psql -v ON_ERROR_STOP=0 -U "$PG_USER" -d "$SCRATCH" >/dev/null

LIVE_COUNT="$(psql -d "$PG_DB" -c "SELECT count(*) FROM $PROBE_TABLE;" | tr -d '[:space:]')"
DRILL_COUNT="$(psql -d "$SCRATCH" -c "SELECT count(*) FROM $PROBE_TABLE;" | tr -d '[:space:]')"

echo "4/4 verifying: $PROBE_TABLE  live=$LIVE_COUNT  restored=$DRILL_COUNT"
psql -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\";" >/dev/null
rm -f "$DUMP"

if [ "$LIVE_COUNT" = "$DRILL_COUNT" ] && [ "$LIVE_COUNT" -gt 0 ]; then
  echo "RESTORE DRILL PASSED — backup is restorable ($LIVE_COUNT rows round-tripped)."
else
  echo "RESTORE DRILL FAILED — live=$LIVE_COUNT restored=$DRILL_COUNT" >&2
  exit 1
fi
