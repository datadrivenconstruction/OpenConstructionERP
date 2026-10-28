# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every pack installs on a fresh PostgreSQL database, the way an admin installs it.

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


# Countries a shipped pack names that the tax seed does not carry yet. A pack
# for one of them installs, and its invoices open with no VAT line to pick.
# Listed rather than skipped so the day the seed gains the country this goes
# red and the entry comes out. Indonesia: PPN is 12% by statute since
# 2025-01-01 and 11% in effect for most supplies (PMK 131/2024), which is a
# rate decision for a person to make, not for a test to guess.
_VAT_NOT_SEEDED_YET = {"ID"}


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
    # Some writers (the cost base bulk copy among them) open a sync connection
    # from DATABASE_SYNC_URL instead of using the session factory.
    sync_url = base.set(drivername="postgresql+psycopg2", database=name)
    monkeypatch.setenv("DATABASE_SYNC_URL", sync_url.render_as_string(hide_password=False))
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

    # ``XX`` is how a sector pack (renewables, modular, retail across DACH)
    # says it belongs to no single country, so it has no VAT of its own.
    country = (m.metadata or {}).get("country")
    if country and country != "XX":
        async with factory() as s:
            vat_rows = (
                await s.execute(select(func.count()).select_from(TaxConfig).where(TaxConfig.country_code == country))
            ).scalar_one()
        if country in _VAT_NOT_SEEDED_YET:
            assert vat_rows == 0, f"{slug}: {country} now has VAT rows, drop it from _VAT_NOT_SEEDED_YET"
        else:
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


# ── Switching packs ─────────────────────────────────────────────────────────

# Pairs that share nothing: different country, currency and demos. Switching
# is the branch where the installer deletes the previous pack's demo projects,
# an ORM delete over a project with hundreds of child rows inside an ``except``
# that returns 0, so a delete PostgreSQL refuses reads as "nothing to delete".
_SWITCH_PAIRS = _shard(["germany-de>france-fr", "us-costdata>uk-jct", "japan-jp>brazil-sinapi"])


@pytest.mark.timeout(1500)
@pytest.mark.parametrize("pair", _SWITCH_PAIRS)
async def test_switching_packs_removes_the_previous_packs_demos(pair: str, fresh_db, caplog) -> None:
    from app.core.partner_pack.state import load_applied_state

    caplog.set_level(logging.WARNING)
    factory = fresh_db
    first, second = (_load_manifest(d).slug for d in pair.split(">"))

    await _stream_install(first)
    first_demos = set(_expected_demos(first))
    assert first_demos, f"{first} installs no demos, so this pair tests nothing"
    assert first_demos <= set(await _demo_projects(factory))

    done = await _stream_install(second)
    steps = {s["step"]: s for s in done["steps"]}
    assert steps["apply_pack"]["detail"].get("switched_from") == first
    state = load_applied_state()
    assert state is not None and state.slug == second

    left = (first_demos - set(_expected_demos(second))) & set(await _demo_projects(factory))
    assert not left, f"switching {first} -> {second} left the previous pack's demos behind: {sorted(left)}"
    warnings = _install_warnings(caplog)
    assert not warnings, f"{pair}: the switch logged warnings:\n" + "\n".join(warnings[:40])


# ── Showcase templates no pack installs ─────────────────────────────────────


def _unreached_templates() -> list[str]:
    """Demo templates no pack's one-click install reaches, so the loop above never runs them."""
    if os.environ.get("OE_PACK_MATRIX", "") != "1":
        return []
    from app.core.demo_projects import DEMO_TEMPLATES

    reached: set[str] = set()
    for d in ALL_PACK_DIRS:
        reached.update(_expected_demos(_load_manifest(d).slug))
    return _shard(sorted(set(DEMO_TEMPLATES) - reached))


