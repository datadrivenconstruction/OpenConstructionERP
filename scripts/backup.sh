#!/usr/bin/env bash
# Nightly pg_dump of the OpenEstimate/ACAP database from the running Docker
# stack. Writes a gzipped plain-SQL dump and rotates to the newest 14.
#
# Usage:  scripts/backup.sh [backup_dir]        (default: ./backups)
# Cron:   0 2 * * *  cd /path/to/repo && scripts/backup.sh >> /var/log/acap-backup.log 2>&1
#
# Reads POSTGRES_USER / POSTGRES_DB from the environment (or .env), defaulting
# to the stack's oe / openestimate. Compose file set is overridable via
# $COMPOSE_FILES for a prod stack (docker-compose.prod.yml).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BACKUP_DIR="${1:-$REPO_ROOT/backups}"
mkdir -p "$BACKUP_DIR"

# Load .env if present (for POSTGRES_USER / POSTGRES_DB), without leaking values.
[ -f .env ] && set -a && . ./.env && set +a

PG_USER="${POSTGRES_USER:-oe}"
PG_DB="${POSTGRES_DB:-openestimate}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.quickstart.yml -f docker-compose.acap-local.yml}"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/${PG_DB}-${STAMP}.sql.gz"

# -T: no TTY (cron-safe). Stream straight through gzip — never touches disk uncompressed.
docker compose $COMPOSE_FILES exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" | gzip > "$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"
echo "backup OK: $OUT ($SIZE)"

# Retention: keep the newest 14 dumps.
ls -1t "$BACKUP_DIR/${PG_DB}"-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
