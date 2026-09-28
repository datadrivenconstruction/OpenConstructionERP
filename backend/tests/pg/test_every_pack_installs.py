# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every pack installs on a fresh PostgreSQL database, the way an admin installs it.

The unit suite already holds the pack wiring to account from the outside: that
every declared rule set is registered, that every demo id resolves to a
template, that every file a manifest names is shipped. None of those tests ever
installs anything, and the install is where the failures hide. Every layer of it
is fail-soft on purpose. ``apply_pack`` records a demo failure in ``effects``
and still answers ``applied: True``, the demo step reports ``ok`` if any one of
its demos landed, the seeder wraps each module block in its own ``except`` and
logs at debug, and the stream installer's final ``ok`` only looks at step
statuses. So a pack can install half a workspace and every status it prints
reads green. This file asserts on what the database holds instead.

For each pack, on its own database cloned from a booted template:

* the Modules page path, ``full_install_stream``, runs to ``done`` with no step
  in error, installs exactly the demos the installer says it will, and each of
  them has a bill with positions, a schedule with activities, a budget and a
  tender package;
* the pack's locale has a bundle and its extra locale files are readable, and
  its country has VAT rows on file;
* running the same install again changes no table's row count;
* un-applying releases the projects without deleting them and clears the state;
* the ``/apply`` path, run afterwards, reports no demo failure and switches the
  pack's methodology on for its flagship project.

Gated behind ``OE_PACK_MATRIX=1`` because the full matrix installs roughly a
hundred demo projects and does not fit the main PostgreSQL job. ``OE_PACK_SHARD``
(``"k/n"``, 1-based) selects every n-th pack so CI can split it across runners.
The cost database step is off here: it downloads a parquet per region from
GitHub, and the memory-bounded import is measured by its own job.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import pathlib
import sys
import tomllib
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKS_DIR = REPO_ROOT / "packs"
LOCALES_DIR = REPO_ROOT / "frontend" / "src" / "app" / "locales"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("OE_PACK_MATRIX", "") != "1",
        reason="pack install matrix only - set OE_PACK_MATRIX=1 (runs in its own CI job)",
    ),
]

# Tables whose row count legitimately grows when the same install runs twice.
# Each one is a log of events, and a second install is a second event.
_APPEND_ONLY_TABLES = {
    "oe_core_audit_log",  # one row per audited write, re-running writes again
    "oe_activity_log",  # the cross-module activity feed, same shape
    "oe_boq_activity_log",  # the BOQ activity feed, same shape
}


# ── Which packs ─────────────────────────────────────────────────────────────


def _pack_dirs() -> list[pathlib.Path]:
    """Every pack directory discovery would load: a manifest and no DEPRECATED.txt."""
    out = []
    for manifest in sorted(PACKS_DIR.glob("*/src/openconstructionerp_*/manifest.py")):
        pack_dir = manifest.parents[2]
        if any(pack_dir.rglob("DEPRECATED.txt")):
            continue
        out.append(pack_dir)
    return out


def _force_included() -> set[str]:
    """The pack directories the main wheel carries (``backend/pyproject.toml``)."""
    data = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    fi = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    return {pathlib.PurePosixPath(k).parts[2] for k in fi if k.startswith("../packs/")}


def _shard(items: list[str]) -> list[str]:
    raw = os.environ.get("OE_PACK_SHARD", "").strip()
    if not raw:
        return items
    k, n = (int(x) for x in raw.split("/"))
    return [it for i, it in enumerate(items) if i % n == k - 1]


ALL_PACK_DIRS = [d.name for d in _pack_dirs()]
PACK_DIRS = _shard(ALL_PACK_DIRS)


def _load_manifest(pack_dir_name: str) -> Any:
    """The manifest object the pack's ``manifest.py`` builds, loaded by path."""
    (path,) = PACKS_DIR.glob(f"{pack_dir_name}/src/openconstructionerp_*/manifest.py")
    name = f"_pack_matrix_manifest_{path.parts[-2]}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"{path} could not be loaded"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.MANIFEST


# ── A booted template database, cloned per pack ─────────────────────────────

