"""Fuzzy (trigram) cost-item search.

Cost search upgraded from plain substring (ILIKE) matching to fuzzy, ranked
search using PostgreSQL's pg_trgm extension (``similarity`` / ``word_similarity``).
These tests pin the behaviour that matters:

* a typo or reordered query still finds the item via trigram recall + ranking;
* exact and prefix hits rank above looser trigram matches;
* the offset cursor round-trips so cursor-based clients keep paging;
* the path falls back cleanly to substring matching when fuzzy is off, and plain
  substring recall never regresses.

Isolation uses the shared PostgreSQL transactional session
(``tests._pg.transactional_session``): each test runs inside an outer
transaction rolled back on teardown. pg_trgm is created inside that transaction
(and rolled back with it), so a test that needs the extension calls
``_ensure_pg_trgm`` which skips gracefully when the cluster cannot install it.
The cached availability probe is reset around every test so one test's in-
transaction extension never leaks into another.

Run:
    cd backend
    python -m pytest tests/unit/test_cost_fuzzy_search.py -v --tb=short
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.modules.costs.models import CostItem
from app.modules.costs.repository import pg_trgm_available, reset_trgm_probe
from app.modules.costs.schemas import CostSearchQuery
from app.modules.costs.service import CostItemService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _reset_trgm_probe():
    # The probe caches pg_trgm availability for the process. Reset it around
    # each test so an extension created (and rolled back) inside one test never
    # poisons another test's fallback path.
    reset_trgm_probe()
    yield
    reset_trgm_probe()


async def _ensure_pg_trgm(session) -> None:
    """Create pg_trgm in the test transaction, or skip when it cannot be installed."""
    try:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception as exc:  # pragma: no cover - depends on the cluster build
        pytest.skip(f"pg_trgm not installable in this test database: {exc}")
    reset_trgm_probe()  # re-probe now that the extension exists on this connection


async def _add_item(session, *, code, description, region="DE_TEST", rate="100.00"):
    item = CostItem(
        code=code,
        description=description,
        unit="m3",
        rate=rate,
        currency="EUR",
        source="cwicr",
        region=region,
        is_active=True,
    )
    session.add(item)
    await session.flush()
    return item


async def _codes(svc: CostItemService, **query_kwargs) -> list[str]:
    items, _total, _has_more, _next = await svc.search_costs_paginated(CostSearchQuery(**query_kwargs))
    return [i.code for i in items]


# ── recall: typos and word order ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuzzy_matches_reordered_query(session):
    await _ensure_pg_trgm(session)
    await _add_item(session, code="C-001", description="Reinforced concrete wall C30/37")
    await _add_item(session, code="C-002", description="Timber floor joist 45x220")

    svc = CostItemService(session)
    codes = await _codes(svc, q="wall concrete", fuzzy=True, limit=10)

    # "wall concrete" is NOT a substring of "concrete wall", so this only
    # matches via trigram similarity - proving fuzzy adds word-order tolerance.
    assert "C-001" in codes
    assert "C-002" not in codes


@pytest.mark.asyncio
async def test_fuzzy_tolerates_typo(session):
    await _ensure_pg_trgm(session)
    await _add_item(session, code="P-100", description="Concrete foundation footing")

    svc = CostItemService(session)

    # "concreet foundation" is not a substring, so only trigram recall finds it.
    assert "P-100" in await _codes(svc, q="concreet foundation", fuzzy=True, limit=10)
    # With fuzzy off the same typo yields nothing (pure ILIKE substring).
    assert "P-100" not in await _codes(svc, q="concreet foundation", fuzzy=False, limit=10)


# ── ranking ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_and_prefix_rank_above_fuzzy(session):
    await _ensure_pg_trgm(session)
    await _add_item(session, code="EX", description="concrete")  # exact
    await _add_item(session, code="PFX", description="concrete wall panel")  # prefix
    await _add_item(session, code="FUZ", description="precast concreted slab")  # looser match

    svc = CostItemService(session)
    order = await _codes(svc, q="concrete", fuzzy=True, limit=10)

    assert order.index("EX") < order.index("PFX") < order.index("FUZ")


# ── pagination: offset cursor round-trip ─────────────────────────────────────


@pytest.mark.asyncio
async def test_fuzzy_offset_cursor_pagination(session):
    await _ensure_pg_trgm(session)
    for i in range(5):
        await _add_item(session, code=f"W-{i:02d}", description=f"Concrete wall type {i}")

    svc = CostItemService(session)
    page1, total, has_more, next_cursor = await svc.search_costs_paginated(
        CostSearchQuery(q="concrete wall", fuzzy=True, limit=2)
    )
    assert len(page1) == 2
    assert total == 5  # all five recalled, counted on the first page
    assert has_more is True
    assert next_cursor is not None

    page2, total2, _has_more2, _next2 = await svc.search_costs_paginated(
        CostSearchQuery(q="concrete wall", fuzzy=True, limit=2, cursor=next_cursor)
    )
    assert len(page2) == 2
    # Second page (cursor present) omits the total, matching the keyset contract.
    assert total2 is None
    # Pages do not overlap.
    assert not ({i.code for i in page1} & {i.code for i in page2})


@pytest.mark.asyncio
async def test_fuzzy_rejects_malformed_cursor(session):
    await _ensure_pg_trgm(session)
    await _add_item(session, code="X-1", description="Concrete beam")

    svc = CostItemService(session)
    with pytest.raises(Exception) as excinfo:
        await svc.search_costs_paginated(CostSearchQuery(q="concrete", fuzzy=True, cursor="not-a-cursor"))
    # Maps to a 400 so the client drops the bookmark and refetches page 1.
    assert getattr(excinfo.value, "status_code", None) == 400


# ── fallback: fuzzy off / substring recall never regresses ───────────────────


@pytest.mark.asyncio
async def test_fuzzy_off_uses_substring(session):
    await _ensure_pg_trgm(session)  # extension present, but fuzzy is off
    await _add_item(session, code="S-1", description="Steel beam IPE 200")

    svc = CostItemService(session)
    items, _total, _has_more, next_cursor = await svc.search_costs_paginated(
        CostSearchQuery(q="steel beam", fuzzy=False, limit=10)
    )
    assert "S-1" in [i.code for i in items]
    # The non-fuzzy path uses the keyset cursor; a single match has no next page.
    assert next_cursor is None


@pytest.mark.asyncio
async def test_substring_recall_never_regresses(session):
    # With fuzzy ON, a plain substring query must still return the row whether or
    # not pg_trgm is installed (fuzzy recall is a superset of ILIKE). This test
    # deliberately does NOT create the extension, exercising the runtime fallback.
    reset_trgm_probe()
    await _add_item(session, code="F-1", description="Brick masonry wall")

    svc = CostItemService(session)
    assert "F-1" in await _codes(svc, q="masonry", fuzzy=True, limit=10)


@pytest.mark.asyncio
async def test_probe_reports_absent_extension_as_false(session):
    # A create_all database without the migration has no pg_trgm; the probe must
    # report that honestly so callers use the ILIKE path.
    reset_trgm_probe()
    if await pg_trgm_available(session):
        pytest.skip("pg_trgm is preinstalled in this database; absent-path not exercised")
    assert await pg_trgm_available(session) is False
