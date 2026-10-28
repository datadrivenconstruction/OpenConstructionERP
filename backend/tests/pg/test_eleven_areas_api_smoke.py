# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠API stability of the eleven-areas-framework pack on a fresh install, over HTTP.

One install, two demo projects, then the checks a user would feel:

* every GET route of the framework modules answers both demo projects without a
  5xx, with a body that validates against its response model, and the modules
  that ship demo data answer with some of it;
* every export route returns a real PDF or XLSX with the right content type;
* a viewer is refused every write, and a manager of another workspace cannot
  read a project they do not belong to;
* the install logged nothing above INFO and a second install adds no rows.

Each test collects every problem it finds and fails once with the whole list, so
one broken route does not hide the next. The run is gated like the other
full-boot lanes: ``OE_API_SMOKE=1``.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from tests.pg.elf_qa_fixtures import DEMO_IDS, PACK_SLUG, TARGET_MODULES, World, boot_world, install_pack
from tests.pg.test_every_get_route_answers_on_a_fresh_install import (
    _FAILING,
    _STATEFUL_WORDS,
    Call,
    _alias,
    _classify,
    _ErrorCapture,
    _fill,
    _items,
    _module_of,
    _params,
    _query_fields,
    _Served,
    _Walker,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("OE_API_SMOKE", "") != "1", reason="full-boot lane: set OE_API_SMOKE=1"),
]

#: Modules whose pack demo files put rows on both projects.
DEMO_DATA_MODULES = (
    "commitment_release",
    "delivery_model",
    "design_management",
    "permits",
    "plant_register",
    "procurement_concept",
    "quality_concept",
    "site_logistics",
    "staffing",
    "stakeholders",
    "transmittals",
    "project_governance",
)

REPORT_DIR = Path(os.environ.get("OE_API_SMOKE_REPORT_DIR") or "api-smoke-report") / "elf_qa"

_PDF = "application/pdf"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest_asyncio.fixture(scope="module")
async def world(pg_async_url, tmp_path_factory):
    async for w in boot_world(pg_async_url, str(tmp_path_factory.mktemp("elf_qa_data"))):
        yield w


def _served(world: World) -> list[_Served]:
    from fastapi.routing import APIRoute

    from app.core.module_loader import served_routes

    out: dict[Any, _Served] = {}
    for path, r in served_routes(world.application):
        if isinstance(r, APIRoute) and _module_of(r) in TARGET_MODULES:
            out.setdefault((r.endpoint, tuple(sorted(r.methods))), _Served(path, r))
    return list(out.values())


def _nonempty(body: Any) -> bool:
    if isinstance(body, list):
        return bool(body)
    if isinstance(body, dict):
        return bool(_items(body)) or any(v not in (None, "", [], {}, 0, False) for v in body.values())
    return body not in (None, "")


def _dump(name: str, data: Any) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{name}.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


def _fail_message(title: str, problems: list[str]) -> str:
    return f"{title}: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems[:80])


# ── Install ─────────────────────────────────────────────────────────────────


async def test_the_pack_installs_both_demo_projects(world: World) -> None:
    steps = {s["step"]: s for s in world.install_done["steps"]}
    errored = {k: v for k, v in steps.items() if v["status"] == "error"}
    assert not errored, f"steps in error: {errored}"
    assert world.install_done["ok"], world.install_done
    assert set(world.projects) == set(DEMO_IDS), f"demo projects found: {sorted(world.projects)}"
    assert not steps["demos"]["detail"].get("errors"), steps["demos"]["detail"]


async def test_the_install_logged_nothing_above_info(world: World) -> None:
    """Rule 22: a clean install is silent at WARNING and above."""
    # The embedding model is an optional extra the CI runner does not install; the vector layer says so once.
    # The slow-query monitor times the runner, not the install: a busy CI host crosses its threshold at random.
    logged = [
        r
        for r in world.install_logs
        if "sentence-transformers not installed" not in r and not r.startswith("WARNING slow_queries:")
    ]
    assert not logged, "the pack install logged:\n" + "\n".join(logged[:60])


