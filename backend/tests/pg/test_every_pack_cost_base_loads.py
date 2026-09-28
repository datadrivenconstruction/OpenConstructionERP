# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every cost base a pack points at loads, loads once, and fits the server floor.

A country pack names its cost bases as ``cwicr_regions`` slugs, and the one-click
installer resolves each slug to a loader id and imports that base. The import
step is fail-soft: a region that does not resolve, or whose download or import
raises, comes back as ``skipped`` and the install still reports ``ok``. So the
only way to know that a pack's cost step does what the dialog says is to run the
loader for every id the packs resolve to, which is what this file does.

It is also where the memory claim in CLAUDE.md principle 1 gets measured rather
than repeated: the core has to live on a 3 GB server, the app with every module
takes about 800 MB, PostgreSQL 200 to 400 MB beside it, and the country cost
pack import is the peak on top. Each load here records the Python process's own
high-water mark for the duration of the import (Linux ``clear_refs`` + ``VmHWM``,
so collection and earlier tests do not count) and the largest PostgreSQL backend
next to it, prints both, and fails when the import alone would not fit.

Gated behind ``OE_COST_BASE_MATRIX=1``: it downloads a parquet per base from
GitHub. ``OE_COST_BASE_SHARD`` (``"k/n"``) splits it, and ``OE_COST_BASE_IDS``
(comma separated) narrows it to named ids.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKS_DIR = REPO_ROOT / "packs"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("OE_COST_BASE_MATRIX", "") != "1",
        reason="cost base matrix only - set OE_COST_BASE_MATRIX=1 (downloads from GitHub)",
    ),
]

_MIB = 1024 * 1024
# The floor from CLAUDE.md principle 1: 3 GB, minus the app with every module
# loaded (~800 MB) and PostgreSQL beside it (up to 400 MB). What is left is what
# one import may add on top of an idle app.
_IMPORT_BUDGET_MIB = 3 * 1024 - 800 - 400


def _manifests() -> list:
    out = []
    for path in sorted(PACKS_DIR.glob("*/src/openconstructionerp_*/manifest.py")):
        if any(path.parents[2].rglob("DEPRECATED.txt")):
            continue
        name = f"_cost_matrix_manifest_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        out.append(module.MANIFEST)
    return out


def _db_ids() -> list[str]:
    """Every loader id a shipped pack's ``cwicr_regions`` resolves to."""
    from app.core.partner_pack.full_install import resolve_cwicr_db_id

    ids = sorted({db for m in _manifests() for r in m.cwicr_regions if (db := resolve_cwicr_db_id(r))})
    only = {x.strip() for x in os.environ.get("OE_COST_BASE_IDS", "").split(",") if x.strip()}
    if only:
        ids = [i for i in ids if i in only]
    raw = os.environ.get("OE_COST_BASE_SHARD", "").strip()
    if raw:
        k, n = (int(x) for x in raw.split("/"))
        ids = [it for i, it in enumerate(ids) if i % n == k - 1]
    return ids


DB_IDS = _db_ids() if os.environ.get("OE_COST_BASE_MATRIX", "") == "1" else []


# ── Memory probes (Linux /proc) ─────────────────────────────────────────────


def _status_kib(pid: str, field: str) -> int:
    for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    return 0


def _postgres_pids() -> list[str]:
    out = []
    for p in pathlib.Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if (p / "comm").read_text().strip() == "postgres":
                    out.append(p.name)
            except OSError:
                continue
    return out


def _reset_peaks(pids: list[str]) -> None:
    """Make ``VmHWM`` start again from the current RSS (``clear_refs`` mode 5)."""
    for pid in pids:
        try:
            pathlib.Path(f"/proc/{pid}/clear_refs").write_text("5")
        except OSError:
            continue


# ── Fresh database per base ─────────────────────────────────────────────────


@pytest_asyncio.fixture
async def fresh_db(pg_async_url, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import Base

    base = make_url(pg_async_url)
    admin = create_engine(base.set(drivername="postgresql+psycopg2"), isolation_level="AUTOCOMMIT")
    name = f"oe_cost_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    sync = create_engine(base.set(drivername="postgresql+psycopg2", database=name))
    Base.metadata.create_all(sync)
    sync.dispose()
    eng = create_async_engine(base.set(database=name), poolclass=NullPool)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_the_matrix_is_not_empty() -> None:
    assert len(DB_IDS) > 0 or os.environ.get("OE_COST_BASE_SHARD"), "no pack resolves to any cost base"


@pytest.mark.timeout(1800)
@pytest.mark.parametrize("db_id", DB_IDS)
async def test_the_cost_base_loads_once_and_fits_the_floor(db_id: str, fresh_db) -> None:
    from app.modules.costs.models import CostItem
    from app.modules.costs.router import load_cwicr_region

    factory = fresh_db
    linux = pathlib.Path("/proc/self/clear_refs").exists()

    pg_pids = _postgres_pids() if linux else []
    if linux:
        _reset_peaks(["self", *pg_pids])
        base_rss = _status_kib("self", "VmRSS")

    async with factory() as s:
        res = await load_cwicr_region(db_id, s)
        await s.commit()

    if linux:
        peak = _status_kib("self", "VmHWM")
        pg_peak = max((_status_kib(p, "VmHWM") for p in pg_pids), default=0)
        delta_mib = (peak - base_rss) / 1024
        print(
            f"\n[cost-base-memory] {db_id}: python rss before {base_rss / 1024:.0f} MiB, "
            f"peak {peak / 1024:.0f} MiB, import delta {delta_mib:.0f} MiB; "
            f"largest postgres backend peak {pg_peak / 1024:.0f} MiB; "
            f"items {res.get('imported') or res.get('total_items')}"
        )

    async with factory() as s:
        n = (await s.execute(select(func.count()).select_from(CostItem).where(CostItem.region == db_id))).scalar_one()
    assert n > 10, f"{db_id}: the loader returned {res} and left {n} cost items"

    # A second load of the same base is the re-activation path; it must not
    # import the base again.
    async with factory() as s:
        again = await load_cwicr_region(db_id, s)
        await s.commit()
    async with factory() as s:
        n2 = (await s.execute(select(func.count()).select_from(CostItem).where(CostItem.region == db_id))).scalar_one()
    assert n2 == n, f"{db_id}: a second load changed the item count {n} -> {n2} ({again})"

    if linux:
        assert delta_mib < _IMPORT_BUDGET_MIB, (
            f"{db_id}: the import added {delta_mib:.0f} MiB to the process, over the "
            f"{_IMPORT_BUDGET_MIB} MiB the 3 GB floor leaves for it"
        )
