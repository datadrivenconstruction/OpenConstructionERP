# Sourced by the temporary upgrade-test workflow. Needs $VENV, $DATA, $LOGS.
PROBE="$GITHUB_WORKSPACE/.github/upgrade-probe"

start_serve() {  # $1 = log label
  local log="$LOGS/serve-$1.log"
  ( cd "$RUNNER_TEMP" && nohup "$VENV/bin/openconstructionerp" serve --host 127.0.0.1 --port 8080 \
      --data-dir "$DATA" --demo </dev/null >"$log" 2>&1 & echo $! >"$RUNNER_TEMP/serve.pid" )
  echo "started serve pid $(cat "$RUNNER_TEMP/serve.pid") -> $log"
}

stop_serve() {
  local pid
  pid=$(cat "$RUNNER_TEMP/serve.pid" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" || true
    for _ in $(seq 1 60); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && { echo "serve did not exit on TERM, KILL"; kill -KILL "$pid" || true; }
  fi
  # The embedded postmaster outlives serve; stop it explicitly or the next boot
  # silently reuses the old cluster process.
  if [ -f "$DATA/pgdata/postmaster.pid" ]; then
    local pgctl
    pgctl=$("$VENV/bin/python" -c "from pixeltable_pgserver.utils import POSTGRES_BIN_PATH as p; print(p)")/pg_ctl
    "$pgctl" -D "$DATA/pgdata" -m fast -w -t 60 stop || true
  fi
  sleep 2
  if pgrep -fl "postgres.*$DATA" ; then echo "FAIL: postgres for $DATA still running"; return 1; fi
  echo "stopped cleanly"
}

embedded_db_state() {  # print alembic_version of every database in the embedded cluster
  local pidf="$DATA/pgdata/postmaster.pid" bin port sock
  [ -f "$pidf" ] || { echo "no running embedded cluster"; return 0; }
  port=$(sed -n 4p "$pidf"); sock=$(sed -n 5p "$pidf")
  bin=$("$VENV/bin/python" -c "from pixeltable_pgserver.utils import POSTGRES_BIN_PATH as p; print(p)")
  for db in $("$bin/psql" -h "$sock" -p "$port" -U postgres -d postgres -Atc "select datname from pg_database where not datistemplate"); do
    echo "db $db: alembic_version = $("$bin/psql" -h "$sock" -p "$port" -U postgres -d "$db" -Atc 'select string_agg(version_num, $$,$$) from alembic_version' 2>&1 | head -1)"
    echo "db $db: tables = $("$bin/psql" -h "$sock" -p "$port" -U postgres -d "$db" -Atc "select count(*) from information_schema.tables where table_schema='public'")"
  done
}

site_packages() { "$VENV/bin/python" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"; }

embedded_schema() {  # $1 = outdir; dump the schema of the app database in the running embedded cluster
  local pidf="$DATA/pgdata/postmaster.pid" bin port sock db
  port=$(sed -n 4p "$pidf"); sock=$(sed -n 5p "$pidf")
  bin=$("$VENV/bin/python" -c "from pixeltable_pgserver.utils import POSTGRES_BIN_PATH as p; print(p)")
  for d in $("$bin/psql" -h "$sock" -p "$port" -U postgres -d postgres -Atc "select datname from pg_database where not datistemplate"); do
    if [ "$("$bin/psql" -h "$sock" -p "$port" -U postgres -d "$d" -Atc "select to_regclass('public.oe_projects_project') is not null")" = t ]; then db=$d; fi
  done
  echo "embedded app database: ${db:-NOT FOUND}"
  PSQL="$bin/psql -h $sock -p $port -U postgres" bash "$PROBE/schema.sh" "$db" "$1"
}

compare_schema() {  # $1 = upgraded dir, $2 = fresh dir, $3 = label; fails on table/column/index/constraint gaps
  local rc=0 k a b only_up only_fresh
  for k in tables columns indexes constraints; do
    a="$1/$k.txt"; b="$2/$k.txt"
    only_up=$(comm -23 "$a" "$b" | wc -l | tr -d ' '); only_fresh=$(comm -13 "$a" "$b" | wc -l | tr -d ' ')
    echo "== $3 $k: only in upgraded=$only_up, only in fresh=$only_fresh"
    comm -3 "$a" "$b" | head -60
    [ "$only_fresh" -gt 0 ] && rc=1
    { [ "$k" = columns ] || [ "$k" = tables ]; } && [ "$only_up" -gt 0 ] && rc=1
  done
  return $rc
}
