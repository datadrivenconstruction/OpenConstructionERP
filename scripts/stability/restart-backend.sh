#!/usr/bin/env bash
# Restart the backend that the stability workflow launched, by PID file only.
#
# Used as BACKEND_RESTART_CMD by the e2e-stability job: a spec calls it to prove
# a signed-in session survives a server restart. It stops exactly the process
# recorded in the PID file (never by image name), starts a new one with the same
# command line and data dir, rewrites the PID file and waits for /api/health.
#
# Env (all set by the workflow):
#   OE_PID_FILE   file holding the backend PID
#   OE_DATA_DIR   data dir passed to `serve` (embedded PostgreSQL lives here)
#   OE_LOG_FILE   log file, appended to
#   OE_PORT       port, default 8000
#   OE_BACKEND_DIR  directory to start from, default backend
set -euo pipefail

: "${OE_PID_FILE:?OE_PID_FILE is required}"
: "${OE_DATA_DIR:?OE_DATA_DIR is required}"
LOG="${OE_LOG_FILE:-/dev/null}"
PORT="${OE_PORT:-8000}"
DIR="${OE_BACKEND_DIR:-backend}"

if [ -f "$OE_PID_FILE" ]; then
  pid="$(cat "$OE_PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "stopping backend pid $pid"
    kill -TERM "$pid" || true
    for _ in $(seq 1 30); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "pid $pid ignored SIGTERM for 30s, sending SIGKILL"
      kill -KILL "$pid" || true
    fi
  fi
fi

# The embedded PostgreSQL is a child of the old process; give it a moment to
# release the data dir and port before the new serve starts its own.
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/api/health" || true)
  [ "$code" = "000" ] && break
  sleep 1
done

cd "$DIR"
nohup python -m app.cli serve --port "$PORT" --data-dir "$OE_DATA_DIR" >> "$LOG" 2>&1 &
echo $! > "$OE_PID_FILE"
echo "backend relaunched (pid $(cat "$OE_PID_FILE"))"

for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/api/health" || true)
  if [ "$code" = "200" ]; then
    echo "backend healthy again after $((i * 2))s"
    exit 0
  fi
  sleep 2
done
echo "backend did not come back within 120s" >&2
tail -60 "$LOG" >&2 || true
exit 1
