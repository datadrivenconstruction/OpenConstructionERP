"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Mixed-currency money in the sales kanban and the development P&L.

Two defects of one family, both fixed by folding money per ISO currency
before it becomes a headline figure:

- The kanban summed every buyer in a column into one ``total_value``
  regardless of the currency each buyer signed in, so a column holding a
  EUR contract and a USD contract presented their raw sum as money.
- The P&L picked the currency of the FIRST buyer carrying one and dropped
  every buyer that disagreed, so a development whose first stamped buyer
  was a lead in another currency reported ``revenue_contracted = 0``
  while contracted revenue plainly existed.

The aggregation lives in module-top pure helpers, which is the design the
service module's own docstring declares, so these tests exercise the real
code path without a database. The two service-level tests below drive
``PropertyDevService.sales_kanban`` / ``development_pnl`` against stub
repositories to prove the service actually calls those helpers, and the
schema round-trips pin the wire shape the router returns.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.modules.property_dev.schemas import (
    DevelopmentPnLResponse,
    SalesKanbanResponse,
)
from app.modules.property_dev.service import (
    PropertyDevService,
    _resolve_base_currency,
    compute_development_pnl_money,
    compute_kanban_column_money,
)

# ── Stubs ───────────────────────────────────────────────────────────────


class _Buyer:
    """Minimal stand-in for a ``Buyer`` row - only the fields money reads."""

    def __init__(
        self,
        *,
        status: str,
        currency: str = "",
        contract_value: str = "0",
        deposit_amount: str = "0",
        deposit_forfeited: str = "0",
        full_name: str = "Buyer",
    ) -> None:
        self.id = uuid.uuid4()
        self.full_name = full_name
        self.email = ""
        self.plot_id = None
        self.status = status
        self.currency = currency
        self.contract_value = Decimal(contract_value)
        self.deposit_amount = Decimal(deposit_amount)
        self.deposit_forfeited = Decimal(deposit_forfeited)
        self.contract_signed_at = None
        self.freeze_deadline = None


class _Project:
    """Stand-in for the owning ``Project`` - currency + FX table only."""

    def __init__(self, currency: str = "", fx_rates: list[dict[str, str]] | None = None) -> None:
        self.id = uuid.uuid4()
        self.currency = currency
        self.fx_rates = fx_rates or []


class _Development:
    """Stand-in for a ``Development`` row."""

    def __init__(self, *, currency: str = "", project_id: uuid.UUID | None = None) -> None:
        self.id = uuid.uuid4()
        self.project_id = project_id or uuid.uuid4()
        self.currency = currency


