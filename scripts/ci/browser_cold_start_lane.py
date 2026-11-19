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
the result is publish it - Playwright's JSON report carries the metrics lines the
spec prints, and those become job annotations and a step summary, so the numbers
are on the run rather than in a log nobody downloads.

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


def _annotate(level: str, message: str) -> None:
    """Print a GitHub Actions annotation.

    Used instead of a plain line for anything a reader of the run should not
    have to find: the whole point of publishing the counts is that they are
    visible where the verdict is.
    """
    # A newline inside an annotation truncates it, so metrics are flattened.
    print(f"::{level}::{message}".replace("\n", " "), flush=True)


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


def _publish(metrics_list: list[dict[str, object]]) -> None:
    """Annotations plus, when the runner offers one, a step summary."""
    summary: list[str] = ["### Browser cold start", ""]
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
            sys.executable,
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
            _annotate("warning", f"no Playwright JSON report at {report_path}")

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
        if metrics_list:
            _publish(metrics_list)
        else:
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
            return _fail(f"the browser lane exited {finished.returncode}", child, data_dir)
        return 0
    finally:
        _stop(child)
        if created and not args.keep_data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
