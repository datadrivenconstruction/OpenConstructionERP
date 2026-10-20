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

# The database can be given as a whole URL or as its parts. The parts exist
# because a URL assembled by string interpolation is wrong for any password
# containing "@": the user info splits at the first one, so "oe:pa@ss@postgres"
# is read as host "ss@postgres", which resolves nowhere. The container then
# dies naming a host nobody typed, while PostgreSQL stays healthy on the same
# password, because it gets it as a plain environment variable.
#
# Compose has no urlencode, so the parts are assembled and percent-encoded in
# app/config.py, where they are still separate and an encoder exists. That is
# also the only place that works for the backend-only image, which has no
# entrypoint script at all. Here we only have to stop insisting on a URL that
# is legitimately about to be built downstream.
db_from_parts=0
if [ -z "${DATABASE_URL:-}" ] && [ -n "${OE_DB_PASSWORD:-}" ]; then
  db_from_parts=1
fi

# Catch the same damage in a DATABASE_URL that was handed to us already
# composed. Exactly one "@" separates userinfo from host; a second one means
# an unencoded "@" in the password, and the host is not what the operator
# thinks it is. Better to say so than to let asyncpg report a DNS failure for
# a host nobody typed.
#
# The way to ask that without getting it wrong is to take the same parse the
# reader downstream takes, rather than to invent a second one. User info ends
# at the FIRST "@", the host runs from there to the next "/", and a host is not
# allowed to contain "@", so an "@" still sitting in it is the damage itself.
#
# This used to truncate at the first "/" and then count "@" over what was left,
# which reads like it isolates the authority and does not, because a password
# may contain "/" and a base64 one does about four times in ten. Given the
# password "pa/b@ss" the truncated text was "oe:pa", the count was zero, and the
# guard waved through the very URL it exists to catch, the one make_url reads
# with host "ss@postgres". Isolating the host instead of counting over a guess
# at the authority also drops the false positives that counting had: an "@" in
# a database name or in a query string is past the first "/" and no longer in
# the text being examined.
if [ -n "${DATABASE_URL:-}" ]; then
  _host="${DATABASE_URL#*://}"
  _host="${_host#*@}"
  _host="${_host%%/*}"
  case "$_host" in
    *@*)
    if [ -n "${OE_DB_PASSWORD:-}" ]; then
      # Recoverable: the parts are here as well, and app/config.py prefers them
      # over a URL whose host is visibly wrong. Say so and carry on rather than
      # refusing to start over a URL nobody has to use. A compose file that
      # passes both is doing it on purpose, so that one file works with an
      # image published before the parts existed.
      echo "NOTE: the host in DATABASE_URL contains an '@', which means the" >&2
      echo "password contains a literal one and the host is not the host you" >&2
      echo "typed. Using OE_DB_HOST and the other parts instead, where the" >&2
      echo "password is encoded properly." >&2
    else
      echo "ERROR: the host in DATABASE_URL contains an '@'." >&2
      echo "" >&2
      echo "The password almost certainly contains a literal '@'. In a URL that" >&2
      echo "splits the user info early, so the host is read as everything after" >&2
      echo "the first '@' and cannot be resolved." >&2
      echo "" >&2
      echo "Either percent-encode the '@' as %40, or let this container build" >&2
      echo "the URL for you by passing the parts instead:" >&2
      echo "      -e OE_DB_PASSWORD=... -e OE_DB_HOST=... (and no DATABASE_URL)" >&2
      exit 1
    fi
    ;;
  esac
  unset _host
fi

if [ "$db_from_parts" = 0 ]; then
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
      echo "  - or hand over the parts and let the app assemble them, which is" >&2
      echo "    the safe route for a password containing '@', ':' or '/':" >&2
      echo "      docker run -e OE_DB_HOST=... -e OE_DB_PASSWORD=... ..." >&2
      exit 1
      ;;
    *)
      # Do not echo the full URL - it may carry credentials.
      echo "ERROR: DATABASE_URL must be a PostgreSQL URL (got scheme '${DATABASE_URL%%:*}')." >&2
      echo "PostgreSQL is the only supported database since v6.6.0." >&2
      exit 1
      ;;
  esac
fi

# Pin the unified data-dir resolver (app.core.storage.resolve_data_dir) at
# the mounted /data volume. Without an explicit OE_DATA_DIR the resolver's
# wheel/site-packages branch defaults to ~/.openestimate INSIDE the
# container - the ephemeral container layer - so BIM geometry is written
# there, the DB row stays "ready", and a container recreate/redeploy makes
# the geometry endpoint 404. Idempotent and operator-overridable: this only
# fills in the default when OE_DATA_DIR was not already supplied.
export OE_DATA_DIR="${OE_DATA_DIR:-/data}"

exec python -m uvicorn app.main:create_app \
  --factory --host 0.0.0.0 --port 8080 --timeout-keep-alive 75 \
  --app-dir /app/backend
