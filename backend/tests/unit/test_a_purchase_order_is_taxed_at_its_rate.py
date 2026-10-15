"""A purchase order's tax follows its VAT rate (issue #515).

A new order used to keep a tax of 0 whatever the project's default VAT rate
said, and the tax could only be typed as an absolute amount. The order now
carries a rate: stated, it wins; left out together with the tax, the project's
default is used; an absolute tax stated without a rate is kept as before. The
database-backed half (the project lookup, the opt-in re-apply on drafts) lives
in ``tests/pg/test_orders_and_invoices_take_the_projects_vat.py``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.procurement import service as procurement_service
from app.modules.procurement.schemas import POCreate, POItemCreate, POUpdate
from tests.unit.test_procurement import PROJECT_ID, _make_service


@pytest.fixture
def project_rate(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    """The project's default VAT rate the service sees, settable per test."""
    holder: dict[str, str | None] = {"rate": None}

    async def _lookup(_session: Any, _project_id: Any) -> str | None:
        return holder["rate"]

    monkeypatch.setattr(procurement_service, "_project_default_vat_rate", _lookup)
    return holder


def _order(**overrides: Any) -> POCreate:
    data: dict[str, Any] = {
        "project_id": PROJECT_ID,
        "currency_code": "EUR",
        "items": [POItemCreate(description="Rebar", quantity="4", unit="t", unit_rate="250", amount="0")],
    }
    data.update(overrides)
    return POCreate(**data)


@pytest.mark.asyncio
async def test_an_order_without_rate_or_tax_takes_the_projects_rate(project_rate: dict[str, str | None]) -> None:
    project_rate["rate"] = "5"

    po = await _make_service().create_po(_order())

    assert po.tax_rate_pct == "5"
    assert Decimal(po.tax_amount) == Decimal("50.00")
    assert Decimal(po.amount_total) == Decimal("1050.00")


@pytest.mark.asyncio
async def test_a_stated_rate_wins(project_rate: dict[str, str | None]) -> None:
    project_rate["rate"] = "5"

    po = await _make_service().create_po(_order(tax_rate_pct="19"))

    assert po.tax_rate_pct == "19"
    assert Decimal(po.tax_amount) == Decimal("190.00")


@pytest.mark.asyncio
async def test_a_stated_tax_without_a_rate_is_kept(project_rate: dict[str, str | None]) -> None:
    project_rate["rate"] = "5"

    po = await _make_service().create_po(_order(tax_amount="7.50"))

    assert po.tax_rate_pct is None
    assert po.tax_amount == "7.50"


@pytest.mark.asyncio
async def test_no_project_rate_leaves_the_tax_at_zero(project_rate: dict[str, str | None]) -> None:
    po = await _make_service().create_po(_order())

    assert po.tax_rate_pct is None
    assert Decimal(po.tax_amount) == Decimal("0")


@pytest.mark.asyncio
async def test_new_lines_re_derive_the_tax_at_the_orders_rate(project_rate: dict[str, str | None]) -> None:
    project_rate["rate"] = "10"
    svc = _make_service()
    po = await svc.create_po(_order())

    updated = await svc.update_po(
        po.id,
        POUpdate(items=[POItemCreate(description="Rebar", quantity="8", unit="t", unit_rate="250", amount="0")]),
    )

    assert Decimal(updated.amount_subtotal) == Decimal("2000")
    assert Decimal(updated.tax_amount) == Decimal("200.00")
    assert Decimal(updated.amount_total) == Decimal("2200.00")


@pytest.mark.asyncio
async def test_an_absolute_tax_detaches_the_rate(project_rate: dict[str, str | None]) -> None:
    project_rate["rate"] = "10"
    svc = _make_service()
    po = await svc.create_po(_order())

    updated = await svc.update_po(po.id, POUpdate(tax_amount="33.00"))

    assert updated.tax_rate_pct is None
    assert updated.tax_amount == "33.00"
    assert Decimal(updated.amount_total) == Decimal("1033.00")


@pytest.mark.asyncio
async def test_an_approved_order_keeps_its_rate(project_rate: dict[str, str | None]) -> None:
    project_rate["rate"] = "10"
    svc = _make_service()
    po = await svc.create_po(_order())
    po.status = "approved"

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(tax_rate_pct="21"))

    assert exc.value.status_code == 409
    assert po.tax_rate_pct == "10"


@pytest.mark.parametrize("rate", ["-1", "100.01", "abc"])
def test_a_rate_outside_0_to_100_is_refused(rate: str) -> None:
    with pytest.raises(ValidationError):
        _order(tax_rate_pct=rate)


def test_an_empty_rate_reads_as_none() -> None:
    assert POUpdate(tax_rate_pct="").tax_rate_pct is None
