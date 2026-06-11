#!/bin/sh
# Entrypoint for the unified OpenConstructionERP image.
#
# The backend is PostgreSQL-only (SQLite support was removed in v6.6.0)
# and this image does not bundle a database server, so DATABASE_URL is
# required. Validate it up front and fail with one readable message
# instead of a Python traceback in a restart loop (the old image baked a
# sqlite+aiosqlite default that the backend hard-rejects, which made a
# bare `docker run` crash-loop).
set -eu

# Operability escape hatch: `docker run <image> sh` (or any explicit
# command) bypasses the server startup entirely.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

case "${DATABASE_URL:-}" in
  postgres://* | postgresql://* | postgresql+*)
    # Any postgres-family URL is accepted; the app normalizes the driver.
    ;;
  "")
    echo "ERROR: DATABASE_URL is not set." >&2
    echo "" >&2
    echo "OpenConstructionERP needs a PostgreSQL server. Either:" >&2
    echo "  - run the full stack from the repo root:" >&2
    echo "      docker compose -f docker-compose.quickstart.yml up" >&2
    echo "  - or point this container at your own PostgreSQL:" >&2
    echo "      docker run -e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname ..." >&2
    exit 1
    ;;
  *)
    # Do not echo the full URL - it may carry credentials.
    echo "ERROR: DATABASE_URL must be a PostgreSQL URL (got scheme '${DATABASE_URL%%:*}')." >&2
    echo "PostgreSQL is the only supported database since v6.6.0." >&2
    exit 1
    ;;
esac

exec python -m uvicorn app.main:create_app \
  --factory --host 0.0.0.0 --port 8080 \
  --app-dir /app/backend
