"""MISC-05: a base total never combines unconvertible currencies."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.boq.service import (
    _detect_resource_fx_warnings,
    _leaf_total_base_with_resources,
    _position_total_in_base,
    _resource_total_in_base,
)


@pytest.mark.parametrize("bad_rate", [None, "0", "-2", "nan", "inf", "abc", ""])
def test_unusable_fx_excludes_foreign_money_but_preserves_base_and_credits(bad_rate):
    rates = {} if bad_rate is None else {"USD": bad_rate}
    resources = [
        {"quantity": 2, "unit_rate": 10, "currency": "EUR"},
        {"quantity": 1, "unit_rate": -3, "currency": "EUR"},
        {"quantity": 3, "unit_rate": 100, "currency": "USD"},
    ]
    assert _resource_total_in_base(resources, rates, "EUR") == Decimal("17")
    assert _position_total_in_base("-100", "USD", rates, "EUR") == 0
    assert _detect_resource_fx_warnings(resources, rates, "EUR") == ["USD"]
    pos = SimpleNamespace(quantity="0.5", total="317", metadata_={"resources": resources})
    assert _leaf_total_base_with_resources(pos, rates, "EUR") == Decimal("8.5")


def test_usable_fx_preserves_credit_and_does_not_apply_twice():
    rates = {"USD": "0.8", "EUR": "99"}
    assert _position_total_in_base("-100", " usd ", rates, "EUR") == Decimal("-80")
    assert _position_total_in_base("100", " eur ", rates, "EUR") == Decimal("100")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_rate", [None, "0", "-1", "abc"])
async def test_summary_separates_missing_amounts_including_credit_and_repeated_names(monkeypatch, bad_rate):
    from app.modules.boq import router

    monkeypatch.setattr(router, "_verify_boq_owner", AsyncMock())
    resources = [
        {"name": "Shared", "type": "material", "quantity": 1, "unit_rate": 10, "currency": "EUR"},
        {"name": "Shared", "type": "material", "quantity": 1, "unit_rate": 100, "currency": "USD"},
        {"name": "Shared", "type": "material", "quantity": 1, "unit_rate": -20, "currency": "USD"},
        {"name": "Shared", "type": "material", "quantity": 1, "unit_rate": 30, "currency": "JPY"},
        {"name": "Converted", "type": "labor", "quantity": 1, "unit_rate": 40, "currency": "GBP"},
    ]
    positions = [SimpleNamespace(id=uuid4(), quantity="0.5", metadata={"resources": resources})]
    rates = {"GBP": "2"}
    if bad_rate is not None:
        rates["USD"] = bad_rate
    service = SimpleNamespace(
        get_boq_with_positions=AsyncMock(return_value=SimpleNamespace(positions=positions)),
        get_export_fx=AsyncMock(return_value=("EUR", rates)),
    )
    result = await router.get_resource_summary(uuid4(), uuid4(), {}, None, service)
    assert result.grand_total == Decimal("45")  # 5 EUR + 20 GBP * 2
    assert result.unconverted == {"JPY": Decimal("15"), "USD": Decimal("40")}
    assert sum(x.total_cost for x in result.resources) == result.grand_total
    assert sum(x.total_cost for x in result.by_type.values()) == result.grand_total
    assert sum(x.abc_percentage for x in result.resources) == pytest.approx(100)
    assert result.model_dump(mode="json")["unconverted"] == {"JPY": "15", "USD": "40.00"}


@pytest.mark.asyncio
async def test_cost_breakdown_never_allocates_convertible_money_to_a_missing_fx_resource():
    from app.modules.boq.service import BOQService

    pos = SimpleNamespace(
        id=uuid4(),
        unit="m",
        quantity="2",
        unit_rate="110",
        total="220",
        description="Mixed scope",
        metadata_={
            "resources": [
                {"name": "Known", "type": "labor", "quantity": 1, "unit_rate": 10, "currency": "EUR"},
                {"name": "Missing", "type": "material", "quantity": 1, "unit_rate": 100, "currency": "USD"},
            ]
        },
    )
    service = BOQService(AsyncMock())
    service.boq_repo = SimpleNamespace(get_header=AsyncMock(return_value=SimpleNamespace()))
    service.position_repo = SimpleNamespace(list_all_for_boq=AsyncMock(return_value=[pos]))
    service.markup_repo = SimpleNamespace(list_for_boq=AsyncMock(return_value=[]))
    service._resolve_project_fx = AsyncMock(return_value=("EUR", {}))
    result = await service.get_cost_breakdown(uuid4())
    assert result.grand_total == Decimal("20")
    assert [(r.name, r.total_cost) for r in result.top_resources] == [("Known", Decimal("20"))]
    assert sum(c.amount for c in result.categories) == result.grand_total
