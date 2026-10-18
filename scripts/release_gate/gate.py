"""Install and upgrade checks for a release wheel, run the way a user runs it.

The release gate workflow (``.github/workflows/release-gate.yml``) calls this
script on Linux, Windows and macOS. Everything that differs between those
systems lives here rather than in shell, so every runner executes the same
logic: creating the virtualenv, installing, starting ``openconstructionerp
serve`` exactly as the install guides say, waiting for it, asking it
questions over HTTP, and stopping it the way Ctrl+C does.

Only the standard library is used, because this runs on the runner's own
interpreter, outside the virtualenv under test.

Subcommands:

``install``   create (or reuse) a virtualenv and pip install a wheel or a spec.
``fresh``     boot a clean install, check health, version, the SPA and a
              public API route, check the boot log, stop.
``seed``      boot an install (normally the previous release), register the
              first admin, create a project, a BOQ and positions, record what
              was created to a snapshot file, stop.
``verify``    boot after the upgrade and check that everything in the snapshot
              is still there with the same amounts, plus the fresh checks.

Exit status is 0 when every check passed and 1 otherwise. Each failure is
printed as a GitHub ``::error::`` line and the server log tail is printed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"

ADMIN_EMAIL = "release-gate-admin@example.com"
ADMIN_PASSWORD = "ReleaseGate2026check"  # noqa: S105 - throwaway account on a CI runner
PROJECT_NAME = "Release gate upgrade project"
BOQ_NAME = "Release gate BOQ"

# Positions with fractional quantities and rates, so a lossy float round trip
# or a changed rounding rule shows up as a different total after the upgrade.
POSITIONS: list[dict[str, str]] = [
    {
        "ordinal": "01.001",
        "description": "Reinforced concrete wall C30/37",
        "unit": "m3",
        "quantity": "125.5",
        "unit_rate": "285.37",
    },
    {
        "ordinal": "01.002",
        "description": "Formwork both sides",
        "unit": "m2",
        "quantity": "1046.25",
        "unit_rate": "38.90",
    },
    {
        "ordinal": "02.001",
        "description": "Reinforcement steel B500B",
        "unit": "t",
        "quantity": "18.375",
        "unit_rate": "1499.99",
    },
]

# What counts as an error in a boot log. The level names are matched as whole
# words in the positions the two log formats used at boot put them: the stdlib
# ``LEVEL:name:`` form uvicorn prints and the ``[level]`` / `` LEVEL `` forms of
# the application's own formatter. A bare word search would trip over module
# names and log text that merely mention errors.
_LOG_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"^\s*(ERROR|CRITICAL)[:\s]"),
    re.compile(r"\[(error|critical)\s*\]", re.IGNORECASE),
    re.compile(r"\s(ERROR|CRITICAL)\s"),
    re.compile(r"STAGE:server:fail"),
)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in backend/tests/unit/test_release_gate_helper.py)
# ---------------------------------------------------------------------------


def scan_log_for_errors(text: str, allow: list[str] | None = None) -> list[str]:
    """Return the log lines that look like errors, minus the allowed ones.

    Args:
        text: The full server log.
        allow: Regular expressions; a matching line is not reported.

    Returns:
        The offending lines, in order, stripped of trailing whitespace.
    """
    allowed = [re.compile(a) for a in (allow or [])]
    hits: list[str] = []
    for line in text.splitlines():
        if not any(p.search(line) for p in _LOG_ERROR_PATTERNS):
            continue
        if any(a.search(line) for a in allowed):
            continue
        hits.append(line.rstrip())
    return hits


def health_problems(payload: dict[str, Any], expected_version: str | None, *, fresh: bool) -> list[str]:
    """Say what is wrong with an ``/api/health`` payload, if anything.

    Args:
        payload: The decoded JSON body.
        expected_version: The version the install must report, or None to skip.
        fresh: True on a brand new database, where the boot stamps the
            migration head, so ``alembic_head_matches`` must be true. After an
            upgrade the product moves the schema through its boot heal and does
            not advance an existing stamp, so there only ``schema_matches_models``
            is required and the stamp is reported, not asserted.

    Returns:
        Human readable problems; empty means healthy.
    """
    problems: list[str] = []
    if payload.get("status") != "healthy":
        problems.append(f"status is {payload.get('status')!r}, expected 'healthy'")
    if payload.get("database") != "ok":
        problems.append(f"database is {payload.get('database')!r}, expected 'ok'")
    if expected_version is not None and payload.get("version") != expected_version:
        problems.append(f"version is {payload.get('version')!r}, expected {expected_version!r}")
    if payload.get("frontend_dist_present") is not True:
        problems.append(f"frontend_dist_present is {payload.get('frontend_dist_present')!r}, expected true")
    for key in ("schema_heal_failed", "data_repairs_failed", "data_repair_ledger_failed", "schema_match_check_failed"):
        if payload.get(key) is True:
            problems.append(f"{key} is true")
    if payload.get("schema_matches_models") is False:
        problems.append("schema_matches_models is false: the database schema does not match the models")
    if fresh and payload.get("alembic_head_matches") is not True:
        problems.append(
            f"alembic_head_matches is {payload.get('alembic_head_matches')!r} on a fresh install, expected true"
        )
    loaded, enabled = payload.get("modules_loaded"), payload.get("modules_enabled")
    if isinstance(loaded, int) and isinstance(enabled, int) and loaded < enabled:
        problems.append(f"only {loaded} of {enabled} enabled modules loaded")
    return problems


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def compare_snapshot(before: dict[str, Any], after_boq: dict[str, Any], after_project_ids: set[str]) -> list[str]:
    """Compare what ``seed`` recorded with what the upgraded server returns.

    Amounts are compared as decimals, so ``"285.370"`` equals ``"285.37"`` but
    any change in value is reported.

    Args:
        before: The snapshot file written by ``seed``.
        after_boq: ``GET /api/v1/boq/boqs/{id}`` after the upgrade.
        after_project_ids: Every project id the admin can list after the upgrade.

    Returns:
        Human readable differences; empty means the data survived intact.
    """
    problems: list[str] = []
    missing = sorted(set(before.get("project_ids", [])) - after_project_ids)
    if missing:
        problems.append(f"{len(missing)} project(s) visible before the upgrade are gone: {missing[:5]}")

    after_positions = {p.get("ordinal"): p for p in after_boq.get("positions", [])}
    for pos in before.get("positions", []):
        got = after_positions.get(pos["ordinal"])
        if got is None:
            problems.append(f"position {pos['ordinal']} is gone")
            continue
        for key in ("quantity", "unit_rate", "total"):
            if _dec(got.get(key)) != _dec(pos.get(key)):
                problems.append(f"position {pos['ordinal']} {key} was {pos.get(key)!r}, now {got.get(key)!r}")
    if len(after_positions) != len(before.get("positions", [])):
        problems.append(f"BOQ had {len(before.get('positions', []))} positions, now {len(after_positions)}")
    if _dec(after_boq.get("direct_cost_total")) != _dec(before.get("direct_cost_total")):
        problems.append(
            f"direct_cost_total was {before.get('direct_cost_total')!r}, now {after_boq.get('direct_cost_total')!r}"
        )
    return problems


def wheel_version(wheel: Path) -> str:
    """The version part of a wheel file name (PEP 427)."""
    return wheel.name.split("-")[1]


def asset_refs(index_html: str) -> list[str]:
    """Local ``src``/``href`` references of the SPA index page."""
    refs = re.findall(r'(?:src|href)="([^"]+)"', index_html)
    return [r for r in refs if not r.startswith(("http://", "https://", "data:", "//", "#"))]


# ---------------------------------------------------------------------------
# Process and HTTP plumbing
# ---------------------------------------------------------------------------


@dataclass
class Result:
    """Collected failures of one phase."""

    errors: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        print(f"::error::{message}", flush=True)
        self.errors.append(message)

    def check(self, ok: bool, message: str) -> bool:
        if not ok:
            self.fail(message)
        else:
            print(f"ok: {message.split(':')[0] if ':' in message else message}", flush=True)
        return ok


def venv_bin(venv: Path, name: str) -> Path:
    """Path of an executable inside a virtualenv on this OS."""
    if IS_WINDOWS:
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def default_data_dir() -> Path:
    """The data dir a bare ``openconstructionerp serve`` uses (mirrors app.cli)."""
    for var in ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR"):
        raw = os.environ.get(var, "").strip()
        if raw:
            return Path(raw)
    return Path.home() / ".openestimate"


def http(
    method: str, url: str, *, body: Any = None, token: str | None = None, timeout: float = 60
) -> tuple[int, bytes, dict[str, str]]:
    """Make one HTTP request; never raises for an HTTP status."""
    data = None
    headers = {"Accept": "application/json, text/html;q=0.9, */*;q=0.1"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310 - loopback only
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


def http_json(method: str, url: str, **kw: Any) -> tuple[int, Any]:
    status, raw, _ = http(method, url, **kw)
    try:
        return status, json.loads(raw.decode("utf-8") or "null")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, raw[:500].decode("utf-8", "replace")


class Server:
    """``openconstructionerp serve`` started as a user starts it."""

    def __init__(self, venv: Path, port: int, log_path: Path, extra_env: dict[str, str] | None = None) -> None:
        self.venv = venv
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.log_path = log_path
        self.extra_env = extra_env or {}
        self.proc: subprocess.Popen[bytes] | None = None
        self._log_fh: Any = None
        self.forced_stop = False

    def start(self) -> None:
        exe = venv_bin(self.venv, "openconstructionerp")
        if not exe.exists():
            raise SystemExit(f"::error::entry point {exe} is missing; the wheel did not install its console script")
        env = dict(os.environ)
        env.update(self.extra_env)
        # Line-buffered output so the log is complete when the process is
        # stopped and readable while it boots. This changes no behaviour.
        env["PYTHONUNBUFFERED"] = "1"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = open(self.log_path, "ab")  # noqa: SIM115 - closed in stop()
        cmd = [str(exe), "serve", "--port", str(self.port)]
        print(f"starting: {' '.join(cmd)}", flush=True)
        kwargs: dict[str, Any] = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(  # noqa: S603
            cmd, stdin=subprocess.DEVNULL, stdout=self._log_fh, stderr=subprocess.STDOUT, env=env, **kwargs
        )

    def wait_healthy(self, timeout: float) -> dict[str, Any] | None:
        """Poll ``/api/health`` until it answers 200, the process dies, or time runs out."""
        assert self.proc is not None
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        last_note = 0.0
        while time.monotonic() < deadline:
            code = self.proc.poll()
            if code is not None:
                print(f"::error::server exited with code {code} before it answered /api/health", flush=True)
                return None
            with contextlib.suppress(OSError, TimeoutError, ConnectionError):
                status, payload = http_json("GET", f"{self.base}/api/health", timeout=15)
                if status == 200 and isinstance(payload, dict):
                    print(f"health answered after {time.monotonic() - started:.0f}s", flush=True)
                    return payload
            if time.monotonic() - last_note > 60:
                last_note = time.monotonic()
                print(f"waiting for /api/health ({time.monotonic() - started:.0f}s)", flush=True)
            time.sleep(3)
        print(f"::error::/api/health did not answer within {timeout:.0f}s", flush=True)
        return None

    def stop(self, timeout: float = 120) -> bool:
        """Stop the server the way Ctrl+C does; True when it went down on its own."""
        if self.proc is None:
            return True
        graceful = True
        if self.proc.poll() is None:
            print("stopping server (Ctrl+C equivalent)", flush=True)
            if IS_WINDOWS:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                # A terminal delivers Ctrl+C to the whole foreground group.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGINT)
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                graceful = False
                print(f"::error::server did not stop within {timeout:.0f}s of Ctrl+C; killing it", flush=True)
                self._kill_tree()
        print(f"server exit code {self.proc.returncode}", flush=True)
        if self._log_fh:
            self._log_fh.close()
        self.forced_stop = not graceful
        return graceful

    def _kill_tree(self) -> None:
        assert self.proc is not None
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], check=False)  # noqa: S603, S607
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=30)

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


def pid_alive(pid: int) -> bool:
    """Whether a process id is alive on this machine."""
    if IS_WINDOWS:
        out = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def leftover_postmaster(data_dir: Path) -> int | None:
    """The embedded PostgreSQL postmaster still running for ``data_dir``, if any."""
    pidfile = data_dir / "pgdata" / "postmaster.pid"
    try:
        first = pidfile.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
        pid = int(first)
    except (OSError, IndexError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def collect_diagnostics(data_dir: Path, out: Path) -> None:
    """Copy the embedded PostgreSQL log and crash logs next to the server log."""
    dest = out / "data-dir-logs"
    for rel in ("pgdata/log", "logs", "crash.log", "crash_diagnostics.log"):
        src = data_dir / rel
        with contextlib.suppress(OSError):
            if src.is_dir():
                shutil.copytree(src, dest / rel, dirs_exist_ok=True)
            elif src.is_file():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / rel)


def print_log_tail(server: Server, lines: int = 200) -> None:
    text = server.log_text().splitlines()
    print(f"----- last {min(lines, len(text))} lines of {server.log_path} -----")
    for line in text[-lines:]:
        print(line)
    print("----- end of server log -----", flush=True)


# ---------------------------------------------------------------------------
# Checks shared by the phases
# ---------------------------------------------------------------------------


def check_spa_and_public_api(server: Server, res: Result) -> None:
    status, raw, headers = http("GET", f"{server.base}/", timeout=60)
    ctype = {k.lower(): v for k, v in headers.items()}.get("content-type", "")
    html = raw.decode("utf-8", "replace")
    if not res.check(status == 200 and "text/html" in ctype, f"SPA index: GET / answered {status} {ctype!r}"):
        return
    refs = asset_refs(html)
    res.check(bool(refs), "SPA index: page references no assets, it is not the built frontend")
    scripts = [r for r in refs if r.endswith(".js")] or refs
    if scripts:
        a_status, a_raw, _ = http("GET", f"{server.base}/{scripts[0].lstrip('/')}", timeout=60)
        res.check(a_status == 200 and len(a_raw) > 0, f"SPA asset: GET {scripts[0]} answered {a_status}")
    status, payload = http_json("GET", f"{server.base}/api/v1/auth/first-run/")
    res.check(
        status == 200 and isinstance(payload, dict),
        f"public API: GET /api/v1/auth/first-run/ answered {status} {str(payload)[:200]}",
    )


def check_cli_version(venv: Path, expected: str, res: Result) -> None:
    exe = venv_bin(venv, "openconstructionerp")
    proc = subprocess.run([str(exe), "version"], capture_output=True, text=True, timeout=300, check=False)  # noqa: S603
    text = proc.stdout + proc.stderr
    res.check(
        proc.returncode == 0 and expected in text,
        f"CLI version: 'openconstructionerp version' printed {text.strip()[:300]!r}, expected {expected}",
    )


def check_single_alembic_head(venv: Path, res: Result) -> None:
    """The installed migration tree must have exactly one head."""
    py = venv_bin(venv, "python")
    code = (
        "import json, pathlib, app\n"
        "from alembic.config import Config\n"
        "from alembic.script import ScriptDirectory\n"
        "ini = pathlib.Path(app.__file__).resolve().parent.parent / 'alembic.ini'\n"
        "print(json.dumps({'ini': str(ini), 'exists': ini.is_file(), "
        "'heads': list(ScriptDirectory.from_config(Config(str(ini))).get_heads()) if ini.is_file() else []}))\n"
    )
    # Some revisions import app.database at module level, and that refuses to
    # load without a PostgreSQL URL. Reading the tree never connects, so an
    # unreachable placeholder is enough; a URL the job already set is kept.
    env = dict(os.environ)
    env.setdefault("DATABASE_URL", "postgresql+asyncpg://gate:gate@127.0.0.1:1/gate")
    proc = subprocess.run(  # noqa: S603
        [str(py), "-c", code], capture_output=True, text=True, timeout=300, check=False, env=env
    )
    try:
        info = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        res.fail(f"alembic heads: could not read the installed migration tree: {(proc.stdout + proc.stderr)[-800:]}")
        return
    print(f"installed alembic heads: {info}", flush=True)
    res.check(info["exists"], f"alembic heads: {info['ini']} is not installed")
    res.check(
        len(info["heads"]) == 1,
        f"alembic heads: installed migration tree has {len(info['heads'])} heads {info['heads']}, expected 1",
    )


def check_boot(server: Server, args: argparse.Namespace, res: Result, *, fresh: bool) -> dict[str, Any] | None:
    health = server.wait_healthy(args.boot_timeout)
    if health is None:
        res.fail("server never became healthy")
        return None
    print("health: " + json.dumps(health, sort_keys=True), flush=True)
    for problem in health_problems(health, args.expect_version, fresh=fresh):
        res.fail(f"health: {problem}")
    if not fresh and health.get("alembic_head_matches") is not True:
        # Known product behaviour, not a gate failure: the boot stamps the
        # migration head only on an empty database, so an upgraded install keeps
        # the previous release's revision while the boot heal brings the schema
        # itself up to date (schema_matches_models above is what is asserted).
        print(
            f"::warning::alembic_head_matches after the upgrade is {health.get('alembic_head_matches')!r}: "
            "the boot does not advance an existing migration stamp, the schema check is what this lane asserts",
            flush=True,
        )
    return health


def finish(server: Server, args: argparse.Namespace, res: Result, data_dir: Path) -> int:
    # Give deferred startup work (the background demo seed) a moment to log
    # whatever it is going to log before the boot log is judged.
    if server.proc is not None and server.proc.poll() is None and args.settle > 0:
        time.sleep(args.settle)
    graceful = server.stop()
    res.check(graceful, "stop: server did not shut down on Ctrl+C")
    if server.proc is not None and server.proc.returncode not in (0, None) and graceful:
        print(f"note: server exit code after Ctrl+C was {server.proc.returncode}", flush=True)
    pm = leftover_postmaster(data_dir)
    res.check(pm is None, f"stop: embedded PostgreSQL postmaster (pid {pm}) is still running after the server stopped")
    if pm is not None:
        # Clear it so the next step measures its own behaviour, not this one's.
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pm)], check=False)  # noqa: S603, S607
        else:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pm, signal.SIGKILL)
    hits = scan_log_for_errors(server.log_text(), args.allow_log)
    if hits:
        res.fail(f"boot log has {len(hits)} error line(s); first ones below")
        for line in hits[:40]:
            print(f"  | {line}")
    else:
        print("ok: boot log has no Traceback/ERROR lines", flush=True)
    collect_diagnostics(data_dir, Path(args.out))
    if res.errors:
        print_log_tail(server)
        print(f"\nFAILED: {len(res.errors)} check(s)", flush=True)
        for e in res.errors:
            print(f"  - {e}")
        return 1
    print("\nALL CHECKS PASSED", flush=True)
    return 0


def login(server: Server) -> str:
    status, payload = http_json(
        "POST", f"{server.base}/api/v1/users/auth/login/", body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
        raise RuntimeError(f"login answered {status}: {str(payload)[:400]}")
    return str(payload["access_token"])


def list_project_ids(server: Server, token: str) -> set[str]:
    status, payload = http_json("GET", f"{server.base}/api/v1/projects/?limit=500", token=token)
    if status != 200:
        raise RuntimeError(f"GET /api/v1/projects/ answered {status}: {str(payload)[:400]}")
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    return {str(p["id"]) for p in items}


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_install(args: argparse.Namespace) -> int:
    venv = Path(args.venv)
    if not venv_bin(venv, "python").exists():
        print(f"creating virtualenv {venv} with {sys.executable} ({sys.version.split()[0]})", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)  # noqa: S603
    py = str(venv_bin(venv, "python"))
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"], check=True)  # noqa: S603
    if args.wheel_dir:
        wheels = sorted(Path(args.wheel_dir).glob("openconstructionerp-*.whl"))
        if len(wheels) != 1:
            print(f"::error::expected exactly one wheel in {args.wheel_dir}, found {wheels}")
            return 1
        target = str(wheels[0])
        print(f"wheel version {wheel_version(wheels[0])}", flush=True)
    else:
        target = args.spec
    started = time.monotonic()
    proc = subprocess.run([py, "-m", "pip", "install", target], check=False)  # noqa: S603
    print(f"pip install took {time.monotonic() - started:.0f}s", flush=True)
    if proc.returncode != 0:
        print(f"::error::pip install {target} failed with exit code {proc.returncode}")
        return 1
    subprocess.run([py, "-m", "pip", "check"], check=False)  # noqa: S603 - informational
    out = subprocess.run([py, "-m", "pip", "show", "openconstructionerp"], capture_output=True, text=True, check=False)  # noqa: S603
    print(out.stdout, flush=True)
    return 0


def cmd_fresh(args: argparse.Namespace) -> int:
    res = Result()
    venv = Path(args.venv)
    data_dir = default_data_dir()
    res.check(
        not (data_dir / "pgdata").exists() or bool(os.environ.get("DATABASE_URL")),
        f"fresh: data dir {data_dir} already holds a cluster",
    )
    check_cli_version(venv, args.expect_version, res)
    check_single_alembic_head(venv, res)
    server = Server(venv, args.port, Path(args.out) / "server-fresh.log")
    server.start()
    try:
        if check_boot(server, args, res, fresh=True) is not None:
            check_spa_and_public_api(server, res)
    except Exception as exc:  # noqa: BLE001 - reported as a failed check
        res.fail(f"fresh: {type(exc).__name__}: {exc}")
    return finish(server, args, res, data_dir)


def cmd_seed(args: argparse.Namespace) -> int:
    res = Result()
    venv = Path(args.venv)
    data_dir = default_data_dir()
    # Seed the demo projects before /api/health answers, so the upgrade carries
    # them; by default they load in the background and a stop could cut them off.
    server = Server(venv, args.port, Path(args.out) / "server-seed.log", {"OE_DEMO_SEED_INLINE": "1"})
    server.start()
    try:
        health = server.wait_healthy(args.boot_timeout)
        if health is None:
            res.fail("seed: previous release never became healthy")
            return finish(server, args, res, data_dir)
        print("health (previous release): " + json.dumps(health, sort_keys=True), flush=True)
        base = server.base
        status, payload = http_json(
            "POST",
            f"{base}/api/v1/users/auth/register/",
            body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "full_name": "Release Gate"},
        )
        if not res.check(status == 201, f"seed: register answered {status}: {str(payload)[:400]}"):
            return finish(server, args, res, data_dir)
        token = login(server)
        status, me = http_json("GET", f"{base}/api/v1/users/me/", token=token)
        res.check(
            status == 200 and isinstance(me, dict) and me.get("role") == "admin",
            f"seed: first registered user is not admin: {status} {str(me)[:300]}",
        )
        status, project = http_json(
            "POST", f"{base}/api/v1/projects/", token=token, body={"name": PROJECT_NAME, "currency": "EUR"}
        )
        if not res.check(status == 201, f"seed: create project answered {status}: {str(project)[:400]}"):
            return finish(server, args, res, data_dir)
        status, boq = http_json(
            "POST", f"{base}/api/v1/boq/boqs/", token=token, body={"project_id": project["id"], "name": BOQ_NAME}
        )
        if not res.check(status == 201, f"seed: create BOQ answered {status}: {str(boq)[:400]}"):
            return finish(server, args, res, data_dir)
        for pos in POSITIONS:
            status, created = http_json(
                "POST", f"{base}/api/v1/boq/boqs/{boq['id']}/positions/", token=token, body={"boq_id": boq["id"], **pos}
            )
            res.check(status == 201, f"seed: add position {pos['ordinal']} answered {status}: {str(created)[:400]}")
        status, full = http_json("GET", f"{base}/api/v1/boq/boqs/{boq['id']}", token=token)
        if not res.check(
            status == 200 and isinstance(full, dict), f"seed: read BOQ answered {status}: {str(full)[:400]}"
        ):
            return finish(server, args, res, data_dir)
        expected_total = sum(Decimal(p["quantity"]) * Decimal(p["unit_rate"]) for p in POSITIONS)
        print(
            f"BOQ direct_cost_total {full.get('direct_cost_total')} (quantity x rate sums to {expected_total})",
            flush=True,
        )
        project_ids = list_project_ids(server, token)
        snapshot = {
            "version": health.get("version"),
            "project_id": project["id"],
            "boq_id": boq["id"],
            "project_ids": sorted(project_ids),
            "direct_cost_total": str(full.get("direct_cost_total")),
            "positions": [
                {k: str(p.get(k)) for k in ("ordinal", "quantity", "unit_rate", "total")}
                for p in full.get("positions", [])
            ],
        }
        Path(args.snapshot).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(
            f"snapshot: {len(project_ids)} projects visible, {len(snapshot['positions'])} positions -> {args.snapshot}",
            flush=True,
        )
        res.check(
            len(snapshot["positions"]) == len(POSITIONS),
            f"seed: BOQ holds {len(snapshot['positions'])} positions, expected {len(POSITIONS)}",
        )
    except Exception as exc:  # noqa: BLE001
        res.fail(f"seed: {type(exc).__name__}: {exc}")
    # The previous release's boot log is not judged: its defects are history.
    args.allow_log = [".*"]
    return finish(server, args, res, data_dir)


def cmd_verify(args: argparse.Namespace) -> int:
    res = Result()
    venv = Path(args.venv)
    data_dir = default_data_dir()
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    check_cli_version(venv, args.expect_version, res)
    check_single_alembic_head(venv, res)
    server = Server(venv, args.port, Path(args.out) / "server-upgraded.log")
    server.start()
    try:
        if check_boot(server, args, res, fresh=False) is not None:
            check_spa_and_public_api(server, res)
            token = login(server)
            status, boq = http_json("GET", f"{server.base}/api/v1/boq/boqs/{snapshot['boq_id']}", token=token)
            if res.check(
                status == 200 and isinstance(boq, dict), f"verify: read BOQ answered {status}: {str(boq)[:400]}"
            ):
                problems = compare_snapshot(snapshot, boq, list_project_ids(server, token))
                for problem in problems:
                    res.fail(f"verify: {problem}")
                if not problems:
                    print(
                        f"ok: {len(snapshot['positions'])} positions and {len(snapshot['project_ids'])} projects survived",
                        flush=True,
                    )
    except Exception as exc:  # noqa: BLE001
        res.fail(f"verify: {type(exc).__name__}: {exc}")
    return finish(server, args, res, data_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("install")
    p.add_argument("--venv", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--wheel-dir")
    g.add_argument("--spec")
    p.set_defaults(func=cmd_install)

    for name, func in (("fresh", cmd_fresh), ("seed", cmd_seed), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--venv", required=True)
        p.add_argument("--out", required=True, help="directory for logs")
        p.add_argument("--port", type=int, default=8080)
        p.add_argument("--boot-timeout", type=float, default=1800)
        p.add_argument(
            "--settle", type=float, default=20, help="seconds to let background startup work run before stopping"
        )
        p.add_argument("--allow-log", action="append", default=[], help="regex of a boot log line not to report")
        if name != "fresh":
            p.add_argument("--snapshot", required=True)
        if name != "seed":
            p.add_argument("--expect-version", required=True)
        else:
            p.set_defaults(expect_version=None)
        p.set_defaults(func=func)

    p = sub.add_parser("wheel-version")
    p.add_argument("wheel_dir")
    p.set_defaults(func=lambda a: print(wheel_version(sorted(Path(a.wheel_dir).glob("*.whl"))[0])) or 0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args, "out"):
        Path(args.out).mkdir(parents=True, exist_ok=True)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