@pytest.mark.timeout(900)
@pytest.mark.parametrize("demo_id", _unreached_templates())
async def test_a_showcase_template_no_pack_installs_still_installs(demo_id: str, fresh_db, caplog) -> None:
    from app.core.demo_enrichment import enrich_projects
    from app.core.demo_projects import install_demo_project

    caplog.set_level(logging.WARNING)
    factory = fresh_db
    async with factory() as s:
        res = await install_demo_project(s, demo_id)
        await s.commit()
    pid = uuid.UUID(str(res["project_id"]))
    await enrich_projects([pid])
    counts = await _project_children(factory, pid)
    assert all(counts.values()), f"{demo_id}: empty core modules {counts}"

    before = await _table_counts(factory)
    async with factory() as s:
        again = await install_demo_project(s, demo_id)
        await s.commit()
    await enrich_projects([pid])
    after = await _table_counts(factory)
    assert again.get("already_installed"), f"{demo_id}: a second install did not recognise the first"
    grew = {t: (before[t], after[t]) for t in before if after[t] != before[t] and t not in _APPEND_ONLY_TABLES}
    assert not grew, f"{demo_id}: a second install changed row counts: {grew}"
    warnings = _install_warnings(caplog)
    assert not warnings, f"{demo_id}: the install logged warnings:\n" + "\n".join(warnings[:40])


# ── Governance on the demo projects of a pack ───────────────────────────────

_GOVERNANCE_LOGGERS = ("app.modules.project_governance", "app.core.demo_cast")


_DEMO_LOGINS = ("estimator@openconstructionerp.com", "manager@openconstructionerp.com")


