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
  to right so nested routes get a parent id first, and only a value the
  parameter's declared type accepts. A parameter nothing can resolve is skipped
  and the reason is written into the report;
* a route that needs one of several query parameters with the one
  :data:`_EITHER_OR` names;
* every route that declares ``project_id``, ``limit`` or ``offset`` a second
  time with the values the frontend sends, clamped to the route's own bounds.

The routes come from :func:`app.core.module_loader.served_routes`, one URL per
endpoint. ``app.routes`` is not enough: since FastAPI 0.141 an include adds one
marker instead of copying the router's routes, and this test walked the 13
routes the application declares itself, on every run, while reporting green.
A floor (served GET paths >= GET paths in the OpenAPI document) now fails a
walk that shrinks like that again, and the counts are printed into the log.
The same table is checked for routes an earlier route answers in their place
(``tests/_route_shadowing.py``).

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

#: Routes that are exempt, with the outcomes they are excused for and the
#: reason. A route belongs here only when the failure is not a defect: it
#: streams, it needs an upstream service a fresh install does not have, or it
#: refuses on purpose for data the demo seed does not carry. Keyed by the full
#: path template. An entry excuses only the outcomes it names, so the same route
#: answering 500 still fails, and every excused call is listed in the report.
ALLOWLIST: dict[str, tuple[frozenset[str], str]] = {
    "/api/v1/boq/boqs/{boq_id}/export/gaeb-x31/": (
        frozenset({"422"}),
        "X31 carries measured quantities; the demo bills have no measurement sheet, and the route says so",
    ),
    "/api/v1/finance/invoices/{invoice_id}/einvoice": (
        frozenset({"422"}),
        "the demo contacts lack the buyer name, country and city EN 16931 requires; the route lists what is missing",
    ),
    "/api/v1/bim-hub/models/{model_id}/download/": (
        frozenset({"timeout", "slow"}),
        "streams the model file; the test transport buffers the whole body, so a large model reaches the ceiling",
    ),
}

#: Routes that need one of several query parameters, none of them required on
#: its own, so the signature cannot tell the walker. Each entry names the
#: parameter the walker sends, the list route its value comes from (None: the
#: demo project) and the alternatives the route accepts. Called bare, these
#: answer 422 with a plain-text detail.
_EITHER_OR: dict[str, tuple[str, str | None, str]] = {
    "/api/v1/documents/bim-links/": ("document_id", "/api/v1/documents/", "element_id or document_id"),
    "/api/v1/property-dev/instalments/": (
        "schedule_id",
        "/api/v1/property-dev/payment-schedules/",
        "schedule_id or sales_contract_id",
    ),
    "/api/v1/property-dev/payment-schedules/": (
        "development_id",
        "/api/v1/property-dev/developments/",
        "sales_contract_id or development_id",
    ),
    "/api/v1/property-dev/sales-contracts/": (
        "development_id",
        "/api/v1/property-dev/developments/",
        "plot_id, development_id or reservation_id",
    ),
    "/api/v1/schedule/critical-path/": ("project_id", None, "project_id or schedule_id"),
}

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
    walk_seconds: float = 0.0
    routes: int = 0
    served_get_paths: int = 0
    openapi_get_paths: int = 0
    aliases: int = 0
    calls: list[Call] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    shadowed: list[str] = field(default_factory=list)


class _Served:
    """A served route under the full URL it answers on.

    ``route.path`` is the path the route was declared with, without the prefixes
    of the includes above it; the URL is known only to the include tree
    (:func:`app.core.module_loader.served_routes`). Everything else is the
    route's own.
    """

    def __init__(self, path: str, route: Any) -> None:
        self.path = path
        self.route = route

    def __getattr__(self, name: str) -> Any:
        return getattr(self.route, name)


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


def _accepts(field_: Any | None, value: str) -> bool:
    """Whether ``value`` passes the parameter's declared type.

    A row can carry the parameter's name with another meaning: an EPD row's
    ``epd_id`` is the business code ("EPD-CONCRETE-001") while the route's
    ``{epd_id}`` is the row's UUID. Without this check the walker sent the code
    and reported the route's correct 422 as a failure.
    """
    annotation = getattr(getattr(field_, "field_info", None), "annotation", None)
    if annotation is None:
        return True
    from pydantic import TypeAdapter, ValidationError

    try:
        TypeAdapter(annotation).validate_python(value)
    except ValidationError:
        return False
    except Exception:  # noqa: BLE001 - an annotation no adapter takes decides nothing
        return True
    return True


def _pick(row: dict[str, Any], param: str, field_: Any | None = None) -> str | None:
    for key in (param, "id") if param.endswith("_id") or param == "id" else (param,):
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value) and _accepts(field_, str(value)):
            return str(value)
    return None


