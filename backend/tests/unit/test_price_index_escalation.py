# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service tests for the price-index "escalate stored rates" preview.

These stand up a real (throwaway PostgreSQL) session, seed one cost-index
series plus a handful of cost items with known ``price_as_of`` capture dates,
and assert that :meth:`PriceIndexService.escalate_stored_rates` returns the
expected escalated rates and correctly flags the items it cannot escalate
(null ``price_as_of``, unparseable rate, or a period the series does not
carry). Escalation is read-only, so nothing is written back to the items.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.models import CostItem
from app.modules.price_index.models import CostIndexPoint, CostIndexSeries
from app.modules.price_index.schemas import EscalatePreviewRequest
from app.modules.price_index.service import (
    AmbiguousSeriesError,
    PriceIndexService,
    SeriesNotFoundError,
)
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


async def _make_series(session: AsyncSession, name: str = "Test Index") -> CostIndexSeries:
    """Insert a small rising index: 2019-01 -> 1.0, 2023-01 -> 1.24, 2026-01 -> 1.4."""
    series = CostIndexSeries(name=name, description="")
    session.add(series)
    await session.flush()
    for period, factor in (("2019-01", "1.000000"), ("2023-01", "1.240000"), ("2026-01", "1.400000")):
        session.add(CostIndexPoint(series_id=series.id, period=period, factor=D(factor)))
    await session.flush()
    return series


async def _make_item(
    session: AsyncSession,
    *,
    code: str,
    rate: str,
    price_as_of: date | None,
    region: str | None = None,
    classification: dict | None = None,
) -> CostItem:
    item = CostItem(
        code=code,
        description=f"Item {code}",
        unit="m3",
        rate=rate,
        currency="EUR",
        region=region,
        price_as_of=price_as_of,
        classification=classification or {},
    )
    session.add(item)
    await session.flush()
    return item


async def test_escalate_stored_rates_by_ids_computes_and_flags(session: AsyncSession) -> None:
    """Known dates + a known series give the expected escalated rates.

    The null-``price_as_of`` item, the unparseable-rate item and the item whose
    capture month is absent from the series are all returned flagged, never
    guessed, so a single bad item does not void the batch.
    """
    series = await _make_series(session)
    fresh = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10))
    mid = await _make_item(session, code="B", rate="80.00", price_as_of=date(2023, 1, 5))
    no_date = await _make_item(session, code="C", rate="50.00", price_as_of=None)
    off_series = await _make_item(session, code="D", rate="70.00", price_as_of=date(2010, 1, 1))
    bad_rate = await _make_item(session, code="E", rate="not-a-number", price_as_of=date(2019, 1, 1))

    service = PriceIndexService(session)
    request = EscalatePreviewRequest(
        target_date=date(2026, 1, 15),
        series_id=series.id,
        cost_item_ids=[fresh.id, mid.id, no_date.id, off_series.id, bad_rate.id],
    )
    response = await service.escalate_stored_rates(request)

    assert response.series_id == series.id
    assert response.target_period == "2026-01"
    assert response.item_count == 5
    assert response.escalatable_count == 2

    lines = {line.code: line for line in response.results}

    # A: 2019-01 (1.0) -> 2026-01 (1.4) => factor 1.4, 100.00 * 1.4 = 140.00
    a = lines["A"]
    assert a.escalatable is True
    assert a.base_rate == D("100.00")
    assert a.base_date == date(2019, 1, 10)
    assert a.base_period == "2019-01"
    assert a.factor == D("1.400000")
    assert a.escalated_rate == D("140.00")
    assert a.note is None

    # B: 2023-01 (1.24) -> 2026-01 (1.4) => 1.4/1.24 = 1.129032, 80 * 1.129032 = 90.32
    b = lines["B"]
    assert b.escalatable is True
    assert b.factor == D("1.129032")
    assert b.escalated_rate == D("90.32")

    # C: no price_as_of -> flagged, nothing computed
    c = lines["C"]
    assert c.escalatable is False
    assert c.base_date is None
    assert c.factor is None
    assert c.escalated_rate is None
    assert c.note is not None and "price_as_of" in c.note

    # D: capture month absent from the series -> flagged with the missing period
    d = lines["D"]
    assert d.escalatable is False
    assert d.base_period == "2010-01"
    assert d.factor is None
    assert d.escalated_rate is None
    assert d.note is not None and "2010-01" in d.note

    # E: unparseable rate -> flagged, no base rate
    e = lines["E"]
    assert e.escalatable is False
    assert e.base_rate is None
    assert e.escalated_rate is None
    assert e.note is not None and "not a number" in e.note


async def test_escalate_serializes_decimals_as_strings(session: AsyncSession) -> None:
    """Every factor / money field must cross the wire as a plain string."""
    series = await _make_series(session)
    item = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10))

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(target_date=date(2026, 1, 15), series_id=series.id, cost_item_ids=[item.id])
    )
    dumped = response.model_dump(mode="json")
    line = dumped["results"][0]
    assert line["base_rate"] == "100.00"
    assert line["factor"] == "1.400000"
    assert line["escalated_rate"] == "140.00"
    assert isinstance(line["escalated_rate"], str)


async def test_escalate_defaults_to_single_series_and_filters(session: AsyncSession) -> None:
    """With one series, series_id may be omitted; region + category select items."""
    series = await _make_series(session)
    in_scope = await _make_item(
        session,
        code="R1",
        rate="200.00",
        price_as_of=date(2019, 1, 1),
        region="DE_BERLIN",
        classification={"collection": "Concrete"},
    )
    # Different region - excluded by the region filter.
    await _make_item(
        session,
        code="R2",
        rate="200.00",
        price_as_of=date(2019, 1, 1),
        region="DE_MUNICH",
        classification={"collection": "Concrete"},
    )
    # Right region, different collection - excluded by the category filter.
    await _make_item(
        session,
        code="R3",
        rate="200.00",
        price_as_of=date(2019, 1, 1),
        region="DE_BERLIN",
        classification={"collection": "Steel"},
    )

    service = PriceIndexService(session)
    response = await service.escalate_stored_rates(
        EscalatePreviewRequest(target_date=date(2026, 1, 15), region="DE_BERLIN", category="Concrete")
    )

    assert response.series_id == series.id  # resolved the sole series
    assert response.item_count == 1
    assert response.results[0].cost_item_id == in_scope.id
    assert response.results[0].escalated_rate == D("280.00")  # 200 * 1.4


async def test_escalate_unknown_series_raises(session: AsyncSession) -> None:
    """A series id that does not exist is a not-found error."""
    import uuid

    await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10))
    service = PriceIndexService(session)
    with pytest.raises(SeriesNotFoundError):
        await service.escalate_stored_rates(
            EscalatePreviewRequest(
                target_date=date(2026, 1, 15),
                series_id=uuid.uuid4(),
                cost_item_ids=[uuid.uuid4()],
            )
        )


async def test_escalate_ambiguous_when_multiple_series_and_no_id(session: AsyncSession) -> None:
    """Omitting series_id with several series is ambiguous, not a silent pick."""
    await _make_series(session, name="Index One")
    await _make_series(session, name="Index Two")
    item = await _make_item(session, code="A", rate="100.00", price_as_of=date(2019, 1, 10))

    service = PriceIndexService(session)
    with pytest.raises(AmbiguousSeriesError):
        await service.escalate_stored_rates(
            EscalatePreviewRequest(target_date=date(2026, 1, 15), cost_item_ids=[item.id])
        )