class _Result:
    """The slice of a SQLAlchemy result the FX metadata loader touches."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    """Async session stub that answers the single FX metadata SELECT."""

    def __init__(self, project: Any) -> None:
        self._project = project

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._project)


class _Pipeline:
    """Stub for ``BuyerPipelineQueries`` - returns fixed ``(buyer, plot)`` rows."""

    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows

    async def kanban_for_development(self, _dev_id: uuid.UUID) -> list[tuple[Any, Any]]:
        return self._rows


class _Counter:
    """Stub for the warranty / snag open-count repositories."""

    async def count_open_for_development(self, _dev_id: uuid.UUID) -> int:
        return 0


def _service(dev: _Development, project: Any, buyers: list[_Buyer]) -> PropertyDevService:
    """Build a service wired to stubs - no database, real service methods.

    Args:
        dev: The development the roll-ups run for.
        project: The owning project (or ``None``) used for FX metadata.
        buyers: Buyer rows the pipeline query returns.

    Returns:
        A ``PropertyDevService`` whose repositories are the stubs above.
    """
    svc = PropertyDevService.__new__(PropertyDevService)
    svc.session = _Session(project)  # type: ignore[assignment]
    svc.pipeline = _Pipeline([(b, None) for b in buyers])  # type: ignore[assignment]
    svc.warranty = _Counter()  # type: ignore[assignment]
    svc.snags = _Counter()  # type: ignore[assignment]
    svc.get_development = lambda _dev_id: _coro(dev)  # type: ignore[assignment]
    return svc


async def _coro(value: Any) -> Any:
    """Wrap a plain value so a stub can stand in for an async method."""
    return value


# ── Defect A - the kanban column ────────────────────────────────────────


def test_mixed_currency_column_is_not_summed_across_currencies() -> None:
    """A column holding two currencies must not present their raw sum.

    Without an FX rate the foreign bucket is excluded from
    ``total_value`` and reported instead, so the headline stays money in
    one currency rather than the meaningless 300000 the old code showed.
    """
    out = compute_kanban_column_money(
        {"EUR": Decimal("100000.00"), "USD": Decimal("200000.00")},
        base_code="EUR",
        fx_map={},
    )

    assert out["total_value"] == Decimal("100000.00")
    assert out["total_value"] != Decimal("300000.00")
    assert out["mixed_currency"] is True
    assert out["unconverted_by_currency"] == {"USD": "200000.00"}
    assert out["total_by_currency"] == {"EUR": "100000.00", "USD": "200000.00"}


def test_mixed_currency_column_converts_the_buckets_it_has_a_rate_for() -> None:
    """With a project FX rate the foreign bucket joins the base total."""
    out = compute_kanban_column_money(
        {"EUR": Decimal("100000.00"), "USD": Decimal("200000.00")},
        base_code="EUR",
        fx_map={"USD": Decimal("0.90")},
    )

    assert out["total_value"] == Decimal("280000.00")
    assert out["unconverted_by_currency"] == {}
    assert out["mixed_currency"] is True


def test_single_currency_column_keeps_its_plain_total() -> None:
    """The common case is untouched: one currency, one straight sum."""
    out = compute_kanban_column_money(
        {"EUR": Decimal("450000.00")},
        base_code="EUR",
        fx_map={},
    )

    assert out["total_value"] == Decimal("450000.00")
    assert out["mixed_currency"] is False
    assert out["unconverted_by_currency"] == {}


def test_unstamped_buyers_count_as_base_currency() -> None:
    """A buyer with no currency stamp is money in the base currency."""
    out = compute_kanban_column_money(
        {"": Decimal("50000.00"), "EUR": Decimal("100000.00")},
        base_code="EUR",
        fx_map={},
    )

    assert out["total_value"] == Decimal("150000.00")
    assert out["mixed_currency"] is False


def test_column_with_no_base_currency_folds_nothing() -> None:
    """No base currency means no honest headline - everything is reported.

    This is the case where neither the development nor its project names
    a currency and the buyers disagree with each other.
    """
    out = compute_kanban_column_money(
        {"EUR": Decimal("100000.00"), "USD": Decimal("200000.00")},
        base_code="",
        fx_map={"USD": Decimal("0.90")},
    )

    assert out["total_value"] == Decimal("0.00")
    assert out["unconverted_by_currency"] == {
        "EUR": "100000.00",
        "USD": "200000.00",
    }


# ── Defect B - the development P&L ──────────────────────────────────────


def test_contracted_revenue_survives_an_earlier_buyer_in_another_currency() -> None:
    """The first buyer carrying a currency no longer defines the base.

    Old behaviour: the EUR lead was met first, became the development
    currency, and the USD contract was dropped - ``revenue_contracted``
    came back 0 while half a million of contracted revenue existed.
    """
    buyers = [
        _Buyer(status="lead", currency="EUR", contract_value="250000.00"),
        _Buyer(status="contracted", currency="USD", contract_value="500000.00"),
    ]

    out = compute_development_pnl_money(buyers, base_code="USD", fx_map={})

    assert out["revenue_contracted"] == Decimal("500000.00")
    assert out["revenue_contracted_by_currency"] == {"USD": "500000.00"}
    assert out["revenue_contracted_unconverted_by_currency"] == {}
    assert out["mixed_currency"] is True


def test_unconvertible_contracted_revenue_is_reported_not_dropped() -> None:
    """A zero headline must name what it had to leave out.

    With no FX rate the USD contract genuinely cannot be stated in EUR,
    so the scalar stays 0 - but the amount and its currency ride along in
    the envelope instead of vanishing.
    """
    buyers = [
        _Buyer(status="lead", currency="EUR", contract_value="250000.00"),
        _Buyer(status="contracted", currency="USD", contract_value="500000.00"),
    ]

    out = compute_development_pnl_money(buyers, base_code="EUR", fx_map={})

    assert out["revenue_contracted"] == Decimal("0.00")
    assert out["revenue_contracted_unconverted_by_currency"] == {"USD": "500000.00"}
    assert out["mixed_currency"] is True


def test_contracted_revenue_is_fx_converted_when_a_rate_exists() -> None:
    """A rate on the project turns the foreign contract into base money."""
    buyers = [
        _Buyer(status="contracted", currency="EUR", contract_value="100000.00"),
        _Buyer(status="contracted", currency="USD", contract_value="500000.00"),
    ]

    out = compute_development_pnl_money(
        buyers,
        base_code="EUR",
        fx_map={"USD": Decimal("0.90")},
    )

    assert out["revenue_contracted"] == Decimal("550000.00")
    assert out["revenue_contracted_unconverted_by_currency"] == {}


def test_average_sale_price_counts_only_the_buyers_it_summed() -> None:
    """The mean's denominator must match its numerator's population.

    The USD buyer is excluded from contracted revenue for want of a rate,
    so its head must not stay in the divisor either - 200000 / 2, never
    200000 / 3.
    """
    buyers = [
        _Buyer(status="contracted", currency="EUR", contract_value="100000.00"),
        _Buyer(status="contracted", currency="EUR", contract_value="100000.00"),
        _Buyer(status="contracted", currency="USD", contract_value="900000.00"),
    ]

    out = compute_development_pnl_money(buyers, base_code="EUR", fx_map={})

    assert out["avg_sale_price"] == Decimal("100000.00")


def test_deposits_are_folded_by_currency_too() -> None:
    """Deposits ride the same gate as revenue and get the same treatment."""
    buyers = [
        _Buyer(status="reserved", currency="EUR", deposit_amount="10000.00"),
        _Buyer(status="reserved", currency="USD", deposit_amount="20000.00"),
        _Buyer(status="cancelled", currency="USD", deposit_forfeited="5000.00"),
    ]

    out = compute_development_pnl_money(buyers, base_code="EUR", fx_map={})

    assert out["deposits_held"] == Decimal("10000.00")
    assert out["deposits_held_unconverted_by_currency"] == {"USD": "20000.00"}
    assert out["deposits_forfeited"] == Decimal("0.00")
    assert out["deposits_forfeited_unconverted_by_currency"] == {"USD": "5000.00"}


def test_single_currency_pnl_is_unchanged() -> None:
    """One currency throughout: the numbers are what they always were."""
    buyers = [
        _Buyer(status="contracted", currency="EUR", contract_value="300000.00", deposit_amount="30000.00"),
        _Buyer(status="completed", currency="EUR", contract_value="400000.00"),
    ]

    out = compute_development_pnl_money(buyers, base_code="EUR", fx_map={})

    assert out["revenue_contracted"] == Decimal("300000.00")
    assert out["revenue_completed"] == Decimal("400000.00")
    assert out["deposits_held"] == Decimal("30000.00")
    assert out["avg_sale_price"] == Decimal("350000.00")
    assert out["mixed_currency"] is False


# ── Base-currency resolution ────────────────────────────────────────────


def test_base_currency_prefers_the_development_then_the_project() -> None:
    """``Development.currency`` wins; blank falls through to the project."""
    assert _resolve_base_currency("gbp", "EUR", ["USD"]) == "GBP"
    assert _resolve_base_currency("", "EUR", ["USD"]) == "EUR"


def test_blank_base_adopts_the_only_currency_in_use() -> None:
    """An unstamped development that trades in one currency adopts it."""
    assert _resolve_base_currency("", "", ["USD", "USD", ""]) == "USD"


def test_blank_base_with_disagreeing_rows_stays_blank() -> None:
    """Nothing to adopt when the rows disagree, so no headline is labelled."""
    assert _resolve_base_currency("", "", ["USD", "EUR"]) == ""


# ── Service + wire shape ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sales_kanban_reports_the_mixed_column_through_the_service() -> None:
    """The service itself must not hand back a cross-currency sum."""
    project = _Project(currency="EUR")
    dev = _Development(currency="EUR", project_id=project.id)
    buyers = [
        _Buyer(status="contracted", currency="EUR", contract_value="100000.00"),
        _Buyer(status="contracted", currency="USD", contract_value="200000.00"),
    ]

    payload = await _service(dev, project, buyers).sales_kanban(dev.id)

    assert payload["currency"] == "EUR"
    assert payload["mixed_currency"] is True
    contracted = next(c for c in payload["columns"] if c["status"] == "contracted")
    assert contracted["count"] == 2
    assert contracted["total_value"] == Decimal("100000.00")
    assert contracted["unconverted_by_currency"] == {"USD": "200000.00"}

    wire = SalesKanbanResponse(**payload).model_dump(mode="json")
    wire_contracted = next(c for c in wire["columns"] if c["status"] == "contracted")
    assert wire_contracted["total_value"] == "100000.00"
    assert wire_contracted["unconverted_by_currency"] == {"USD": "200000.00"}


@pytest.mark.asyncio
async def test_development_pnl_reports_contracted_revenue_through_the_service() -> None:
    """Defect B end to end: the lead's currency no longer zeroes the P&L."""
    project = _Project(currency="USD", fx_rates=[{"code": "EUR", "rate": "1.10"}])
    dev = _Development(currency="", project_id=project.id)
    buyers = [
        _Buyer(status="lead", currency="EUR", contract_value="250000.00"),
        _Buyer(status="contracted", currency="USD", contract_value="500000.00"),
    ]

    payload = await _service(dev, project, buyers).development_pnl(dev.id)

    assert payload["currency"] == "USD"
    assert payload["revenue_contracted"] == Decimal("500000.00")
    assert payload["mixed_currency"] is True

    wire = DevelopmentPnLResponse(**payload).model_dump(mode="json")
    assert wire["revenue_contracted"] == "500000.00"
    assert wire["currency"] == "USD"
    assert wire["revenue_contracted_by_currency"] == {"USD": "500000.00"}
