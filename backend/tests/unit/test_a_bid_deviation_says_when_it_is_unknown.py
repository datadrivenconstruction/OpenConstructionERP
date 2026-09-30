"""A bid total's deviation says when it could not be computed.

``compare_bids`` writes ``deviation_pct = 0.0`` for a bid it cannot compare
with the budget (a zero budget, or a bid in another currency). The tender
comparison export printed that as "0.0%", which reads as an exact match.
``deviation_known`` tells the two apart so a reader can print N/A.

The service runs without a database: the package and bids come from stubs and
``BOQService`` is replaced on its own module, since ``compare_bids`` imports it
inside the function body.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

import app.modules.boq.service as boq_service_module
from app.modules.tendering.service import TenderingService

PACKAGE_ID = uuid.uuid4()


def _bid(currency: str, amount: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        package_id=PACKAGE_ID,
        company_name=f"Bidder {currency} {amount}",
        total_amount=amount,
        currency=currency,
        status="submitted",
        line_items=[],
    )


def _service(monkeypatch: pytest.MonkeyPatch, budget_total: Decimal, bids: list[Any]) -> TenderingService:
    position = SimpleNamespace(
        id=uuid.uuid4(),
        quantity=Decimal("1"),
        unit_rate=budget_total,
        total=budget_total,
        description="Slab",
        unit="m3",
        ordinal="01",
        currency="EUR",
    )

    class _BOQ:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_boq_with_positions(self, _boq_id: Any) -> Any:
            return SimpleNamespace(positions=[position])

    monkeypatch.setattr(boq_service_module, "BOQService", _BOQ)

    async def _get_package(_package_id: Any) -> Any:
        return SimpleNamespace(id=PACKAGE_ID, name="Concrete", boq_id=uuid.uuid4(), metadata_={})

    async def _list_bids(_package_id: Any) -> list[Any]:
        return bids

    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace()
    svc.repo = SimpleNamespace(list_bids_for_package=_list_bids)
    svc.get_package = _get_package  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_a_same_currency_bid_carries_a_known_deviation(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(monkeypatch, Decimal("1000"), [_bid("EUR", "1100")])
    [total] = (await svc.compare_bids(PACKAGE_ID)).bid_totals
    assert total["deviation_known"] is True
    assert total["deviation_pct"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_a_bid_in_another_currency_is_marked_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(monkeypatch, Decimal("1000"), [_bid("USD", "1100")])
    [total] = (await svc.compare_bids(PACKAGE_ID)).bid_totals
    assert total["deviation_known"] is False
    assert total["deviation_pct"] == 0.0


@pytest.mark.asyncio
async def test_a_zero_budget_is_marked_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(monkeypatch, Decimal("0"), [_bid("EUR", "1100")])
    [total] = (await svc.compare_bids(PACKAGE_ID)).bid_totals
    assert total["deviation_known"] is False
