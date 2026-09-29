# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every GET route of a fresh install answers the demo admin without breaking.

A self-hosted user boots the platform with the demo seed on, signs in with the
"Try demo" tile and clicks around. Each screen reads one or more GET routes, and
a route that answers 500, or 422 to a call the frontend would make, is a dead
page. Module tests exercise routes one module at a time against fixtures they
build themselves, so a route that breaks only on the data the demo seeder
writes, or only once every module is mounted together, is invisible to them.

This test boots the application exactly as a user gets it, runs the full
lifespan (every module loaded, the showcase and flagship demo projects seeded),
signs in through ``/auth/demo-login/`` the way the login page does, and then
calls every mounted GET route:

* routes without path parameters directly;
* ``project_id`` and its spellings with a seeded demo project;
* any other id with a value taken from the matching list route, resolved left
  to right so nested routes get a parent id first. A parameter nothing can
  resolve is skipped and the reason is written into the report;
* every route that declares ``project_id``, ``limit`` or ``offset`` a second
  time with the values the frontend sends.

A failure is a 5xx, a 422 on a call whose every parameter was resolved, a body
that does not validate against the route's ``response_model``, or an answer
slower than :data:`_SLOW_SECONDS`. Every call, failed or not, lands in a report
(JSON and Markdown) written to ``OE_API_SMOKE_REPORT_DIR``, which CI uploads as
an artifact.

The boot is the expensive part (the full demo seed), so the test is gated twice:
it lives in the PG lane and additionally needs ``OE_API_SMOKE=1``. The
dedicated ``api-smoke`` job in ``ci-postgres.yml`` sets both, together with
``SEED_DEMO=true`` and ``OE_TEST_FAST_STARTUP=0``, which the suite-wide
conftest otherwise defaults the other way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

#: A route slower than this is reported as failing. The frontend's own request
#: timeout is longer, but a page waiting ten seconds for one read is broken.
_SLOW_SECONDS = 10.0

#: Hard ceiling per call, so a streaming route cannot hang the run. The test
#: transport buffers the whole body, so an event stream always runs to it.
_HARD_TIMEOUT_SECONDS = 15.0

_DEMO_ADMIN = "demo@openconstructionerp.com"

#: Query values the frontend sends on list screens.
_LIST_LIMIT = 50
_LIST_OFFSET = 0

#: Parameter names that carry a project id.
_PROJECT_PARAMS = frozenset({"project_id", "projectId", "pid"})

#: Names too generic to look up in another module's list route.
_GENERIC_PARAMS = frozenset({"id", "item_id", "entry_id", "record_id", "key", "name", "slug", "code", "uid"})

#: Routes that are exempt, with the reason. A route belongs here only when the
#: failure is not a defect: it streams, it needs an upstream service a fresh
#: install does not have, or it answers a question that has no data on a fresh
#: install by design. Keyed by the route's path template.
ALLOWLIST: dict[str, str] = {}

#: GET routes that change state on the server. Calling one mid-walk would sign
#: the admin out, stop the app or purge the demo data every later call reads.
_STATEFUL_WORDS = re.compile(r"logout|shutdown|purge|reset|revoke|sign-out|signout", re.IGNORECASE)

_PARAM_RE = re.compile(r"{([^}:]+)(?::[^}]+)?}")


@dataclass
class Call:
    module: str
    route: str
    url: str
    variant: str
    status: int | None = None
    seconds: float = 0.0
    outcome: str = "ok"
    error: str = ""
    allowlisted: str = ""


@dataclass
class Report:
    project_id: str = ""
    boot_seconds: float = 0.0
    routes: int = 0
    calls: list[Call] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


