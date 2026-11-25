"""Each cost rate shows the spread it was applied at and how many BOQ lines cite it.

Worked example: a brickwork rate (EUR) applied in BOQ lines at 10, 12.5 and
14 EUR, once with no captured currency at 11, once in USD at 99, and once in
an assembly at 50. Five BOQ lines cite it; the EUR spread is min 10, max 14,
average (10 + 12.5 + 14 + 11) / 4 = 11.875. The USD line and the assembly use
stay out of the spread.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.costs.intelligence import CostUsageRecorder, applied_rate_stats
from tests._pg import transactional_session


async def _item(session) -> uuid.UUID:  # noqa: ANN001
    from app.modules.costs.models import CostItem

    item = CostItem(
        id=uuid.uuid4(),
        code=f"BRK-{uuid.uuid4().hex[:6]}",
        description="Brickwork",
        unit="m2",
        rate="12.00",
        currency="EUR",
        source="custom",
        components=[],
    )
    session.add(item)
    await session.flush()
    return item.id


@pytest.mark.asyncio
async def test_spread_and_citations_follow_the_worked_example() -> None:
    async with transactional_session() as session:
        item_id = await _item(session)
        unused = await _item(session)
        project = uuid.uuid4()
        rec = CostUsageRecorder(session)
        for rate, cur in (("10", "EUR"), ("12.5", "eur"), ("14", "EUR"), ("11", None), ("99", "USD")):
            await rec.record(item_id, project_id=project, unit_rate_at_use=Decimal(rate), currency_at_use=cur)
        await rec.record(item_id, project_id=project, unit_rate_at_use=Decimal("50"), context="assembly")

        stats = await applied_rate_stats(session, [item_id, unused], {project})

        assert set(stats) == {str(item_id)}
        row = stats[str(item_id)]
        assert row["boq_lines"] == 5
        assert row["rate_count"] == 4
        assert Decimal(row["min"]) == Decimal("10")
        assert Decimal(row["max"]) == Decimal("14")
        assert row["avg"] == "11.8750"
        assert row["currency"] == "EUR"


@pytest.mark.asyncio
async def test_no_ids_answers_nothing() -> None:
    async with transactional_session() as session:
        assert await applied_rate_stats(session, [], None) == {}
        assert await applied_rate_stats(session, [uuid.uuid4()], set()) == {}


@pytest.mark.asyncio
async def test_another_tenants_applications_never_move_my_stats() -> None:
    async with transactional_session() as session:
        item_id = await _item(session)
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        rec = CostUsageRecorder(session)
        await rec.record(item_id, project_id=mine, unit_rate_at_use=Decimal("10"), currency_at_use="EUR")
        before = await applied_rate_stats(session, [item_id], {mine})
        for rate in ("1", "500", "9999"):
            await rec.record(item_id, project_id=theirs, unit_rate_at_use=Decimal(rate), currency_at_use="EUR")
        after = await applied_rate_stats(session, [item_id], {mine})
        assert after == before
        assert after[str(item_id)]["boq_lines"] == 1
        assert after[str(item_id)]["max"] == "10.0000"
        assert await applied_rate_stats(session, [item_id], {uuid.uuid4()}) == {}