# ── 1. Every GET route ──────────────────────────────────────────────────────


@pytest.mark.timeout(1800)
async def test_every_get_route_of_the_framework_modules_answers_both_demo_projects(world: World) -> None:
    routes = [s for s in _served(world) if "GET" in s.methods and not _STATEFUL_WORDS.search(s.path)]
    assert len(routes) > 150, f"only {len(routes)} GET routes of the framework modules are mounted"
    capture = _ErrorCapture()
    import logging

    logging.getLogger().addHandler(capture)
    problems: list[str] = []
    nonempty: dict[str, set[str]] = {m: set() for m in DEMO_DATA_MODULES}
    answered: dict[str, int] = {}
    skipped: list[str] = []
    try:
        for demo_id, project_id in sorted(world.projects.items()):
            walker = _Walker(world.client, routes, str(project_id), capture)
            walker.headers = world.admin
            for route in sorted(routes, key=lambda r: r.path):
                module = _module_of(route)
                if "export" in route.path:
                    continue
                values = await walker.resolve(route, {})
                if values is None:
                    skipped.append(f"{demo_id} {route.path}")
                    continue
                if walker.unresolved_required(route, values):
                    skipped.append(f"{demo_id} {route.path} (required query)")
                    continue
                url = _fill(route.path, values)
                query = walker.query_for(route, values, list_call=True) or {}
                resp, elapsed, err = await walker.get(url, query)
                call = Call(module=module, route=route.path, url=url, variant=demo_id, seconds=elapsed)
                _classify(call, resp, err, True, route)
                if call.outcome == "5xx" and capture.last:
                    call.error = capture.last
                if call.outcome in _FAILING:
                    problems.append(
                        f"{demo_id} {module} GET {route.path} -> {call.status} {call.outcome}: {call.error}"
                    )
                    continue
                answered[module] = answered.get(module, 0) + 1
                if resp is not None and resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                    try:
                        body = resp.json()
                    except ValueError:
                        continue
                    if module in nonempty and _nonempty(body):
                        nonempty[module].add(demo_id)
    finally:
        logging.getLogger().removeHandler(capture)
    _dump("get_walk", {"answered": answered, "skipped": skipped, "problems": problems})
    print(f"[elf-qa] GET answered per module: {answered}; skipped {len(skipped)}")  # noqa: T201
    for module in DEMO_DATA_MODULES:
        missing = sorted(set(world.projects) - nonempty[module])
        if missing:
            problems.append(f"{module}: no non-empty GET answer for demo project(s) {missing}")
    for module in TARGET_MODULES:
        if not answered.get(module):
            problems.append(f"{module}: not one GET route could be called")
    assert not problems, _fail_message("GET walk", problems)


# ── 2. Exports ──────────────────────────────────────────────────────────────


def _enum_of(schema: dict[str, Any]) -> list[str] | None:
    if "enum" in schema:
        return [str(v) for v in schema["enum"]]
    for key in ("anyOf", "oneOf", "allOf"):
        for part in schema.get(key, []):
            found = _enum_of(part)
            if found:
                return found
    return None


