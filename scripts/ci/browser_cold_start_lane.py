#!/usr/bin/env python3
"""Start a cold install, then drive a real browser through its first session.

``scripts/ci/cli_cold_start_probe.py`` proves a cold install answers HTTP: it
starts the CLI against an empty data directory, waits for ``/api/health``, and
makes the register and sign-in calls an installer would make. It does that with
``urllib``, which is the right tool for that question and cannot ask any other
question. What it cannot see is what a browser does with the same server: how
many requests one page load fires, whether the console is clean, whether a toast
appears on a page that has not been given a chance to load anything, whether the
sign-up form still asks how the visitor found us.

Those were the reports this lane exists for. A person on a fresh Windows install
counted 585 requests and 6.4 MB for one load of the sign-in page, 27 console
errors, and a "could not load data" toast that arrived with the page. Every one
of those is a property of the running product rather than of any part of it, so
no unit suite could have produced them and no unit suite can refute them.

The division of labour is deliberate and is why this is a second script rather
than a flag on the first. This one owns the process and the clock: it starts the
CLI exactly as the probe does, measures how long the server took to answer,
checks that what it serves is the built interface and not a 404, and hands the
port to Playwright. The browser owns the page: the assertions about requests,
console messages and forms live in ``frontend/e2e/cold-start-first-boot.spec.ts``,
where they can be read next to the selectors they use. What this script does with
the result is publish it. Playwright's JSON report carries the metrics lines the
spec prints, and those become job annotations and a step summary, so the numbers
are on the run rather than in a log nobody downloads. The same report also
carries, for every test that did not pass, the test's own title, the message of
the assertion that stopped it, and the steps it had run with their durations;
those become one error annotation each, because a red run of this lane is
otherwise a verdict with no subject. The first Windows failure of this lane was
exactly that. Three of the four tests passed, one did not, and everything
readable from the run page said "the browser lane exited 1": the log comes back
as an empty response from the results receiver and the artifact that holds the
traces is on a blob host, so the two places the failing test's name existed were
both unreachable from the machine that had to diagnose it.

Stdlib only, like the probe: this runs in a job that has installed the product
and nothing else, and a lane that has to install a dependency to report on the
dependencies is a lane with a second way to fail.

Usage:
    python scripts/ci/browser_cold_start_lane.py --port 8765 --timeout 900
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The backend package lives here; the CLI is started from it.
BACKEND_DIR = ROOT / "backend"

#: Variables that would let the CLI skip booting its own cluster, which is the
#: only thing a cold start can measure.
FORBIDDEN_ENV = ("DATABASE_URL", "DATABASE_SYNC_URL")

#: The prefix the spec prints its metrics with. One line, one JSON object.
METRICS_PREFIX = "OE-COLD-START-METRICS"

#: GitHub keeps at most ten annotations of each level per step, so the eleventh
#: failing test is folded into one line saying how many were left out rather than
#: dropped in silence. ``scripts/publish_test_counts.py`` does the same for the
#: backend shards, for the same reason: past the cap an annotation disappears
#: with nothing on the run to say it ever existed.
_ANNOTATION_LIMIT = 10

#: What Playwright's JSON report calls a test that did not end the way the spec
#: claimed it would. "flaky" cannot arise while retries are off (see
#: ``frontend/playwright.cold-start.config.ts``) and is named anyway, because a
#: lane that ignored a status it did not recognise would publish a pass it never
#: saw.
_UNEXPECTED_TEST_STATUSES = frozenset({"unexpected", "flaky"})

#: What one attempt inside such a test is called when that attempt stopped.
_STOPPED_RESULT_STATUSES = frozenset({"failed", "timedOut", "interrupted"})

#: Playwright colourises the assertion message it puts in its own report.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

#: The three shapes of line in that message that are not the message: the source
#: frame it points at (``>  8 |   expect(...)``), the caret under it, and the
#: stack (``at /path/to/spec.ts:8:59``).
_SOURCE_FRAME = re.compile(r"^>?\s*\d+\s*\|")
_CARET_LINE = re.compile(r"^\|?\s*\^+\s*$")
_STACK_LINE = re.compile(r"^at\s+\S")

#: The words the embedded cluster uses for "something went wrong", in the log it
#: writes under the data directory.
_DATABASE_COMPLAINTS = ("ERROR", "FATAL", "PANIC")


def _annotate(level: str, message: str) -> None:
    """Print a GitHub Actions annotation.

    Used instead of a plain line for anything a reader of the run should not
    have to find: the whole point of publishing the counts is that they are
    visible where the verdict is.
    """
    # A newline inside an annotation truncates it, so metrics are flattened.
    print(f"::{level}::{message}".replace("\n", " "), flush=True)


def _one_line(text: str, limit: int) -> str:
    """A message safe to hand to ``_annotate``: no colour, no newline, capped.

    Playwright writes the assertion message it reports in colour, and an
    annotation is one line of plain text on a web page: with the escapes left in
    it reads as ``<0x1b>[31mReceived<0x1b>[39m``, and with a newline left in the
    rest of the message prints as ordinary output below a truncated annotation.
    """
    plain = " ".join(part.strip() for part in _ANSI_ESCAPE.sub("", text).splitlines() if part.strip())
    return plain if len(plain) <= limit else plain[: max(0, limit - 3)] + "..."


def _readable_message(text: str) -> str:
    """The part of Playwright's message a reader can act on.

    The report carries the assertion, then the source frame it came from, then a
    stack. Flattened onto one line on a web page, the frame and the stack push
    the assertion itself past the cap - the first probe of this function returned
    seven hundred characters of which the useful part was the first sentence.
    What survives is the sentence the spec wrote and, for a wait that ran out,
    the call log naming the locator that was waited for, which is the whole
    answer to "what was it looking at when it stopped".
    """
    kept: list[str] = []
    for line in _ANSI_ESCAPE.sub("", text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _SOURCE_FRAME.match(stripped) or _CARET_LINE.match(stripped) or _STACK_LINE.match(stripped):
            continue
        kept.append(stripped)
    return " ".join(kept)


def _annotate_database_complaints(data_dir: Path) -> None:
    """Put the embedded cluster's own errors on the run page.

    ``_fail`` already prints the tail of the newest PostgreSQL log, and printing
    it is not enough: the job log this repository's CI writes is not downloadable
    from every environment (the results receiver answers with an empty body), so
    a tail in the log is a tail nobody reads. A cold start whose symptom is
    browser-shaped - a page that never rendered, a request that never came back -
    has its cause in this file more often than in anything the browser saw, and
    the lines that matter are the ones the cluster wrote at ERROR or worse.
    """
    pg_log = data_dir / "pgdata" / "log"
    if not pg_log.is_dir():
        return
    logs = sorted(pg_log.glob("*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return
    try:
        text = logs[-1].read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # the cluster's log is evidence, never a second failure
        print(f"could not read {logs[-1]}: {exc}", flush=True)
        return
    complaints = [line.strip() for line in text.splitlines() if any(word in line for word in _DATABASE_COMPLAINTS)]
    if not complaints:
        return
    kept = complaints[-6:]
    _annotate(
        "error",
        f"the embedded cluster logged {len(complaints)} complaint(s) in {logs[-1].name}, "
        f"the last {len(kept)}: " + _one_line("\n".join(kept), 900),
    )


def _stop(child: subprocess.Popen | None) -> None:
    """Stop the CLI, and on Windows its whole tree.

    The embedded postmaster is a grandchild: terminating the Python process
    alone leaves it holding the data directory on a Windows runner, and the next
    lane in the matrix then fails on a directory it did not create.
    """
    if child is None or child.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(child.pid)],
            check=False,
            capture_output=True,
        )
        return
    child.terminate()
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        child.kill()


def _fail(message: str, child: subprocess.Popen | None = None, data_dir: Path | None = None) -> int:
    """Say why the lane stopped, name the log that holds the cause, and stop."""
    _annotate("error", f"browser cold start failed: {message}")

    if data_dir is not None:
        pg_log = data_dir / "pgdata" / "log"
        print(f"data directory: {data_dir}", flush=True)
        if data_dir.exists():
            print(
                "data directory contents: " + ", ".join(sorted(p.name for p in data_dir.iterdir())),
                flush=True,
            )
        if pg_log.is_dir():
            logs = sorted(pg_log.glob("*.log"), key=lambda p: p.stat().st_mtime)
            if logs:
                print(f"--- tail of {logs[-1].name} ---", flush=True)
                print(
                    "\n".join(logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()[-40:]),
                    flush=True,
                )
        # The tail above goes into the job log, which is not readable from
        # everywhere; the cluster's own errors go onto the run page as well.
        _annotate_database_complaints(data_dir)

    _stop(child)
    return 1


def _get(port: int, path: str, timeout: float = 30.0) -> tuple[int, str]:
    """One GET against the cold install. Returns (status, body)."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # a status is an answer, just not a good one
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def _check_it_serves_the_interface(port: int) -> str | None:
    """Fail unless the server answers ``/`` with the built interface.

    A browser lane pointed at a server that serves nothing would still run: every
    navigation would 404, the request counts would be tiny, the console would be
    quiet, and the lane would report a healthy first boot for a product that
    cannot draw one. This is the check that makes the rest mean something.

    The backend resolves its own interface directory - ``app/_frontend_dist``
    when the wheel or an editable install carried one, ``../frontend/dist``
    otherwise - and those two can disagree with what the job downloaded. Asking
    the running server is the only source that cannot be wrong about which of
    them it chose.
    """
    status, body = _get(port, "/")
    if status != 200:
        return f"GET / answered {status or 'nothing'}; the CLI is not serving an interface at all"
    if 'id="root"' not in body:
        return f"GET / answered 200 but the body carries no application root: {body[:200]!r}"
    return ""


def _collect_stdout(node: object, found: list[str]) -> None:
    """Walk Playwright's JSON report and take every line of captured stdout."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "stdout" and isinstance(value, list):
                for chunk in value:
                    text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
                    found.append(text)
            else:
                _collect_stdout(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_stdout(item, found)


def _metrics_from(report: object) -> list[dict[str, object]]:
    """The metrics objects the spec printed, in the order it printed them."""
    lines: list[str] = []
    _collect_stdout(report, lines)
    parsed: list[dict[str, object]] = []
    for line in lines:
        for part in line.splitlines():
            if METRICS_PREFIX not in part:
                continue
            payload = part.split(METRICS_PREFIX, 1)[1].strip()
            try:
                loaded = json.loads(payload)
            except json.JSONDecodeError:
                _annotate("warning", f"a metrics line did not parse: {payload[:200]}")
                continue
            if isinstance(loaded, dict):
                parsed.append(loaded)
    return parsed


def _slowest_steps(result: dict, limit: int = 3) -> list[str]:
    """The steps of one attempt that took longest, as ``"page.goto 1200ms"``.

    A cold-start failure is most often a wait that ran out, and "ran out" is a
    duration rather than a sentence. Playwright nests steps inside steps, so this
    walks the whole tree and keeps the longest few instead of taking the
    outermost ones - the outermost are the outermost precisely because they
    contain the others, and "Before Hooks 60012ms" says nothing about which wait
    inside them was the slow one.
    """
    found: list[tuple[float, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            title = node.get("title")
            duration = node.get("duration")
            if isinstance(title, str) and isinstance(duration, (int, float)):
                found.append((float(duration), title))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(result.get("steps"))
    found.sort(key=lambda pair: -pair[0])
    return [f"{title} {duration:.0f}ms" for duration, title in found[:limit]]


def _failure_of(spec: dict, test: dict, file_name: str) -> dict[str, object]:
    """One test that did not pass, reduced to what a reader of the run needs.

    The location comes from the attempt's own ``errorLocation`` when it has one
    and falls back to the line the spec declared the test on, because the two
    answer different questions and the first is the one a reader can open: the
    spec's line is where the test starts, the attempt's is where it stopped.
    """
    results = [item for item in (test.get("results") or []) if isinstance(item, dict)]
    stopped = [item for item in results if str(item.get("status")) in _STOPPED_RESULT_STATUSES]
    attempts = stopped or results
    attempt: dict = attempts[-1] if attempts else {}

    errors = attempt.get("errors")
    if not isinstance(errors, list) or not errors:
        single = attempt.get("error")
        errors = [single] if isinstance(single, dict) else []
    messages: list[str] = []
    for error in errors:
        text = error.get("message") if isinstance(error, dict) else None
        if isinstance(text, str) and text.strip():
            messages.append(text.strip())

    location = attempt.get("errorLocation")
    where: dict = location if isinstance(location, dict) else {}
    return {
        "file": file_name or str(spec.get("file") or ""),
        "line": where.get("line") or spec.get("line"),
        "title": spec.get("title"),
        "attempt_status": attempt.get("status") or test.get("status"),
        "duration_ms": attempt.get("duration"),
        "message": _one_line(
            _readable_message(messages[0]) if messages else "the report carried no message for this failure",
            900,
        ),
        "further_messages": max(0, len(messages) - 1),
        "slowest_steps": _slowest_steps(attempt),
    }


def _failures_from(report: object) -> list[dict[str, object]]:
    """Every test Playwright did not expect to end the way the spec claimed.

    The report is walked rather than indexed because its shape is a tree of
    suites whose depth is whatever the spec's ``test.describe`` nesting makes it.
    A lane that assumed one level would publish nothing at all about a spec that
    grew a describe block, and a lane that publishes nothing about a failure is
    the thing this function exists to prevent.
    """
    found: list[dict[str, object]] = []

    def walk(node: object, file_name: str) -> None:
        if isinstance(node, dict):
            own_file = node.get("file")
            nested = own_file if isinstance(own_file, str) and own_file else file_name
            specs = node.get("specs")
            if isinstance(specs, list):
                for spec in specs:
                    if not isinstance(spec, dict):
                        continue
                    tests = spec.get("tests")
                    if not isinstance(tests, list):
                        continue
                    for test in tests:
                        if isinstance(test, dict) and str(test.get("status")) in _UNEXPECTED_TEST_STATUSES:
                            found.append(_failure_of(spec, test, nested))
            for value in node.values():
                walk(value, nested)
        elif isinstance(node, list):
            for item in node:
                walk(item, file_name)

    walk(report, "")
    return found


def _annotate_failures(failures: list[dict[str, object]]) -> list[str]:
    """One error annotation per failing test, folded at GitHub's cap of ten.

    This is the half of the lane a red run cannot do without. The step's exit
    code says only that Playwright was unhappy; the traces and the video that
    say which of the four tests stopped are inside an artifact, and neither the
    job log nor the artifact could be fetched from the environment that had to
    diagnose this lane's first Windows failure. What was readable there was the
    ``expected=3 unexpected=1`` notice and the *absence* of one metrics line,
    which together named the test only by elimination and said nothing about why
    it stopped. The report already carries the why.
    """
    lines: list[str] = []
    for index, failure in enumerate(failures):
        parts = [
            f"{failure.get('file') or 'the spec'}:{failure.get('line')} {failure.get('title')}",
            f"{failure.get('attempt_status')} after {failure.get('duration_ms')}ms",
        ]
        message = failure.get("message")
        if isinstance(message, str) and message:
            parts.append(message)
        further = failure.get("further_messages")
        if isinstance(further, int) and further:
            parts.append(f"{further} more error(s) in the report")
        steps = failure.get("slowest_steps")
        if isinstance(steps, list) and steps:
            parts.append("longest steps: " + ", ".join(str(step) for step in steps))
        line = " | ".join(parts)
        if index < _ANNOTATION_LIMIT:
            _annotate("error", line)
        lines.append(f"- {line}")
    if len(failures) > _ANNOTATION_LIMIT:
        note = (
            f"{len(failures) - _ANNOTATION_LIMIT} further failing test(s) are in the step summary only: "
            f"GitHub keeps {_ANNOTATION_LIMIT} annotations of a level per step"
        )
        _annotate("error", note)
        lines.append(f"- {note}")
    return lines


def _summarise_census(metrics: dict[str, object]) -> list[str]:
    """Turn the sign-in page census into the lines a reader of the run needs."""
    lines = [
        f"requests: total={metrics.get('total_requests')} api={metrics.get('api_requests')} "
        f"assets={metrics.get('asset_requests')} over {metrics.get('record_window_ms')}ms",
    ]
    by_endpoint = metrics.get("by_endpoint")
    if isinstance(by_endpoint, dict) and by_endpoint:
        ordered = sorted(by_endpoint.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
        lines.append("requests per endpoint: " + ", ".join(f"{name}={count}" for name, count in ordered[:20]))
    worst = metrics.get("worst_repeat")
    if isinstance(worst, dict):
        lines.append(f"most-repeated single URL: {worst.get('url')} x{worst.get('count')}")
    for key in ("server_errors", "console_errors", "page_errors"):
        value = metrics.get(key)
        if isinstance(value, list):
            lines.append(f"{key}: {len(value)}" + (f" {json.dumps(value[:5])[:400]}" if value else ""))
    lines.append(f"load_failure_toast: {metrics.get('load_failure_toast')}")
    return lines


def _publish(metrics_list: list[dict[str, object]], failure_lines: list[str] | None = None) -> None:
    """Annotations plus, when the runner offers one, a step summary.

    The failing tests come first in the summary. A reader who opens a red run
    wants the verdict before the measurements, and the measurements are what
    explain it - the other order reads as a wall of numbers with a failure
    buried under it.
    """
    summary: list[str] = ["### Browser cold start", ""]
    if failure_lines:
        summary.append("**Tests that did not pass**")
        summary += failure_lines
        summary.append("")
    for metrics in metrics_list:
        name = str(metrics.get("name", "unnamed"))
        if "total_requests" in metrics:
            lines = _summarise_census(metrics)
        else:
            lines = [f"{key}={json.dumps(value)[:200]}" for key, value in metrics.items() if key != "name"]
        _annotate("notice", f"[{name}] " + " | ".join(lines))
        summary.append(f"**{name}**")
        summary += [f"- {line}" for line in lines]
        summary.append("")

    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        try:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("\n".join(summary) + "\n")
        except OSError as exc:  # a summary is a convenience, never a verdict
            print(f"could not write the step summary: {exc}", flush=True)


def _playwright_cli(frontend_dir: Path) -> Path | None:
    """Playwright's own entry point, so no shell and no `npx` resolution."""
    candidate = frontend_dir / "node_modules" / "@playwright" / "test" / "cli.js"
    return candidate if candidate.is_file() else None


def _node_executable() -> str | None:
    """The interpreter that entry point needs, resolved rather than assumed.

    ``cli.js`` is JavaScript and Node runs it. The first version of this lane passed
    ``sys.executable``, which is the Python that is running this file, and Python
    reading a JavaScript file dies on the first line: exit code 1, no report, no
    metrics, and nothing on the console that names the cause. Both matrix legs failed
    that way at ``a69ab2a4`` and the only evidence in the run was the *absence* of
    ``test-results/cold-start-report.json``. Resolving Node here, before a server is
    started and before a browser is launched, is what turns that into a named refusal.
    """
    return shutil.which("node")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="port the CLI should bind (default 8765)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="seconds to wait for health (default 900)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="data directory to use; it must be empty or absent (default: a fresh temporary one)",
    )
    parser.add_argument(
        "--keep-data-dir",
        action="store_true",
        help="leave a data directory this lane created behind (for a later step to inspect)",
    )
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=ROOT / "frontend",
        help="the frontend package to run",
    )
    parser.add_argument(
        "--config",
        default="playwright.cold-start.config.ts",
        help="Playwright config, relative to the frontend directory",
    )
    parser.add_argument(
        "--record-window",
        type=int,
        default=45,
        help="seconds the sign-in page is watched (default 45)",
    )
    args = parser.parse_args()

    inherited = [name for name in FORBIDDEN_ENV if os.environ.get(name)]
    if inherited:
        _annotate(
            "error",
            f"{' and '.join(inherited)} is already set in this environment. This lane exists to start the product "
            "with no database configured, the way a new install does; with one set it would measure somebody "
            "else's server. Unset it in the calling job.",
        )
        return 1

    if not BACKEND_DIR.is_dir():
        return _fail(f"no backend directory at {BACKEND_DIR}")

    frontend_dir: Path = args.frontend_dir
    if not frontend_dir.is_dir():
        return _fail(f"no frontend directory at {frontend_dir}")

    cli_js = _playwright_cli(frontend_dir)
    if cli_js is None:
        return _fail(
            f"no @playwright/test under {frontend_dir / 'node_modules'}; the job has to run npm ci before this lane"
        )

    node = _node_executable()
    if node is None:
        return _fail("no node on PATH; the job has to run actions/setup-node before this lane")

    created = False
    data_dir = args.data_dir
    if data_dir is None:
        data_dir = Path(tempfile.mkdtemp(prefix="oe-browser-cold-start-"))
        created = True
    elif data_dir.exists() and any(data_dir.iterdir()):
        return _fail(f"--data-dir {data_dir} is not empty; a cold start needs a clean one")

    env = dict(os.environ)
    # Demo data off: a cold start must come up on an empty database, and a
    # seeded one would answer the sign-in page's first queries with rows the
    # installer's own install would not have.
    env["SEED_DEMO"] = "false"
    for name in (*FORBIDDEN_ENV, "OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR"):
        env.pop(name, None)

    command = [
        sys.executable,
        "-m",
        "app.cli",
        "serve",
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
    ]
    print(f"data directory: {data_dir}", flush=True)
    print("starting: " + " ".join(command), flush=True)

    started = time.monotonic()
    child: subprocess.Popen | None = None
    report_path = frontend_dir / "test-results" / "cold-start-report.json"
    try:
        child = subprocess.Popen(
            command,
            cwd=str(BACKEND_DIR),
            env=env,
            stdin=subprocess.DEVNULL,  # no terminal: a first-run prompt must not be able to block the lane
        )

        deadline = started + args.timeout
        last_status = 0
        announced = 0.0
        while time.monotonic() < deadline:
            exit_code = child.poll()
            if exit_code is not None:
                return _fail(
                    f"the CLI exited with code {exit_code} before /api/health answered",
                    child,
                    data_dir,
                )

            last_status, body = _get(args.port, "/api/health", timeout=10)
            if last_status == 200:
                seconds_to_healthy = time.monotonic() - started
                print(
                    f"\n/api/health answered 200 after {seconds_to_healthy:.1f}s",
                    flush=True,
                )
                try:
                    print(
                        "health payload: " + json.dumps(json.loads(body), sort_keys=True),
                        flush=True,
                    )
                except json.JSONDecodeError:
                    print(f"health payload (not JSON): {body[:400]}", flush=True)

                pg_version = data_dir / "pgdata" / "PG_VERSION"
                if not pg_version.exists():
                    return _fail(
                        f"health answered but {pg_version} was never written",
                        child,
                        data_dir,
                    )
                print(
                    f"embedded cluster initialised: {pg_version.read_text(encoding='utf-8').strip()}",
                    flush=True,
                )

                interface_problem = _check_it_serves_the_interface(args.port)
                if interface_problem:
                    return _fail(interface_problem, child, data_dir)
                print("the CLI is serving the built interface at /", flush=True)

                _annotate(
                    "notice",
                    f"time to first healthy response: {seconds_to_healthy:.1f}s",
                )
                break

            now = time.monotonic()
            if now - announced >= 15:
                announced = now
                state = f"last status {last_status}" if last_status else "not listening yet"
                print(
                    f"  waiting for /api/health ... {now - started:.0f}s ({state})",
                    flush=True,
                )
            time.sleep(2)
        else:
            return _fail(
                f"/api/health did not answer 200 within {args.timeout:.0f}s",
                child,
                data_dir,
            )

        report_path.parent.mkdir(parents=True, exist_ok=True)
        run_env = dict(env)
        run_env["OE_COLD_START_BASE_URL"] = f"http://127.0.0.1:{args.port}"
        run_env["OE_COLD_START_RECORD_WINDOW_MS"] = str(args.record_window * 1000)
        run_env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(report_path)
        run_env["CI"] = "1"

        playwright_command = [
            node,
            str(cli_js),
            "test",
            "--config",
            args.config,
            "--reporter=list,json",
        ]
        print("running: " + " ".join(playwright_command), flush=True)
        finished = subprocess.run(playwright_command, cwd=str(frontend_dir), env=run_env, check=False)

        metrics_list: list[dict[str, object]] = []
        report: object = None
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                _annotate("warning", f"Playwright's JSON report did not parse: {exc}")
        else:
            # The exit code is in the annotation on purpose. A missing report has one
            # cause that is a product defect and a dozen that are this lane failing to
            # run Playwright at all, and only the code tells them apart from a run page.
            _annotate(
                "warning",
                f"no Playwright JSON report at {report_path} (playwright exited {finished.returncode})",
            )

        failures_found: list[dict[str, object]] = []
        failure_lines: list[str] = []
        if isinstance(report, dict):
            metrics_list = _metrics_from(report)
            stats = report.get("stats")
            if isinstance(stats, dict):
                _annotate(
                    "notice",
                    "playwright: expected={expected} unexpected={unexpected} skipped={skipped} "
                    "duration={duration}ms".format(
                        **{k: stats.get(k) for k in ("expected", "unexpected", "skipped", "duration")}
                    ),
                )
            failures_found = _failures_from(report)
            failure_lines = _annotate_failures(failures_found)
            run_errors = report.get("errors")
            if isinstance(run_errors, list) and run_errors:
                # A report-level error is one Playwright could not attach to any
                # test - a config that did not load, a worker that died - and for
                # a run like that it is the only explanation there is.
                _annotate(
                    "error",
                    "playwright reported for the run itself: " + _one_line(json.dumps(run_errors), 900),
                )
        if metrics_list or failure_lines:
            _publish(metrics_list, failure_lines)
        if not metrics_list:
            _annotate(
                "warning",
                "the spec printed no metrics line; the counts are missing from this run",
            )

        if finished.returncode != 0:
            print(
                f"\ntraces, screenshots and video are under {frontend_dir / 'test-results'}; "
                f"the report is at {report_path}",
                flush=True,
            )
            # Naming the subject of the failure in the verdict itself, and not
            # only in the annotations above it, because this is the line a list
            # of red jobs shows.
            if failures_found:
                subject = (
                    f"the browser lane exited {finished.returncode}: "
                    f"{len(failures_found)} test(s) did not pass, and each is annotated above"
                )
            else:
                subject = (
                    f"the browser lane exited {finished.returncode} and the report named no failing test, "
                    "so Playwright did not get as far as running them"
                )
            return _fail(subject, child, data_dir)
        return 0
    finally:
        _stop(child)
        if created and not args.keep_data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
