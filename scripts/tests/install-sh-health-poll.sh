#!/usr/bin/env bash
# Guards the health poll in scripts/install.sh.
#
# WHAT THIS PROVES, AND WHAT IT DOES NOT
# The subject is the real text of the wait loop and the verdict, sliced out of
# the shipped scripts/install.sh between two anchors and run under the same
# shell options the script sets. No Docker and no install: these cases prove
# which branch a person is shown for a given health answer, and nothing about
# whether an install works.
#
# WHY IT EXISTS
# The poll was added with `set -euo pipefail` already in force at the top of
# install.sh, and the assignment
#
#     health=$(curl -fsS ... | tr -d ' \n')
#
# takes the exit status of the substitution. curl failing is not an error here,
# it is the normal state of every iteration before the service serves, so the
# first unanswered request killed the installer at the exact spot that was
# added to make it safer. `bash -n` cannot see this: the syntax is fine, and
# the shape only misbehaves when it runs against something that is not up yet.
# So the first case below points the loop at a closed port and asserts that the
# verdict is reached at all. It fails against the unguarded assignment.
#
# HOW TO RUN
#   bash scripts/tests/install-sh-health-poll.sh
# Exit code 0 means every case passed. Needs curl and python3.

set -uo pipefail

src="$(cd "$(dirname "$0")/.." && pwd)/install.sh"
[ -f "$src" ] || { echo "cannot find $src"; exit 1; }

passed=0
failed=0

assert_contains() {
    local what="$1" haystack="$2" needle="$3"
    case "$haystack" in
        *"$needle"*) passed=$((passed + 1)); echo "  ok   $what" ;;
        *) failed=$((failed + 1)); echo "  FAIL $what"; echo "       wanted: $needle"; echo "       got: $haystack" ;;
    esac
}

assert_true() {
    local what="$1" got="$2"
    if [ "$got" = "yes" ]; then
        passed=$((passed + 1)); echo "  ok   $what"
    else
        failed=$((failed + 1)); echo "  FAIL $what"
    fi
}

# -- The subject, sliced from the shipped script ----------------------
# From the line that starts the wait to the esac that closes the verdict.
# The inner case of the loop closes at eight spaces, the verdict at four, so
# the first esac in the first column of the body is the end of the slice.
block=$(awk '/info "Waiting for health check\.\.\."/{on=1} on{print} on&&/^    esac$/{exit}' "$src")
case "$block" in
    *'Commands:'*) echo "the slice ran past the verdict, refusing to guess"; exit 1 ;;
    *'health_attempts'*'esac'*) : ;;
    *) echo "the anchors no longer bracket the poll, refusing to guess"; exit 1 ;;
esac

# Shrink the budget so the closed-port case does not spend a real minute. The
# shipped numbers are asserted separately below, against the file itself.
subject=$(printf '%s\n' "$block" | sed 's/^    health_attempts=30$/    health_attempts=2/; s/^    health_delay=2$/    health_delay=0/')

tmp=$(mktemp -d)
stub_pid=""
cleanup() {
    [ -n "$stub_pid" ] && kill "$stub_pid" 2>/dev/null
    rm -rf "$tmp"
}
trap cleanup EXIT

run_against() {
    # Runs the sliced block against a port, under the options install.sh sets.
    {
        echo 'set -euo pipefail'
        echo 'info() { echo "[i] $*"; }'
        echo 'ok() { echo "[ok] $*"; }'
        echo 'warn() { echo "[warn] $*"; }'
        echo "OE_PORT=$1"
        echo 'OE_INSTALL_DIR=/tmp/oe'
        printf '%s\n' "$subject"
    } > "$tmp/subject.sh"
    bash "$tmp/subject.sh" 2>&1
    echo "EXIT=$?"
}

start_stub() {
    # Serves $1 as the health body on a free port, written to $tmp/port.
    rm -f "$tmp/port"
    python3 - "$1" "$tmp/port" <<'PY' &
import http.server, socketserver, sys, threading

body = sys.argv[1].encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
with open(sys.argv[2], "w") as fh:
    fh.write(str(srv.server_address[1]))
threading.Timer(30, srv.shutdown).start()
srv.serve_forever()
PY
    stub_pid=$!
    for _ in $(seq 1 60); do
        [ -s "$tmp/port" ] && return 0
        sleep 0.1
    done
    return 1
}

stop_stub() {
    [ -n "$stub_pid" ] && kill "$stub_pid" 2>/dev/null
    [ -n "$stub_pid" ] && wait "$stub_pid" 2>/dev/null
    stub_pid=""
}

echo ""
echo "nothing is listening"
# The regression case. Under set -e the failing curl ends the script before the
# verdict, so the person is told nothing at all rather than told to read the
# logs, and an ordinary slow start exits the installer non-zero.
out=$(run_against 59999)
assert_contains "the verdict is still reached" "$out" "did not answer"
assert_contains "the loop does not abort the installer" "$out" "EXIT=0"
assert_contains "the wait is derived rather than written down" "$out" "within 0s"

while IFS='|' read -r name body want; do
    [ -n "$name" ] || continue
    echo ""
    echo "$name"
    if start_stub "$body"; then
        out=$(run_against "$(cat "$tmp/port")")
        assert_contains "is reported as expected" "$out" "$want"
        assert_contains "the installer exits cleanly" "$out" "EXIT=0"
    else
        failed=$((failed + 1)); echo "  FAIL the stub never reported a port"
    fi
    stop_stub
done <<'CASES'
a healthy install|{"status":"healthy","database":"ok"}|OpenConstructionERP is running
a degraded install whose database is reachable|{"status":"degraded","database":"ok"}|not every enabled module loaded
a degraded install that cannot reach its database|{"status":"degraded","database":"error"}|cannot reach its database
CASES

echo ""
echo "an answer this script does not recognise"
# Reassuring somebody about a word we do not understand is the failure the
# fall-through exists to prevent, so it must not be read as running.
if start_stub '{"status":"starting","database":"ok"}'; then
    out=$(run_against "$(cat "$tmp/port")")
    assert_contains "is not reported as running" "$out" "did not answer"
else
    failed=$((failed + 1)); echo "  FAIL the stub never reported a port"
fi
stop_stub

echo ""
echo "the structural cases"
# Both degraded assertions above could pass while one branch swallowed the
# other, so the separation is asserted against the text as well.
assert_true "the verdict reads the database, not only the status" \
    "$(printf '%s\n' "$block" | grep -q '"database":"ok"' && echo yes || echo no)"
assert_true "the wait loop stops on degraded, not only on healthy" \
    "$(printf '%s\n' "$block" | grep -q 'status":"degraded"' && echo yes || echo no)"
assert_true "the file still polls thirty times at two seconds" \
    "$(printf '%s\n' "$block" | grep -q 'health_attempts=30' && printf '%s\n' "$block" | grep -q 'health_delay=2' && echo yes || echo no)"
assert_true "no message hard-codes the wait in seconds" \
    "$(grep -q 'within 60s' "$src" && echo no || echo yes)"

echo ""
if [ "$failed" -gt 0 ]; then
    echo "$failed failed, $passed passed"
    exit 1
fi
echo "$passed passed"
exit 0
