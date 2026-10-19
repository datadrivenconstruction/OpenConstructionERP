# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``POST /contracts/price-adjustment/compute/`` reads indices from the request or a cost-index series.

The endpoint stores nothing: it computes one settlement and a person raises
the claim. An index it cannot find, or a coefficient set the law refuses, is a
422 that names the problem, never a figure computed on a guess.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.contracts.router import compute_price_adjustment, list_price_adjustment_regimes
from app.modules.contracts.schemas import PriceAdjustmentComputeRequest

pytestmark = pytest.mark.asyncio


class _Points:
    """Answers the one ``select(CostIndexPoint)`` with the points of the series it was asked for."""

    def __init__(self, points: dict[uuid.UUID, dict[str, str]]) -> None:
        self._points = points

    async def execute(self, statement: Any) -> Any:
        params = statement.compile().params
        series = next(v for v in params.values() if isinstance(v, uuid.UUID))
        rows = [SimpleNamespace(period=p, factor=Decimal(f)) for p, f in self._points.get(series, {}).items()]
        return SimpleNamespace(scalars=lambda: rows)


async def test_index_values_sent_with_the_request() -> None:
    body = PriceAdjustmentComputeRequest(
        regime="eg_law182_art97",
        value_subject=Decimal("10000000"),
        coefficients=[
            {"item": "cement", "coefficient": "0.15", "base_index": "200", "current_index": "230"},
            {"item": "steel", "coefficient": "0.25", "base_index": "300", "current_index": "270"},
            {"item": "labour", "coefficient": "0.20", "base_index": "150", "current_index": "165"},
        ],
    )
    result = await compute_price_adjustment(body, _Points({}), "user")
    assert result.total == "175000.00"
    assert result.fixed_portion == "0.40"


async def test_index_values_read_from_a_series() -> None:
    steel = uuid.uuid4()
    session = _Points({steel: {"2026-01": "300", "2026-04": "330"}})
    body = PriceAdjustmentComputeRequest(
        regime="eg_law182_art97",
        value_subject=Decimal("1000000"),
        coefficients=[{"item": "steel", "coefficient": "0.4", "index_series_id": str(steel)}],
        base_period="2026-01",
        current_period="2026-04",
    )
    result = await compute_price_adjustment(body, session, "user")
    assert result.total == "40000.00"


async def test_a_period_the_series_lacks_is_refused() -> None:
    steel = uuid.uuid4()
    body = PriceAdjustmentComputeRequest(
        regime="eg_law182_art97",
        value_subject=Decimal("1000000"),
        coefficients=[{"item": "steel", "coefficient": "0.4", "index_series_id": str(steel)}],
        base_period="2026-01",
        current_period="2026-04",
    )
    with pytest.raises(HTTPException) as caught:
        await compute_price_adjustment(body, _Points({steel: {"2026-01": "300"}}), "user")
    assert caught.value.status_code == 422
    assert caught.value.detail["problem"] == "missing_index"


async def test_a_coefficient_sum_of_one_is_refused() -> None:
    body = PriceAdjustmentComputeRequest(
        regime="eg_law182_art97",
        value_subject=Decimal("1000"),
        coefficients=[{"item": "steel", "coefficient": "1", "base_index": "100", "current_index": "110"}],
    )
    with pytest.raises(HTTPException) as caught:
        await compute_price_adjustment(body, _Points({}), "user")
    assert caught.value.detail["problem"] == "coefficient_sum_not_below_one"


async def test_the_regimes_are_listed_with_their_source() -> None:
    regimes = {r["code"]: r for r in await list_price_adjustment_regimes("user")}
    assert {"eg_law182_art97", "contract_indexation"} <= set(regimes)
    assert "Law No. 182 of 2018" in regimes["eg_law182_art97"]["statute"]