@pytest.mark.timeout(1800)
async def test_every_export_returns_a_real_file(world: World) -> None:
    from app.modules.site_logistics.export import REGISTERS

    spec = world.application.openapi()
    target_paths = {s.path for s in _served(world)}
    problems: list[str] = []
    checked = 0
    for path, ops in sorted(spec["paths"].items()):
        op = ops.get("get")
        if not op or "export" not in path:
            continue
        if path not in target_paths:
            continue
        domains: dict[str, list[str]] = {}
        fixed: dict[str, str] = {}
        in_path: dict[str, str] = {}
        skip = False
        id_param = None
        for p in op.get("parameters", []):
            name, where, schema = p["name"], p["in"], p.get("schema", {})
            values = _enum_of(schema)
            if name == "project_id":
                if where == "path":
                    in_path[name] = "<project>"
                else:
                    fixed[name] = "<project>"
            elif values:
                if where == "path":
                    in_path[name] = values[0]
                    domains[f"path:{name}"] = values
                else:
                    domains[name] = values
            elif name in ("format", "fmt", "export_format"):
                domains[name] = ["pdf", "xlsx"]
            elif where == "path" and name == "register":
                domains[f"path:{name}"] = list(REGISTERS)
            elif name in ("item_id", "package_id") and where == "query":
                id_param = name
            elif where == "path" or p.get("required"):
                skip = True
        if skip:
            continue
        keys = list(domains)
        for demo_id, project_id in sorted(world.projects.items()):
            for combo in itertools.islice(itertools.product(*(domains[k] for k in keys)), 40):
                chosen = dict(zip(keys, combo, strict=True))
                url = path.replace("{project_id}", str(project_id))
                for k, v in chosen.items():
                    if k.startswith("path:"):
                        url = url.replace("{" + k[5:] + "}", v)
                query = {k: v for k, v in chosen.items() if not k.startswith("path:")}
                if "project_id" in fixed:
                    query["project_id"] = str(project_id)
                if id_param and ("paper" in chosen.values() or "shortlist" in chosen.values()):
                    listing = path.split("/export")[0].replace("{project_id}", str(project_id))
                    listing += "/items" if id_param == "item_id" else "/packages"
                    got = await world.client.get(listing, params={"limit": 50}, headers=world.admin)
                    rows = _items(got.json())
                    if rows:
                        # The package board nests the package under ``contract_package``.
                        first = rows[0]
                        query[id_param] = str(first.get("id") or first["contract_package"]["id"])
                    if id_param == "item_id" and "paper" in chosen.values():
                        # Only the item the story flags carries a decision paper; print that one.
                        for row in rows:
                            papers = await world.client.get(
                                f"{listing}/{row['id']}/decision-paper", params={"limit": 1}, headers=world.admin
                            )
                            if papers.status_code == 200 and _items(papers.json()):
                                query[id_param] = str(row["id"])
                                break
                fmt = next((v for k, v in query.items() if k in ("format", "fmt", "export_format")), None)
                if fmt is None:
                    fmt = next((v for k, v in chosen.items() if v in ("pdf", "xlsx")), None)
                resp = await world.client.get(url, params=query, headers=world.admin)
                checked += 1
                label = f"{demo_id} GET {url.replace(str(project_id), '{pid}')} {query}"
                if resp.status_code != 200:
                    # A register with nothing to print may say so with a 4xx; a 5xx never.
                    if resp.status_code >= 500 or resp.status_code in (401, 403):
                        problems.append(f"{label} -> {resp.status_code} {resp.text[:160]}")
                    else:
                        problems.append(f"{label} -> {resp.status_code} (no file) {resp.text[:160]}")
                    continue
                ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                want = _PDF if fmt == "pdf" else _XLSX if fmt == "xlsx" else None
                if want and ctype != want:
                    problems.append(f"{label} -> content-type {ctype!r}, wanted {want!r}")
                if not resp.content:
                    problems.append(f"{label} -> empty body")
                elif ctype == _PDF and not resp.content.startswith(b"%PDF"):
                    problems.append(f"{label} -> body is not a PDF")
                elif ctype == _XLSX and not resp.content.startswith(b"PK"):
                    problems.append(f"{label} -> body is not an XLSX container")
    print(f"[elf-qa] exports checked: {checked}")  # noqa: T201
    _dump("exports", {"checked": checked, "problems": problems})
    assert checked > 20, f"only {checked} export calls were made"
    assert not problems, _fail_message("exports", problems)


# ── 3. Permission boundaries ────────────────────────────────────────────────

_WRITE = {"POST", "PUT", "PATCH", "DELETE"}

#: POSTs that only compute and store nothing (checked in the services): a viewer may call them.
_READ_ONLY_POST = re.compile(r"/(validate|numbering/(preview|bulk-validate|validate))$")


def _fill_any(path: str, project_id: uuid.UUID) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "project_id":
            return str(project_id)
        return str(uuid.uuid4()) if name.endswith("id") else "x"

    return re.sub(r"{([^}:]+)(?::[^}]+)?}", sub, path)


