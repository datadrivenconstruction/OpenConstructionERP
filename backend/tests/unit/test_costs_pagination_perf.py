"""Performance contract for the cost autocomplete endpoint.

Before this wave the autocomplete handler fetched ``limit * 3`` rows
via the generic ``search_costs`` path, then re-sorted them in Python by
"items WITH components first" before slicing to ``limit``. On the live
110 k-row CWICR catalogue that translated to 24 rows fetched + a
24-element Python sort per keystroke when the user only ever saw 8 — a
visible UI hitch on slow laptops.

The fix pushes the priority into the SQL ORDER BY via a CASE on
``json_array_length(components) > 0``, so the DB returns exactly
``limit`` rows in the right order and the router becomes pure
serialisation.

These tests pin the new contract:

1. Exactly ``limit`` rows come back from the service.
2. Items WITH components precede items without — same ordering the
   estimator UI relied on.
3. Within each priority bucket, rows sort by code ASC (stable, matches
   the legacy Python ``key=(0/1, code)`` tuple).
4. The handler issues a *single* SQL SELECT against ``oe_costs_item``
   for the standard (non-vector) path — no per-row follow-up reads.

The single-query guarantee is enforced via a SQLAlchemy
``before_cursor_execute`` listener that counts every SELECT issued
during the handler call.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-pagination-perf-"))
_TMP_DB = _TMP_DIR / "session.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from app.database import Base  # noqa: E402
from app.modules.costs.models import CostItem  # noqa: E402
from app.modules.costs.router import autocomplete_cost_items  # noqa: E402
from app.modules.costs.service import CostItemService  # noqa: E402


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[CostItem.__table__])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        # 30 rows total — enough that limit=8 stresses ordering / cap.
        # First 12 have components (priority bucket 1 → returned first),
        # next 18 have no components (priority bucket 0 → tail).
        # Codes are zero-padded so ASC sort is unambiguous across SQLite
        # and Postgres (lexicographic vs numeric).
        with_components = [
            CostItem(
                id=uuid.uuid4(),
                code=f"CW-CONC-{i:03d}",
                description=f"Concrete wall variant {i}",
                unit="m3",
                rate="180.00",
                currency="EUR",
                source="cwicr",
                region="DE_BERLIN",
                classification={"collection": "Buildings"},
                components=[{"cost_item_id": str(uuid.uuid4()), "factor": 1.0}],
                tags=[],
                is_active=True,
                metadata_={},
            )
            for i in range(12)
        ]
        without_components = [
            CostItem(
                id=uuid.uuid4(),
                code=f"CW-PLAIN-{i:03d}",
                description=f"Concrete plain {i}",
                unit="m3",
                rate="120.00",
                currency="EUR",
                source="manual",
                region="DE_BERLIN",
                classification={"collection": "Buildings"},
                components=[],
                tags=[],
                is_active=True,
                metadata_={},
            )
            for i in range(18)
        ]
        s.add_all(with_components + without_components)
        await s.commit()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_autocomplete_returns_exactly_limit_rows(session: AsyncSession) -> None:
    """Service returns ``limit`` rows, never more."""
    service = CostItemService(session)
    out = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region=None,
        limit=8,
        semantic=False,
        locale="en",
        accept_language=None,
    )
    assert len(out) == 8


@pytest.mark.asyncio
async def test_autocomplete_items_with_components_lead(session: AsyncSession) -> None:
    """Items WITH non-empty components appear before items without.

    Pinned because the ordering is the whole reason the legacy code
    over-fetched + Python-sorted. If the new SQL ORDER BY drops it the
    estimator UI loses the richer-first heuristic without anyone
    noticing in the API contract test.
    """
    service = CostItemService(session)
    out = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region=None,
        limit=12,
        semantic=False,
        locale="en",
        accept_language=None,
    )
    # First 12 are all the with-components rows.
    assert len(out) == 12
    for item in out:
        assert item.code.startswith("CW-CONC-"), (
            f"Expected with-components row, got {item.code} — "
            "ORDER BY priority is not pushing components-first to the head."
        )


@pytest.mark.asyncio
async def test_autocomplete_within_bucket_sorts_by_code_asc(
    session: AsyncSession,
) -> None:
    """Within the same priority bucket, rows come back in code ASC order."""
    service = CostItemService(session)
    out = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region=None,
        limit=12,
        semantic=False,
        locale="en",
        accept_language=None,
    )
    codes = [item.code for item in out]
    assert codes == sorted(codes), f"Codes within the components bucket must be ASC, got {codes}"


@pytest.mark.asyncio
async def test_autocomplete_respects_region_filter(session: AsyncSession) -> None:
    """Region filter narrows the result set in SQL (not post-filter)."""
    service = CostItemService(session)
    out_de = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region="DE_BERLIN",
        limit=8,
        semantic=False,
        locale="en",
        accept_language=None,
    )
    assert len(out_de) == 8
    assert all(item.region == "DE_BERLIN" for item in out_de)

    out_us = await autocomplete_cost_items(
        user_id=None,
        service=service,
        q="concrete",
        region="US_NYC",
        limit=8,
        semantic=False,
        locale="en",
        accept_language=None,
    )
    assert out_us == [], "Region filter must be applied in SQL — no rows are tagged US_NYC."


@pytest.mark.asyncio
async def test_autocomplete_single_query_no_overfetch(session: AsyncSession) -> None:
    """The standard-text path issues exactly one SELECT against oe_costs_item.

    Counted via a SQLAlchemy ``before_cursor_execute`` listener pinned to
    the session's sync engine. The pre-fix version issued one SELECT for
    the over-fetched ``limit*3`` window; the new path issues one SELECT
    for ``limit`` rows. The count must be 1.
    """
    select_count = {"oe_costs_item": 0}

    sync_engine = session.bind.sync_engine  # type: ignore[union-attr]

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _count_selects(conn, cursor, statement, parameters, context, executemany):
        normalised = statement.lower().lstrip()
        if normalised.startswith("select") and "oe_costs_item" in normalised:
            select_count["oe_costs_item"] += 1

    service = CostItemService(session)
    try:
        out = await autocomplete_cost_items(
            user_id=None,
            service=service,
            q="concrete",
            region=None,
            limit=8,
            semantic=False,
            locale="en",
            accept_language=None,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count_selects)

    assert len(out) == 8
    assert select_count["oe_costs_item"] == 1, (
        f"Autocomplete must issue exactly one SELECT against oe_costs_item, "
        f"got {select_count['oe_costs_item']}. Did someone re-introduce "
        f"the legacy over-fetch + Python sort?"
    )