_TEMPLATE_DB = "oe_pack_matrix_tpl"


def _register_validators() -> None:
    """Register every rule set the booted app registers.

    The registry is filled by imports: core rules on startup, module rule sets
    when each module's ``validators`` is imported by the loader. ``apply_pack``
    refuses a pack whose rule sets are not registered, so without this the
    matrix would be measuring the pytest session rather than the app.
    """
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    for p in sorted((REPO_ROOT / "backend" / "app" / "modules").glob("*/validators.py")):
        importlib.import_module(f"app.modules.{p.parent.name}.validators")


@pytest_asyncio.fixture(scope="module")
async def pack_template_url(pg_async_url):
    """Build the template database once: full schema plus the boot-time seeds."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.module_loader import module_loader
    from app.database import Base

    base = make_url(pg_async_url)
    admin = create_engine(base.set(drivername="postgresql+psycopg2"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_TEMPLATE_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_TEMPLATE_DB}"'))
    tpl_sync = create_engine(base.set(drivername="postgresql+psycopg2", database=_TEMPLATE_DB))
    Base.metadata.create_all(tpl_sync)
    tpl_sync.dispose()

    # What a first boot seeds before anyone can open the Modules page
    # (app/main.py lifespan): countries, taxes, calendars, and the starter
    # cost items. Without it the VAT assertion below reads an empty table.
    from app.modules.i18n_foundation.seed import seed_i18n_data
    from app.scripts.seed_starter import seed_starter_data

    tpl_url = base.set(database=_TEMPLATE_DB)
    eng = create_async_engine(tpl_url, poolclass=NullPool)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await seed_i18n_data(s)
        await s.commit()
    async with factory() as s:
        await seed_starter_data(s)
        await s.commit()
    await eng.dispose()

    module_loader.discover()
    _register_validators()
    try:
        yield base, admin
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_TEMPLATE_DB}" WITH (FORCE)'))
        admin.dispose()


def _rebind(monkeypatch: pytest.MonkeyPatch, original: Any, replacement: Any) -> None:
    """Point every module attribute that IS ``original`` at ``replacement``.

    Most installers import the factory inside the function, which a patch on
    ``app.database`` reaches, but a handful import it at module level and keep
    their own reference. Walking ``sys.modules`` catches both.
    """
    for mod in list(sys.modules.values()):
        if mod is None or not getattr(mod, "__name__", "").startswith("app"):
            continue
        for attr, value in list(vars(mod).items()):
            if value is original:
                monkeypatch.setattr(mod, attr, replacement)


@pytest_asyncio.fixture
async def fresh_db(pack_template_url, monkeypatch, tmp_path):
    """A database of its own for one pack, and a data directory of its own."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.database
    from app.core.partner_pack.discovery import reset_cache

    base, admin = pack_template_url
    name = f"oe_pack_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{_TEMPLATE_DB}"'))
    eng = create_async_engine(base.set(database=name), poolclass=NullPool)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    _rebind(monkeypatch, app.database.async_session_factory, factory)
    _rebind(monkeypatch, app.database.engine, eng)
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
    reset_cache()
    try:
        yield factory
    finally:
        reset_cache()
        await eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


# ── Helpers over the installed database ─────────────────────────────────────


async def _stream_install(slug: str, *, demo_count: int = 2) -> dict[str, Any]:
    """Drive the Modules-page installer and return its ``done`` payload."""
    from app.core.partner_pack.full_install import FullInstallRequest, full_install_stream

    req = FullInstallRequest(slug=slug, install_cost_db=False, vectorize=False, demo_count=demo_count)
    frames = [frame async for frame in full_install_stream(req, app=None)]
    last = frames[-1]
    assert last.startswith("event: done"), f"the stream ended on {last[:80]!r}"
    payload = last.split("data: ", 1)[1].strip()
    return json.loads(payload)