def _dependant_fields(route: Any, kind: str) -> list[Any]:
    """Every ``kind`` parameter of the route, including those its dependencies declare.

    Walked by hand over ``Dependant.<kind>`` and ``Dependant.dependencies``
    rather than through FastAPI's flattening helper, which is private and has
    changed shape between releases.
    """
    fields: dict[str, Any] = {}
    stack = [route.dependant]
    seen: set[int] = set()
    while stack:
        dependant = stack.pop()
        if id(dependant) in seen:
            continue
        seen.add(id(dependant))
        for f in getattr(dependant, kind, None) or []:
            fields.setdefault(_alias(f), f)
        stack.extend(getattr(dependant, "dependencies", None) or [])
    return list(fields.values())


def _query_fields(route: Any) -> list[Any]:
    return _dependant_fields(route, "query_params")


def _path_field(route: Any, param: str) -> Any | None:
    return next((f for f in _dependant_fields(route, "path_params") if f.name == param), None)


def _clamp(field_: Any, value: int) -> int:
    """``value`` moved inside the parameter's own ``ge``/``gt``/``le``/``lt`` bounds.

    The frontend's list screens send ``limit=50``; a route capped lower (a
    "similar items" panel takes 20) answers that with a correct 422.
    """
    for bound in getattr(field_.field_info, "metadata", None) or []:
        if getattr(bound, "le", None) is not None:
            value = min(value, bound.le)
        if getattr(bound, "lt", None) is not None:
            value = min(value, bound.lt - 1)
        if getattr(bound, "ge", None) is not None:
            value = max(value, bound.ge)
        if getattr(bound, "gt", None) is not None:
            value = max(value, bound.gt + 1)
    return value


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
        if resolved is not None:
            resolved = await self.either_or(route, resolved, depth + 1)
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
            field_ = _path_field(route, param)
            for candidate in candidates:
                sub = {k: v for k, v in values.items() if "{" + k in candidate}
                for row in await self._list_rows(candidate, sub, depth):
                    found = _pick(row, param, field_)
                    if found:
                        break
                if found:
                    break
            if not found:
                return None
            values[param] = found
        return values

    async def either_or(self, route: Any, values: dict[str, str], depth: int = 0) -> dict[str, str] | None:
        """``values`` plus the parameter :data:`_EITHER_OR` names for ``route``.

        None when that parameter has no value: the source list is empty or
        answers nothing the parameter's type accepts.
        """
        entry = _EITHER_OR.get(route.path)
        if entry is None:
            return values
        param, source, _alternatives = entry
        if param in values:
            return values
        if source is None:
            return {**values, param: self.project_id}
        field_ = next((f for f in _query_fields(route) if _alias(f) == param), None)
        for row in await self._list_rows(source, {}, depth):
            found = _pick(row, param, field_)
            if found:
                return {**values, param: found}
        return None

    def query_for(self, route: Any, values: dict[str, str], *, list_call: bool) -> dict[str, Any] | None:
        """The query string for a well-formed call, or None when a required value is unknown."""
        query: dict[str, Any] = {}
        for f in _query_fields(route):
            name = _alias(f)
            if name in _PROJECT_PARAMS or f.name in _PROJECT_PARAMS:
                if _is_required(f) or list_call or name in values:
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


def _excuse(path: str, outcome: str) -> str:
    """The allowlist reason for ``outcome`` on ``path``, or empty."""
    outcomes, reason = ALLOWLIST.get(path, (frozenset(), ""))
    return reason if outcome in outcomes else ""


def _counts(report: Report, failing: list[Call]) -> str:
    allowlisted = sum(1 for c in report.calls if c.allowlisted)
    return (
        f"GET routes {report.routes} (served GET paths {report.served_get_paths}, OpenAPI GET paths "
        f"{report.openapi_get_paths}, aliases folded {report.aliases}), calls {len(report.calls)}, "
        f"failing {len(failing)}, skipped {len(report.skipped)}, allowlisted {allowlisted}, "
        f"shadowed {len(report.shadowed)}"
    )