class _ErrorCapture(logging.Handler):
    """Keep the last logged exception, so a 500 carries its cause into the report."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.last: str = ""

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            frames = traceback.extract_tb(exc.__traceback__)
            app_frames = [f for f in frames if "/app/" in f.filename.replace("\\", "/")]
            where = app_frames[-1] if app_frames else (frames[-1] if frames else None)
            loc = f" at {Path(where.filename).name}:{where.lineno}" if where else ""
            self.last = f"{type(exc).__name__}: {str(exc).splitlines()[0][:300] if str(exc) else ''}{loc}"


def _module_of(route: Any) -> str:
    mod = getattr(route.endpoint, "__module__", "") or ""
    parts = mod.split(".")
    if len(parts) >= 3 and parts[0] == "app" and parts[1] == "modules":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "app":
        return ".".join(parts[1:3])
    return mod or "?"


def _params(template: str) -> list[str]:
    return _PARAM_RE.findall(template)


def _fill(template: str, values: dict[str, str]) -> str:
    return _PARAM_RE.sub(lambda m: values[m.group(1)], template)


def _items(body: Any) -> list[dict[str, Any]]:
    """The rows of a list answer, whatever envelope the route wraps them in."""
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if isinstance(body, dict):
        for key in ("items", "results", "data", "rows", "records", "entries"):
            value = body.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
        for value in body.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return []


def _pick(row: dict[str, Any], param: str) -> str | None:
    for key in (param, "id") if param.endswith("_id") or param == "id" else (param,):
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return None


def _query_fields(route: Any) -> list[Any]:
    from fastapi.dependencies.utils import get_flat_dependant

    return list(get_flat_dependant(route.dependant).query_params)


def _is_required(field_: Any) -> bool:
    required = getattr(field_, "required", None)
    if isinstance(required, bool):
        return required
    return bool(field_.field_info.is_required())


def _alias(field_: Any) -> str:
    return getattr(field_, "alias", None) or field_.name


class _Walker:
    def __init__(self, client: Any, routes: list[Any], project_id: str, capture: _ErrorCapture) -> None:
        self.client = client
        self.routes = routes
        self.project_id = project_id
        self.capture = capture
        self.headers: dict[str, str] = {}
        self.by_template = {r.path: r for r in routes}
        # param name -> list templates ending in "/{param}"'s parent, learned from all routes.
        self.list_for: dict[str, list[str]] = {}
        for r in routes:
            for p in _params(r.path):
                parent = r.path.split("{" + p)[0].rstrip("/")
                if parent in self.by_template or parent + "/" in self.by_template:
                    self.list_for.setdefault(p, [])
                    if parent not in self.list_for[p]:
                        self.list_for[p].append(parent)
        self._list_cache: dict[str, list[dict[str, Any]]] = {}

    async def login(self) -> bool:
        resp = await self.client.post("/api/v1/users/auth/demo-login/", json={"email": _DEMO_ADMIN})
        if resp.status_code != 200:
            return False
        self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        return True

    async def _session_alive(self) -> bool:
        probe = await self.client.get("/api/v1/users/me/", headers=self.headers)
        return probe.status_code == 200

    async def get(self, url: str, params: dict[str, Any] | None = None) -> tuple[Any, float, str]:
        self.capture.last = ""
        started = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                self.client.get(url, params=params, headers=self.headers),
                timeout=_HARD_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return None, time.perf_counter() - started, "hard timeout"
        except Exception as exc:  # noqa: BLE001 - the report records it
            return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"[:400]
        elapsed = time.perf_counter() - started
        # A 401 is either this route refusing a valid session (OAuth, API key and
        # webhook routes do) or the session itself having ended. Only the second
        # is worth a fresh sign-in, and signing in on every such 401 would run
        # into the login rate limit.
        if resp.status_code == 401 and not await self._session_alive() and await self.login():
            resp = await self.client.get(url, params=params, headers=self.headers)
        return resp, elapsed, ""

    def _list_route(self, template: str) -> Any:
        return self.by_template.get(template) or self.by_template.get(template + "/")

    async def _list_rows(self, template: str, values: dict[str, str], depth: int) -> list[dict[str, Any]]:
        route = self._list_route(template)
        if route is None:
            return []
        resolved = await self.resolve(route, values, depth + 1)
        if resolved is None:
            return []
        url = _fill(route.path, resolved)
        query = self.query_for(route, resolved, list_call=True)
        if query is None:
            return []
        cache_key = url + "?" + json.dumps(query, sort_keys=True)
        if cache_key not in self._list_cache:
            resp, _elapsed, _err = await self.get(url, query)
            rows: list[dict[str, Any]] = []
            if resp is not None and resp.status_code == 200:
                try:
                    rows = _items(resp.json())
                except ValueError:
                    rows = []
            self._list_cache[cache_key] = rows
        return self._list_cache[cache_key]

    async def resolve(self, route: Any, known: dict[str, str], depth: int = 0) -> dict[str, str] | None:
        """Values for every path parameter of ``route``, or None when one cannot be found."""
        if depth > 4:
            return None
        values = dict(known)
        for param in _params(route.path):
            if param in values:
                continue
            if param in _PROJECT_PARAMS:
                values[param] = self.project_id
                continue
            prefix = route.path.split("{" + param)[0].rstrip("/")
            candidates = [prefix]
            if param not in _GENERIC_PARAMS:
                candidates += [c for c in self.list_for.get(param, []) if c != prefix]
            found = None
            for candidate in candidates:
                sub = {k: v for k, v in values.items() if "{" + k in candidate}
                for row in await self._list_rows(candidate, sub, depth):
                    found = _pick(row, param)
                    if found:
                        break
                if found:
                    break
            if not found:
                return None
            values[param] = found
        return values

    def query_for(self, route: Any, values: dict[str, str], *, list_call: bool) -> dict[str, Any] | None:
        """The query string for a well-formed call, or None when a required value is unknown."""
        query: dict[str, Any] = {}
        for f in _query_fields(route):
            name = _alias(f)
            if name in _PROJECT_PARAMS or f.name in _PROJECT_PARAMS:
                if _is_required(f) or list_call:
                    query[name] = self.project_id
            elif name in values:
                query[name] = values[name]
            elif _is_required(f):
                return None
        return query

    def unresolved_required(self, route: Any, values: dict[str, str]) -> list[str]:
        return [
            _alias(f)
            for f in _query_fields(route)
            if _is_required(f) and _alias(f) not in _PROJECT_PARAMS and _alias(f) not in values
        ]


def _validate(route: Any, resp: Any) -> str:
    """Empty when the body matches ``response_model``, else the first error."""
    model = getattr(route, "response_model", None)
    if model is None or resp.status_code != 200:
        return ""
    if "json" not in resp.headers.get("content-type", ""):
        return ""
    from pydantic import TypeAdapter, ValidationError

    try:
        TypeAdapter(model).validate_json(resp.content)
    except ValidationError as exc:
        first = exc.errors()[0]
        return f"response_model: {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"[:300]
    except Exception as exc:  # noqa: BLE001 - an unbuildable adapter is itself a finding
        return f"response_model adapter: {type(exc).__name__}: {exc}"[:300]
    return ""


def _classify(call: Call, resp: Any, err: str, fully_resolved: bool, route: Any) -> None:
    if resp is None:
        call.outcome = "timeout" if "timeout" in err else "exception"
        call.error = err
        return
    call.status = resp.status_code
    if call.seconds > _SLOW_SECONDS:
        call.outcome = "slow"
        call.error = f"{call.seconds:.1f}s"
    if resp.status_code >= 500:
        call.outcome = "5xx"
        call.error = call.error or ""
    elif resp.status_code == 422 and fully_resolved:
        call.outcome = "422"
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text
        call.error = json.dumps(detail, default=str)[:300]
    elif resp.status_code == 200:
        problem = _validate(route, resp)
        if problem:
            call.outcome = "schema"
            call.error = problem
    elif call.outcome == "ok" and resp.status_code >= 400:
        call.outcome = f"info-{resp.status_code}"
        try:
            call.error = json.dumps(resp.json().get("detail"), default=str)[:200]
        except (ValueError, AttributeError):
            call.error = resp.text[:200]


_FAILING = {"5xx", "422", "schema", "slow", "timeout", "exception"}


def _write_report(report: Report, directory: Path) -> tuple[Path, list[Call]]:
    """Write the JSON and Markdown report. Called during the walk too, so a run
    killed by a timeout still leaves the calls it made."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "api_smoke.json").write_text(json.dumps(asdict(report), indent=1, default=str), encoding="utf-8")
    failing = [c for c in report.calls if c.outcome in _FAILING and not c.allowlisted]
    lines = [
        "# API smoke on a fresh install",
        "",
        f"Demo project: `{report.project_id}`. Boot {report.boot_seconds:.0f}s. "
        f"GET routes {report.routes}, calls {len(report.calls)}, failing {len(failing)}, "
        f"skipped {len(report.skipped)}.",
        "",
        "## Failing",
        "",
        "| module | route | variant | status | outcome | error |",
        "|---|---|---|---|---|---|",
    ]
    for c in sorted(failing, key=lambda c: (c.module, c.route)):
        err = c.error.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c.module} | `{c.route}` | {c.variant} | {c.status} | {c.outcome} | {err} |")
    lines += ["", "## Other non-200 answers", "", "| module | route | status | detail |", "|---|---|---|---|"]
    for c in sorted(report.calls, key=lambda c: (c.module, c.route)):
        if c.outcome.startswith("info-"):
            err = c.error.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {c.module} | `{c.route}` | {c.status} | {err} |")
    lines += ["", "## Skipped", "", "| module | route | reason |", "|---|---|---|"]
    for s in sorted(report.skipped, key=lambda s: (s["module"], s["route"])):
        lines.append(f"| {s['module']} | `{s['route']}` | {s['reason']} |")
    (directory / "api_smoke.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory / "api_smoke.md", failing


@pytest.mark.timeout(3600)
async def test_every_get_route_answers_the_demo_admin_on_a_fresh_install() -> None:
    if os.environ.get("OE_API_SMOKE", "") != "1":
        pytest.skip("full-boot API smoke: set OE_API_SMOKE=1 (runs in the api-smoke CI job)")
    if os.environ.get("SEED_DEMO", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("the smoke needs SEED_DEMO=true, the value a fresh install boots with")

    from fastapi.routing import APIRoute
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    report = Report()
    capture = _ErrorCapture()
    logging.getLogger().addHandler(capture)
    report_dir = Path(os.environ.get("OE_API_SMOKE_REPORT_DIR") or "api-smoke-report")
    app = create_app()
    started = time.perf_counter()
    try:
        async with app.router.lifespan_context(app):
            report.boot_seconds = time.perf_counter() - started
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://localhost", timeout=None) as client:
                routes = [r for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods]
                report.routes = len(routes)
                walker = _Walker(client, routes, "", capture)
                assert await walker.login(), "the demo admin could not sign in through /auth/demo-login/"

                projects, _elapsed, _err = await walker.get("/api/v1/projects/")
                assert projects is not None and projects.status_code == 200, "the project list itself failed"
                rows = _items(projects.json())
                assert rows, "a fresh install with the demo seed on has no project for the demo admin"
                walker.project_id = report.project_id = str(rows[0]["id"])

                # A route mounted with and without the trailing slash is one
                # endpoint; calling both doubles the run and the report.
                unique: dict[tuple[Any, str], Any] = {}
                for route in sorted(routes, key=lambda r: r.path):
                    unique.setdefault((route.endpoint, route.path.rstrip("/")), route)
                for index, route in enumerate(unique.values()):
                    if index % 100 == 0:
                        _write_report(report, report_dir)
                    module = _module_of(route)
                    if _STATEFUL_WORDS.search(route.path):
                        report.skipped.append(
                            {"module": module, "route": route.path, "reason": "changes server state on GET"}
                        )
                        continue
                    values = await walker.resolve(route, {})
                    if values is None:
                        missing = [p for p in _params(route.path) if p not in _PROJECT_PARAMS]
                        report.skipped.append(
                            {"module": module, "route": route.path, "reason": f"no list value for {missing}"}
                        )
                        continue
                    missing_q = walker.unresolved_required(route, values)
                    if missing_q:
                        report.skipped.append(
                            {"module": module, "route": route.path, "reason": f"required query {missing_q}"}
                        )
                        continue
                    url = _fill(route.path, values)
                    variants: list[tuple[str, dict[str, Any]]] = [
                        ("plain", walker.query_for(route, values, list_call=False) or {})
                    ]
                    declared = {_alias(f) for f in _query_fields(route)}
                    common = {}
                    if declared & _PROJECT_PARAMS:
                        common[next(iter(declared & _PROJECT_PARAMS))] = walker.project_id
                    if "limit" in declared:
                        common["limit"] = _LIST_LIMIT
                    if "offset" in declared:
                        common["offset"] = _LIST_OFFSET
                    if common:
                        variants.append(("list", {**variants[0][1], **common}))
                    for variant, query in variants:
                        resp, elapsed, err = await walker.get(url, query)
                        call = Call(module=module, route=route.path, url=url, variant=variant, seconds=elapsed)
                        _classify(call, resp, err, True, route)
                        if call.outcome == "5xx" and capture.last:
                            call.error = capture.last
                        if call.outcome in _FAILING and route.path in ALLOWLIST:
                            call.allowlisted = ALLOWLIST[route.path]
                        report.calls.append(call)
    finally:
        logging.getLogger().removeHandler(capture)
        md, failing = _write_report(report, report_dir)

    print(md.read_text(encoding="utf-8")[:20000])  # noqa: T201 - the job log shows the table
    # An exemption for a route that was renamed or removed hides nothing and
    # would silently cover whatever takes its path next.
    stale = sorted(set(ALLOWLIST) - {c.route for c in report.calls})
    assert not stale, f"allowlisted routes this install never called: {stale}"
    assert not failing, f"{len(failing)} GET calls failed on a fresh install; see {md}"