def _expected_demos(slug: str, demo_count: int = 2) -> list[str]:
    """The demo list ``_step_demos`` computes, recomputed the same way."""
    from app.core.demo_projects import DEMO_TEMPLATES
    from app.core.partner_pack.discovery import get_pack_by_slug
    from app.core.partner_pack.full_install import _demo_install_list

    pack = get_pack_by_slug(slug)
    pinned = [d for d in (getattr(pack, "demo_template_ids", []) or []) if d in DEMO_TEMPLATES]
    return _demo_install_list(slug, min(10, max(demo_count, len(pinned))))


async def _table_counts(factory) -> dict[str, int]:
    from app.database import Base

    out: dict[str, int] = {}
    async with factory() as s:
        for table in Base.metadata.sorted_tables:
            out[table.name] = (await s.execute(select(func.count()).select_from(table))).scalar_one()
    return out


async def _project_children(factory, project_id: uuid.UUID) -> dict[str, int]:
    """Row counts of the core child tables every demo install writes."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.costmodel.models import BudgetLine
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.tendering.models import TenderPackage

    async with factory() as s:

        async def n(stmt) -> int:
            return (await s.execute(stmt)).scalar_one()

        return {
            "boqs": await n(select(func.count()).select_from(BOQ).where(BOQ.project_id == project_id)),
            "positions": await n(
                select(func.count())
                .select_from(Position)
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(BOQ.project_id == project_id)
            ),
            "schedules": await n(select(func.count()).select_from(Schedule).where(Schedule.project_id == project_id)),
            "activities": await n(
                select(func.count())
                .select_from(Activity)
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == project_id)
            ),
            "budget_lines": await n(
                select(func.count()).select_from(BudgetLine).where(BudgetLine.project_id == project_id)
            ),
            "tender_packages": await n(
                select(func.count()).select_from(TenderPackage).where(TenderPackage.project_id == project_id)
            ),
        }


async def _demo_projects(factory) -> dict[str, Any]:
    from app.modules.projects.models import Project

    async with factory() as s:
        rows = (await s.execute(select(Project))).scalars().all()
    return {p.metadata_.get("demo_id"): p for p in rows if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id")}


_WATCHED_LOGGERS = ("app.core.partner_pack", "app.core.demo_enrichment", "app.core.demo_projects")


def _install_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        f"{r.name}: {r.getMessage()}"
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith(_WATCHED_LOGGERS)
    ]


# ── The matrix ──────────────────────────────────────────────────────────────


def test_the_matrix_covers_every_pack_the_wheel_ships() -> None:
    """A pack that drops out of the parametrisation must go red, not go quiet."""
    missing = _force_included() - set(ALL_PACK_DIRS)
    assert not missing, f"shipped packs the install matrix does not reach: {sorted(missing)}"
    assert len(ALL_PACK_DIRS) >= 40, f"only {len(ALL_PACK_DIRS)} packs found under {PACKS_DIR}"


@pytest.mark.timeout(1500)
@pytest.mark.parametrize("pack_dir", PACK_DIRS)
async def test_the_pack_installs_on_a_fresh_database(pack_dir: str, fresh_db, caplog) -> None:
    from app.core.partner_pack.apply import apply_pack, build_preview, unapply
    from app.core.partner_pack.discovery import get_pack_by_slug, read_pack_file, reset_cache
    from app.core.partner_pack.state import load_applied_state
    from app.modules.i18n_foundation.models import TaxConfiguration as TaxConfig

    caplog.set_level(logging.WARNING)
    factory = fresh_db
    manifest = _load_manifest(pack_dir)
    slug = manifest.slug
    m = get_pack_by_slug(slug)
    assert m is not None, f"{pack_dir}: discovery does not list slug {slug!r}"

    # The dry run the dialog shows first. It raises on an unknown rule set.
    plan = build_preview(slug)["plan"]
    assert not plan["modules_to_enable_missing"], f"{slug}: enables modules that do not exist"
    assert not plan["modules_to_disable_missing"], f"{slug}: hides modules that do not exist"

    # Locale: the interface bundle and any locale files the pack carries.
    loc = m.default_locale
    assert (LOCALES_DIR / f"{loc}.ts").exists() or (LOCALES_DIR / f"{loc.split('-')[0]}.ts").exists(), (
        f"{slug}: no interface bundle for default locale {loc!r}"
    )
    for code, rel in m.additional_locales.items():
        raw = read_pack_file(slug, rel)
        assert raw, f"{slug}: additional locale {code} at {rel} is not readable"
        assert json.loads(raw), f"{slug}: additional locale {code} at {rel} is empty"

    # ── 1. The Modules-page install ──
    expected = _expected_demos(slug)
    done = await _stream_install(slug)
    steps = {s["step"]: s for s in done["steps"]}
    errored = {k: v for k, v in steps.items() if v["status"] == "error"}
    assert not errored, f"{slug}: steps in error: {errored}"
    assert done["ok"], f"{slug}: install reported ok=False: {done['steps']}"
    assert steps["apply_pack"]["status"] == "ok"
    assert steps["locale"]["detail"].get("locale") == loc
    demos = steps["demos"]
    if expected:
        assert demos["status"] == "ok", f"{slug}: demos step {demos}"
        assert demos["detail"].get("installed") == expected, f"{slug}: demos {demos['detail']} != {expected}"
        assert not demos["detail"].get("errors"), f"{slug}: demo errors {demos['detail']['errors']}"
    state = load_applied_state()
    assert state is not None and state.slug == slug, f"{slug}: no applied-pack record after install"

    projects = await _demo_projects(factory)
    empty: dict[str, dict[str, int]] = {}
    for demo_id in expected:
        project = projects.get(demo_id)
        assert project is not None, f"{slug}: demo {demo_id} reported installed but no project row"
        assert project.metadata_.get("partner_pack") == slug, f"{slug}: {demo_id} not scoped to the pack"
        counts = await _project_children(factory, project.id)
        if not all(counts.values()):
            empty[demo_id] = counts
    assert not empty, f"{slug}: demo projects with empty core modules: {empty}"

    country = (m.metadata or {}).get("country")
    if country:
        async with factory() as s:
            vat_rows = (
                await s.execute(select(func.count()).select_from(TaxConfig).where(TaxConfig.country_code == country))
            ).scalar_one()
        assert vat_rows > 0, f"{slug}: no VAT rows on file for {country}"

    # ── 2. The same install again adds nothing ──
    before = await _table_counts(factory)
    await _stream_install(slug)
    after = await _table_counts(factory)
    grew = {t: (before[t], after[t]) for t in before if after[t] != before[t] and t not in _APPEND_ONLY_TABLES}
    assert not grew, f"{slug}: a second install changed row counts: {grew}"

    # ── 3. Un-apply releases the projects and clears the state ──
    res = await unapply(app=None)
    assert res["applied"] is False
    assert load_applied_state() is None, f"{slug}: applied-pack record survived un-apply"
    reset_cache()
    projects = await _demo_projects(factory)
    for demo_id in expected:
        assert demo_id in projects, f"{slug}: un-apply deleted demo {demo_id}"
        assert "partner_pack" not in projects[demo_id].metadata_, f"{slug}: {demo_id} still tagged"

    # ── 4. The /apply path on the same workspace ──
    applied = await apply_pack(slug, install_demo=True, app=None)
    effects = applied["effects"]
    assert applied["applied"] is True
    assert "demo_project_failed" not in effects, f"{slug}: /apply demo failed: {effects['demo_project_failed']}"
    assert not effects["modules_failed"], f"{slug}: /apply module failures: {effects['modules_failed']}"
    if m.default_methodology and effects.get("demo_project"):
        from app.modules.methodology.templates import TEMPLATES_BY_SLUG

        assert m.default_methodology in TEMPLATES_BY_SLUG, (
            f"{slug}: default_methodology {m.default_methodology!r} is not a template, so it is never activated"
        )
        pid = uuid.UUID(str(effects["demo_project"]["project_id"]))
        projects = await _demo_projects(factory)
        flagship = next(p for p in projects.values() if p.id == pid)
        assert flagship.metadata_.get("methodology_slug") == m.default_methodology, (
            f"{slug}: flagship project methodology is {flagship.metadata_.get('methodology_slug')!r}"
        )

    warnings = _install_warnings(caplog)
    assert not warnings, f"{slug}: the install logged warnings:\n" + "\n".join(warnings[:40])