def _write_report(report: Report, directory: Path) -> tuple[Path, list[Call]]:
    """Write the JSON and Markdown report. Called during the walk too, so a run
    killed by a timeout still leaves the calls it made."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "api_smoke.json").write_text(json.dumps(asdict(report), indent=1, default=str), encoding="utf-8")
    failing = [c for c in report.calls if c.outcome in _FAILING and not c.allowlisted]
    lines = [
        "# API smoke on a fresh install",
        "",
        f"Demo project: `{report.project_id}`. Boot {report.boot_seconds:.0f}s, walk {report.walk_seconds:.0f}s. "
        f"{_counts(report, failing)}.",
        "",
        "## Failing",
        "",
        "| module | route | variant | status | outcome | error |",
        "|---|---|---|---|---|---|",
    ]
    for c in sorted(failing, key=lambda c: (c.module, c.route)):
        err = c.error.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c.module} | `{c.route}` | {c.variant} | {c.status} | {c.outcome} | {err} |")
    lines += ["", "## Shadowed (an earlier route answers these URLs)", ""]
    lines += [f"- `{entry}`" for entry in report.shadowed] or ["None."]
    lines += ["", "## Allowlisted", "", "| module | route | outcome | reason |", "|---|---|---|---|"]
    for c in sorted(report.calls, key=lambda c: (c.module, c.route)):
        if c.allowlisted:
            lines.append(f"| {c.module} | `{c.route}` | {c.outcome} | {c.allowlisted} |")
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

    from app.core.module_loader import served_routes
    from app.main import create_app
    from tests._route_shadowing import shadowed_routes

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
                served = list(served_routes(app))
                gets = [(path, r) for path, r in served if isinstance(r, APIRoute) and "GET" in r.methods]
                # One URL per endpoint: the legacy underscore mirror and a
                # trailing-slash twin are the same function a second time.
                first_url: dict[Any, _Served] = {}
                for path, r in gets:
                    first_url.setdefault(r.endpoint, _Served(path, r))
                routes = list(first_url.values())
                report.routes = len(routes)
                report.served_get_paths = len({path for path, _r in gets})
                report.aliases = len(gets) - len(routes)
                report.openapi_get_paths = sum(1 for ops in app.openapi()["paths"].values() if "get" in ops)
                report.shadowed = [f"{','.join(s.methods)} {s.hidden} <- {s.by}" for s in shadowed_routes(served)]
                print(f"API smoke population: {_counts(report, [])}", flush=True)  # noqa: T201
                # A walk that shrinks fails here, before it can pass on nothing.
                assert report.openapi_get_paths > 100, (
                    f"the OpenAPI document lists {report.openapi_get_paths} GET paths; modules did not mount"
                )
                assert report.served_get_paths >= report.openapi_get_paths, (
                    f"served_routes found {report.served_get_paths} GET paths, the OpenAPI document "
                    f"{report.openapi_get_paths}: the route walk no longer sees every module"
                )
                walk_started = time.perf_counter()
                walker = _Walker(client, routes, "", capture)
                assert await walker.login(), "the demo admin could not sign in through /auth/demo-login/"

                # The demo projects seed in the background once the server is up
                # (the ``demo_data_seed`` process), so the first sign-in can
                # beat them. Poll the list the walk needs, bounded.
                seed_deadline = time.perf_counter() + 600
                while True:
                    projects, _elapsed, _err = await walker.get("/api/v1/projects/")
                    assert projects is not None and projects.status_code == 200, "the project list itself failed"
                    rows = _items(projects.json())
                    if rows or time.perf_counter() > seed_deadline:
                        break
                    await asyncio.sleep(2)
                assert rows, "a fresh install with the demo seed on has no project for the demo admin"
                walker.project_id = report.project_id = str(rows[0]["id"])

                for index, route in enumerate(sorted(routes, key=lambda r: r.path)):
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
                    with_choice = await walker.either_or(route, values)
                    if with_choice is None:
                        param, source, _alternatives = _EITHER_OR[route.path]
                        report.skipped.append(
                            {"module": module, "route": route.path, "reason": f"no {param} from {source}"}
                        )
                        continue
                    values = with_choice
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
                    declared = {_alias(f): f for f in _query_fields(route)}
                    common = {}
                    if declared.keys() & _PROJECT_PARAMS:
                        common[next(iter(declared.keys() & _PROJECT_PARAMS))] = walker.project_id
                    if "limit" in declared:
                        common["limit"] = _clamp(declared["limit"], _LIST_LIMIT)
                    if "offset" in declared:
                        common["offset"] = _clamp(declared["offset"], _LIST_OFFSET)
                    if common:
                        variants.append(("list", {**variants[0][1], **common}))
                    for variant, query in variants:
                        resp, elapsed, err = await walker.get(url, query)
                        call = Call(module=module, route=route.path, url=url, variant=variant, seconds=elapsed)
                        _classify(call, resp, err, True, route)
                        if call.outcome == "5xx" and capture.last:
                            call.error = capture.last
                        if call.outcome in _FAILING:
                            call.allowlisted = _excuse(route.path, call.outcome)
                        report.calls.append(call)
                report.walk_seconds = time.perf_counter() - walk_started
    finally:
        logging.getLogger().removeHandler(capture)
        md, failing = _write_report(report, report_dir)

    print(f"API smoke: {_counts(report, failing)}", flush=True)  # noqa: T201
    print(md.read_text(encoding="utf-8")[:20000])  # noqa: T201 - the job log shows the table
    # An exemption for a route that was renamed or removed hides nothing and
    # would silently cover whatever takes its path next.
    stale = sorted(set(ALLOWLIST) - {c.route for c in report.calls})
    assert not stale, f"allowlisted routes this install never called: {stale}"
    walked = {r.path for r in routes}
    stale_choice = sorted(set(_EITHER_OR) - walked)
    assert not stale_choice, f"either-or entries for routes this install does not serve: {stale_choice}"
    assert not report.shadowed, "routes answered by an earlier route:\n" + "\n".join(report.shadowed)
    assert not failing, f"{len(failing)} GET calls failed on a fresh install; see {md}"
