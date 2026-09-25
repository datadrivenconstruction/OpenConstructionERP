"""PG: a search does not offer an asbestos item ahead of an ordinary one.

Searching the cost database for "frame walls" returned a wall clad in
chrysotile (asbestos) cement sheets as a top hit. Such items stay in the data,
because removal and refurbishment work is priced from them, but they rank after
every ordinary hit and carry a hazard marker. The words that mark a hazard come
from ``hazard_terms.json`` in every language the databases ship in, matched so
that a capitalised Cyrillic word is caught under any database locale.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.costs.models import CostItem
from app.modules.costs.repository import CostItemRepository

pytestmark = pytest.mark.asyncio

REGION = "ZZ_HAZARDTEST"


async def _seed(session) -> None:
    rows = [
        # A prefix match, so relevance alone would rank it first.
        ("H-001", "frame walls clad with chrysotile cement sheets"),
        ("H-002", "Timber frame walls, studs 50x100"),
        # Capitalised Cyrillic: a C-locale LOWER() would not fold the capital.
        ("H-003", "Асбестоцементные листы на frame walls"),
    ]
    for code, description in rows:
        session.add(
            CostItem(
                id=uuid.uuid4(),
                code=code,
                description=description,
                unit="m2",
                rate="100.00",
                currency="EUR",
                source="test",
                region=REGION,
                is_active=True,
            )
        )
    await session.flush()


async def test_the_relevance_search_ranks_hazards_last(pg_session) -> None:
    await _seed(pg_session)
    repo = CostItemRepository(pg_session)
    if not await repo.fuzzy_search_enabled("frame walls", True):
        pytest.skip("pg_trgm is not installed on this cluster; the relevance path is not taken")

    items, _total, _more = await repo.search(q="frame walls", region=REGION, fuzzy=True, limit=10)

    assert [i.code for i in items] == ["H-002", "H-001", "H-003"]


async def test_the_autocomplete_ranks_hazards_last(pg_session) -> None:
    await _seed(pg_session)

    items = await CostItemRepository(pg_session).search_for_autocomplete(q="frame walls", region=REGION, limit=8)

    assert [i.code for i in items][0] == "H-002"
    assert {i.code for i in items[1:]} == {"H-001", "H-003"}