@pytest.mark.timeout(1800)
async def test_a_viewer_is_refused_every_write(world: World) -> None:
    project_id = next(iter(world.projects.values()))
    problems: list[str] = []
    weak: list[str] = []
    count = 0
    for route in sorted(_served(world), key=lambda r: r.path):
        for method in sorted(route.methods & _WRITE):
            url = _fill_any(route.path, project_id)
            resp = await world.client.request(method, url, json={}, headers=world.tokens["viewer"])
            count += 1
            label = f"{_module_of(route)} {method} {route.path}"
            if resp.status_code == 403:
                continue
            if method == "POST" and resp.status_code == 200 and _READ_ONLY_POST.search(route.path):
                continue
            if resp.status_code < 300 or resp.status_code >= 500:
                problems.append(f"{label} -> {resp.status_code} for a viewer: {resp.text[:140]}")
            else:
                weak.append(f"{label} -> {resp.status_code}")
    print(f"[elf-qa] viewer writes tried: {count}, answered other than 403: {len(weak)}")  # noqa: T201
    _dump("viewer_writes", {"tried": count, "problems": problems, "not_403": weak})
    assert not problems, _fail_message("viewer writes", problems)


@pytest.mark.timeout(1800)
async def test_a_user_of_another_workspace_cannot_read_a_demo_project(world: World) -> None:
    project_id = next(iter(world.projects.values()))
    problems: list[str] = []
    count = 0
    for route in sorted(_served(world), key=lambda r: r.path):
        if "GET" not in route.methods or _STATEFUL_WORDS.search(route.path):
            continue
        in_path = "{project_id}" in route.path
        q_names = {_alias(f): f for f in _query_fields(route)}
        if not in_path and "project_id" not in q_names:
            continue
        others = [p for p in _params(route.path) if p != "project_id"]
        if others:
            continue
        required = [n for n, f in q_names.items() if n != "project_id" and getattr(f, "required", False)]
        if required:
            continue
        url = _fill_any(route.path, project_id)
        query = {"project_id": str(project_id)} if not in_path else {}
        resp = await world.client.get(url, params=query, headers=world.tokens["outsider"])
        count += 1
        label = f"{_module_of(route)} GET {route.path}"
        if resp.status_code in (403, 404):
            continue
        if resp.status_code >= 500:
            problems.append(f"{label} -> {resp.status_code}: {resp.text[:140]}")
        elif resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                body = resp.content
            if resp.headers.get("content-type", "").startswith("application/json") and not _nonempty(body):
                continue
            problems.append(f"{label} -> 200 with content for a user outside the project")
        elif resp.status_code not in (401, 405, 422):
            problems.append(f"{label} -> {resp.status_code}")
    print(f"[elf-qa] outsider reads tried: {count}")  # noqa: T201
    _dump("outsider_reads", {"tried": count, "problems": problems})
    assert count > 40, f"only {count} reads were tried"
    assert not problems, _fail_message("outsider reads", problems)


# ── 5. A second install adds nothing ────────────────────────────────────────

_APPEND_ONLY = {"oe_core_audit_log", "oe_activity_log", "oe_boq_activity_log"}


async def _counts(world: World) -> dict[str, int]:
    from app.database import Base

    out: dict[str, int] = {}
    async with world.factory() as s:
        for table in Base.metadata.sorted_tables:
            out[table.name] = (await s.execute(select(func.count()).select_from(table))).scalar_one()
    return out


@pytest.mark.timeout(1800)
async def test_a_second_install_adds_no_rows_and_logs_nothing(world: World) -> None:
    before = await _counts(world)
    assert world.collector is not None
    world.collector.records.clear()
    world.collector.active = True
    try:
        done = await install_pack(world.client, world.admin)
    finally:
        world.collector.active = False
    after = await _counts(world)
    grew = {t: (before[t], after[t]) for t in before if after[t] != before[t] and t not in _APPEND_ONLY}
    assert done["ok"], done
    assert not grew, f"a second install changed row counts: {grew}"
    assert not world.collector.records, "the second install logged:\n" + "\n".join(world.collector.records[:40])
    assert PACK_SLUG in json.dumps(done)