async def _governance_of(factory, project_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.project_governance import public
    from app.modules.project_governance.models import (
        GovernanceArea,
        GovernanceDecision,
        GovernanceDocument,
        GovernanceModel,
    )

    async with factory() as s:

        async def rows(model: Any) -> list[Any]:
            return list((await s.execute(select(model).where(model.project_id == project_id))).scalars())

        return {
            "models": await rows(GovernanceModel),
            "areas": await rows(GovernanceArea),
            "documents": await rows(GovernanceDocument),
            "decisions": await rows(GovernanceDecision),
            "enabling": await public.phases_enabling(s, project_id, "construction_start"),
            "gates": await public.project_gates(s, project_id) if await rows(GovernanceModel) else [],
        }


def _governance_records(caplog: pytest.LogCaptureFixture) -> tuple[list[str], list[logging.LogRecord]]:
    """What the governance seed logged above info, and its one line per project that missed its plan."""
    loud = [
        f"{r.name}: {r.getMessage()}"
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith(_GOVERNANCE_LOGGERS)
    ]
    return loud, [r for r in caplog.records if "was planned at" in r.getMessage()]


# One pack, in one shard: the question is asked of the installer, not of each pack.
@pytest.mark.timeout(1500)
@pytest.mark.parametrize("pack_dir", _shard(["germany-de"]))
async def test_a_fresh_pack_install_tells_every_demo_project_by_its_owner_alone(
    pack_dir: str, fresh_db, caplog
) -> None:
    """A pack install creates the demo projects and their owner, and nobody else.

    Under four-eyes the owner of an area cannot decide its gate, and the seed
    creates no user. So every demo project gets what one person can do: a
    model, owned areas, issued documents, no decision. That is a legal state
    and nothing is logged above info for it. The project a pack's demo file
    names is the exception: it is filmed with the demo logins or not at all.
    """
    from app.modules.project_governance import catalogue_packs, seed_story
    from app.modules.users.models import User

    caplog.set_level(logging.INFO)
    factory = fresh_db
    slug = _load_manifest(pack_dir).slug
    done = await _stream_install(slug)
    assert done["ok"], f"{slug}: install reported ok=False: {done['steps']}"
    expected = _expected_demos(slug)
    assert expected, f"{slug} installs no demos, so this test asks nothing"
    async with factory() as s:
        logins = (await s.execute(select(User.email).where(func.lower(User.email).in_(_DEMO_LOGINS)))).scalars().all()
    assert logins == [], f"{slug}: this world is the one without the demo logins, found {logins}"

    projects = await _demo_projects(factory)
    pack_projects = seed_story.pack_demo_ids(catalogue_packs.active_pack_demo())
    filmed_ids = [d for d in expected if d in pack_projects]
    for demo_id in expected:
        has = await _governance_of(factory, projects[demo_id].id)
        if demo_id in filmed_ids:
            assert has["models"] == [], f"{slug}: the filmed project {demo_id} was told without its cast"
            continue
        assert len(has["models"]) == 1, f"{slug}: demo {demo_id} has no governance model"
        assert has["areas"] and all(a.owner_user_id == projects[demo_id].owner_id for a in has["areas"]), demo_id
        assert [d for d in has["documents"] if d.container_id], f"{slug}: demo {demo_id} has no issued document"
        assert has["decisions"] == [], f"{slug}: demo {demo_id} carries a decision nobody could have taken"
        assert "decided" not in {g.status for g in has["gates"]}, demo_id

    loud, told = _governance_records(caplog)
    filmed = [m for m in loud if "was planned at" in m]
    assert len(filmed) == len(filmed_ids), loud
    assert sorted(loud) == sorted(filmed), f"{slug}: the governance seed logged:\n" + "\n".join(loud[:40])
    quiet = [r for r in told if r.levelno == logging.INFO]
    assert len(quiet) == len([d for d in expected if d not in filmed_ids]), [r.getMessage() for r in told]
    assert all("no_decider" in r.getMessage() for r in told), [r.getMessage() for r in told]


@pytest.mark.timeout(1500)
@pytest.mark.parametrize("pack_dir", _shard(["germany-de"]))
async def test_a_pack_install_beside_the_demo_logins_leaves_every_demo_project_at_its_planned_gate(
    pack_dir: str, fresh_db, caplog
) -> None:
    """The same install on a database that has the two demo logins: every story is told in full.

    The logins are put there by this test, the way the boot seeder does when
    the demo is enabled. Nothing in the product creates them for a pack.
    """
    from app.modules.project_governance import catalogue_packs, seed_story
    from app.modules.users.models import User

    caplog.set_level(logging.INFO)
    factory = fresh_db
    async with factory() as s:
        for email in _DEMO_LOGINS:
            name = email.split("@")[0]
            s.add(
                User(
                    id=uuid.uuid4(),
                    email=email,
                    hashed_password="x",
                    full_name=name.title(),
                    role=name,
                    locale="en",
                    is_active=True,
                    metadata_={},
                )
            )
        await s.commit()
    slug = _load_manifest(pack_dir).slug
    done = await _stream_install(slug)
    assert done["ok"], f"{slug}: install reported ok=False: {done['steps']}"
    expected = _expected_demos(slug)
    assert expected, f"{slug} installs no demos, so this test asks nothing"

    projects = await _demo_projects(factory)
    pack_projects = seed_story.pack_demo_ids(catalogue_packs.active_pack_demo())
    placed = 0
    for demo_id in expected:
        planned = seed_story.planned_moment(demo_id, pack_projects)
        has = await _governance_of(factory, projects[demo_id].id)
        assert len(has["models"]) == 1, f"{slug}: demo {demo_id} has no governance model (planned {planned})"
        if planned in ("execution", "near_handover"):
            placed += 1
            into = [g.status for g in has["gates"] if g.to_phase in has["enabling"]]
            assert into == ["decided"], f"{slug}: {demo_id} was planned at {planned}, its construction gate is {into}"
        elif planned == "first_gate":
            decided = len(has["decisions"])
            assert decided == 1, f"{slug}: {demo_id} has {decided} gate decisions, the first-gate story takes one"
    assert placed or set(pack_projects) & set(expected), (
        f"{slug}: none of {expected} is a placed project, pick another pack"
    )

    loud, told = _governance_records(caplog)
    assert not loud, f"{slug}: the governance seed logged:\n" + "\n".join(loud[:40])
    assert not told, f"{slug}: placement fallbacks: {[r.getMessage() for r in told]}"


# The tables behind the screens of the eleven areas, by module prefix. A filmed project of the
# pack must have rows in each table that carries a project id, unless the table is listed here
# with the reason it is empty on a healthy demo.
_ELEVEN_MODULES = (
    "project_governance",
    "stakeholders",
    "delivery_model",
    "permits",
    "plant_register",
    "staffing",
    "site_logistics",
    "design_management",
    "procurement_concept",
    "commitment_release",
    "quality_concept",
    "transmittals",
    "handbook",
)
_EMPTY_BY_DESIGN: dict[str, str] = {
    # Written only when a delivery is scheduled on a granted oversize permit, which needs a running site.
    "oe_site_logistics_permit_transport": "a site before its construction gate schedules no delivery",
}


@pytest.mark.timeout(1500)
@pytest.mark.parametrize("path", ["modules_page", "apply"])
@pytest.mark.parametrize("pack_dir", _shard(["eleven-areas-framework"]))
async def test_every_screen_of_the_eleven_areas_has_rows_for_both_filmed_projects(
    pack_dir: str, path: str, fresh_db, caplog
) -> None:
    """The video series films both projects: no table behind an area's screens may be empty.

    The demo logins are put there first, as in the beside-the-logins test, so the governance
    story is told in full. Every table of the twelve modules that carries a project id is counted
    for each project; the failure lists all the empty ones at once.
    """
    from app.database import Base
    from app.modules.project_governance import catalogue_packs, seed_story
    from app.modules.users.models import User

    caplog.set_level(logging.WARNING)
    factory = fresh_db
    async with factory() as s:
        for email in _DEMO_LOGINS:
            name = email.split("@")[0]
            s.add(
                User(
                    id=uuid.uuid4(),
                    email=email,
                    hashed_password="x",
                    full_name=name.title(),
                    role=name,
                    locale="en",
                    is_active=True,
                    metadata_={},
                )
            )
        await s.commit()
    slug = _load_manifest(pack_dir).slug
    if path == "apply":
        # The route the Modules page "apply" button and the API take: it must land every demo the pack pins.
        from app.core.partner_pack.apply import apply_pack

        applied = await apply_pack(slug, install_demo=True, app=None)
        assert applied["applied"] is True
        assert "demo_project_failed" not in applied["effects"], applied["effects"]
        assert len(applied["effects"].get("demo_projects", [])) == 2, applied["effects"]
    else:
        done = await _stream_install(slug)
        assert done["ok"], f"{slug}: install reported ok=False: {done['steps']}"
    projects = await _demo_projects(factory)
    filmed = seed_story.pack_demo_ids(catalogue_packs.active_pack_demo())
    assert len(filmed) == 2 and all(d in projects for d in filmed), (filmed, sorted(projects))

    tables = sorted(
        (
            t
            for t in Base.metadata.sorted_tables
            if "project_id" in t.c and any(t.name.startswith(f"oe_{m}_") for m in _ELEVEN_MODULES)
        ),
        key=lambda t: t.name,
    )
    assert len(tables) >= 40, f"only {len(tables)} tables found behind the eleven areas"
    empty: dict[str, list[str]] = {}
    async with factory() as s:
        for demo_id in filmed:
            pid = projects[demo_id].id
            for table in tables:
                if table.name in _EMPTY_BY_DESIGN:
                    continue
                count = (
                    await s.execute(select(func.count()).select_from(table).where(table.c.project_id == pid))
                ).scalar_one()
                if not count:
                    empty.setdefault(demo_id, []).append(table.name)
    assert not empty, "tables with no rows for a filmed project:\n" + "\n".join(
        f"{demo_id}: {', '.join(names)}" for demo_id, names in empty.items()
    )
    # Each area of a filmed project has its own named owner, and every owner but the project's own account
    # is a roster line with a name, so the screens never print a bare id or the same person eleven times.
    from app.modules.project_governance.models import GovernanceArea
    from app.modules.teams.models import RosterMember
    from app.modules.users.models import User

    async with factory() as s:
        for demo_id in filmed:
            project = projects[demo_id]
            owners = [
                o
                for o in (
                    await s.execute(
                        select(GovernanceArea.owner_user_id).where(
                            GovernanceArea.project_id == project.id, GovernanceArea.retired.is_(False)
                        )
                    )
                ).scalars()
            ]
            assert len(owners) == 11 and None not in owners, (demo_id, owners)
            assert len(set(owners)) >= 10, f"{demo_id}: the areas share owners: {len(set(owners))} distinct"
            named = {
                uid
                for uid in (
                    await s.execute(
                        select(RosterMember.user_id).where(
                            RosterMember.project_id == project.id, RosterMember.user_id.is_not(None)
                        )
                    )
                ).scalars()
            }
            people = [o for o in set(owners) if o != project.owner_id]
            assert people and set(people) <= named, f"{demo_id}: owners without a roster name"
            for user in (await s.execute(select(User).where(User.id.in_(people)))).scalars():
                # Nobody can sign in as a demo person.
                assert user.is_active is False and (user.metadata_ or {}).get("demo_person") is True, user.email

            # The handbook chapters of an area are written by that area's owner, and the edition names the phase.
            from app.modules.project_handbook.models import Handbook, HandbookChapter

            area_owner = {
                a.code: a.owner_user_id
                for a in (
                    await s.execute(select(GovernanceArea).where(GovernanceArea.project_id == project.id))
                ).scalars()
            }
            chapters = (
                await s.execute(select(HandbookChapter).where(HandbookChapter.project_id == project.id))
            ).scalars()
            wrong = [c.code for c in chapters if c.area_code in area_owner and c.owner_id != area_owner[c.area_code]]
            assert not wrong, f"{demo_id}: handbook chapters not owned by their area owner: {wrong}"
            edition = (await s.execute(select(Handbook.edition).where(Handbook.project_id == project.id))).scalar_one()
            assert edition == (
                "Ausgabe 2, Ausführungsphase" if demo_id == "residential-regensburg" else "Ausgabe 1, Entwicklungsphase"
            ), (demo_id, edition)
            # A project waiting at the gate shows the end of its phase, the running site its first execution phase.
            from app.modules.projects.models import Project

            shown = (await s.execute(select(Project.phase).where(Project.id == project.id))).scalar_one()
            assert shown == ("construction" if demo_id == "residential-regensburg" else "award"), (demo_id, shown)

    # Interfaces and transmittals are told by the pack story, not by the generic seeders:
    # German titles, no foreign script, and nothing closed or issued before its time.
    import re

    from app.modules.interface_management.models import InterfaceRecord
    from app.modules.transmittals.models import Transmittal

    foreign = re.compile(r"[Ѐ-ӿ぀-ヿ一-鿿؀-ۿ]")
    english = re.compile(r"\b(the|and|penetrations|drawings|supply to)\b", re.IGNORECASE)
    async with factory() as s:
        for demo_id in filmed:
            pid = projects[demo_id].id
            interfaces = (
                (await s.execute(select(InterfaceRecord).where(InterfaceRecord.project_id == pid))).scalars().all()
            )
            assert 8 <= len(interfaces) <= 15, f"{demo_id}: {len(interfaces)} interfaces"
            transmittals = (await s.execute(select(Transmittal).where(Transmittal.project_id == pid))).scalars().all()
            listing = "; ".join(
                f"{r.transmittal_number} {r.status} {r.subject!r} {(r.metadata_ or {}).get('recipient_key', '-')}"
                for r in sorted(transmittals, key=lambda r: r.transmittal_number)
            )
            told = [r for r in transmittals if "design_release_id" not in (r.metadata_ or {})]
            issued = [r for r in transmittals if "design_release_id" in (r.metadata_ or {})]
            assert len(told) == 5, f"{demo_id}: {len(told)} story transmittals, the story tells five: {listing}"
            # The design releases add one transmittal per recipient and release, never two for the same pair.
            pairs = [
                ((r.metadata_ or {})["design_release_id"], (r.metadata_ or {}).get("recipient_key")) for r in issued
            ]
            assert len(pairs) == len(set(pairs)), f"{demo_id}: a recipient got a release twice: {listing}"
            texts = [r.title for r in interfaces] + [r.owner_party or "" for r in interfaces]
            texts += [r.subject for r in transmittals]
            for text in texts:
                assert not foreign.search(text), f"{demo_id}: non-German script in {text!r}"
                assert not english.search(text), f"{demo_id}: English text in the German project: {text!r}"
            for row in interfaces:
                assert (row.status in ("agreed", "closed")) == (row.agreed_date is not None), row.reference
                assert (row.status == "closed") == (row.closed_date is not None), row.reference
    # The data room: the catalogue folder tree is materialised for each filmed project.
    from app.modules.documents.models import DocumentFolder

    async with factory() as s:
        for demo_id in filmed:
            folders = (
                await s.execute(
                    select(func.count())
                    .select_from(DocumentFolder)
                    .where(DocumentFolder.project_id == projects[demo_id].id)
                )
            ).scalar_one()
            assert folders > 0, f"{demo_id}: the data room has no folders"
    warned = _install_warnings(caplog)
    assert not warned, warned[:20]
