"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - payroll labour-cost math, aggregation, FX, and idempotency.

Scope (Wave 4 lane 2):

1.  ``hours x cost_rate`` produces the correct base-currency amount for a
    single worker, in project base currency.
2.  Multiple logs for the same resource + date merge into one aggregate row
    (hours summed, single rate applied).
3.  Different dates for the same resource stay as separate aggregate rows.
4.  A foreign-currency rate is converted to project base via fx_rates and is
    never blended.
5.  A row with no resolvable rate (no cost_rate, no resource) contributes 0.
6.  A free-text ``worker_type`` row with an explicit cost_rate still costs.
7.  ``LabourActualsService.compute_labour_cost`` matches the entry math.
8.  ``apply_labour_event`` is idempotent on (report_id, status) - re-applying
    the same event does not double the budget actual.

These tests exercise the pure aggregation / FX / idempotency logic only;
the DB is never booted. A tiny fake session + monkeypatched FX context and
resource lookup stand in for the data layer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.costmodel.service import LabourActualsService
from app.modules.payroll.service import PayrollService, _to_decimal

PROJECT_ID = uuid.uuid4()
RESOURCE_A = uuid.uuid4()


class _FakeSession:
    """Minimal stand-in - the methods under test never touch it directly
    (collection is monkeypatched), but the service constructor stores it."""


def _make_payroll_service(monkeypatch, *, base: str, fx: dict[str, str], rates: dict[str, tuple[Decimal, str]]):
    """Build a PayrollService with stubbed FX context + resource rates."""
    service = PayrollService(_FakeSession())  # type: ignore[arg-type]

    async def _fx_ctx(_project_id):
        return base, fx

    async def _resource_rate(resource_id: str):
        return rates.get(str(resource_id), (Decimal("0"), ""))

    monkeypatch.setattr(service.budget_repo, "_project_fx_context", _fx_ctx)
    monkeypatch.setattr(service, "_resource_rate", _resource_rate)
    return service


# ── 1. Single worker hours x rate ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_worker_hours_times_rate(monkeypatch) -> None:
    service = _make_payroll_service(monkeypatch, base="EUR", fx={}, rates={})
    rows = [{"worker_type": "carpenter", "work_date": "2026-06-01", "hours": Decimal("8"), "cost_rate": "50"}]
    agg, base, fx = await service._aggregate(PROJECT_ID, rows)
    assert base == "EUR"
    assert len(agg) == 1
    assert agg[0].hours == Decimal("8")
    assert agg[0].rate == Decimal("50")
    # 8 * 50 = 400
    cost, hours, ccy = await _labour_via_rows(service, rows)
    assert cost == Decimal("400.00")
    assert hours == Decimal("8.00")
    assert ccy == "EUR"


# ── 2. Same resource + date merges ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_resource_same_date_merges(monkeypatch) -> None:
    service = _make_payroll_service(monkeypatch, base="EUR", fx={}, rates={str(RESOURCE_A): (Decimal("40"), "EUR")})
    rows = [
        {"worker_type": "mason", "work_date": "2026-06-01", "hours": Decimal("5"), "resource_id": str(RESOURCE_A)},
        {"worker_type": "mason", "work_date": "2026-06-01", "hours": Decimal("3"), "resource_id": str(RESOURCE_A)},
    ]
    agg, _, _ = await service._aggregate(PROJECT_ID, rows)
    assert len(agg) == 1
    assert agg[0].hours == Decimal("8")
    assert agg[0].rate == Decimal("40")


# ── 3. Different dates stay separate ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_resource_different_dates_split(monkeypatch) -> None:
    service = _make_payroll_service(monkeypatch, base="EUR", fx={}, rates={str(RESOURCE_A): (Decimal("40"), "EUR")})
    rows = [
        {"worker_type": "mason", "work_date": "2026-06-01", "hours": Decimal("5"), "resource_id": str(RESOURCE_A)},
        {"worker_type": "mason", "work_date": "2026-06-02", "hours": Decimal("3"), "resource_id": str(RESOURCE_A)},
    ]
    agg, _, _ = await service._aggregate(PROJECT_ID, rows)
    assert len(agg) == 2
    assert {a.work_date for a in agg} == {"2026-06-01", "2026-06-02"}


# ── 4. Foreign currency converted, never blended ───────────────────────────────


@pytest.mark.asyncio
async def test_foreign_currency_converted_to_base(monkeypatch) -> None:
    # USD rate of 1.10 base-per-USD. 10h * 30 USD = 300 USD = 330 EUR.
    service = _make_payroll_service(monkeypatch, base="EUR", fx={"USD": "1.10"}, rates={})
    rows = [
        {
            "worker_type": "labourer",
            "work_date": "2026-06-01",
            "hours": Decimal("10"),
            "cost_rate": "30",
            "currency": "USD",
        }
    ]
    cost, _, ccy = await _labour_via_rows(service, rows)
    assert ccy == "EUR"
    assert cost == Decimal("330.00")


# ── 5. No resolvable rate → zero ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_rate_contributes_zero(monkeypatch) -> None:
    service = _make_payroll_service(monkeypatch, base="EUR", fx={}, rates={})
    rows = [{"worker_type": "volunteer", "work_date": "2026-06-01", "hours": Decimal("6")}]
    cost, hours, _ = await _labour_via_rows(service, rows)
    assert cost == Decimal("0.00")
    assert hours == Decimal("6.00")  # hours still counted


# ── 6. Free-text worker with explicit rate still costs ─────────────────────────


@pytest.mark.asyncio
async def test_free_text_worker_with_explicit_rate(monkeypatch) -> None:
    service = _make_payroll_service(monkeypatch, base="EUR", fx={}, rates={})
    rows = [{"worker_type": "scaffolder", "work_date": "2026-06-03", "hours": Decimal("7.5"), "cost_rate": "42"}]
    cost, _, _ = await _labour_via_rows(service, rows)
    assert cost == Decimal("315.00")  # 7.5 * 42


# ── 7. costmodel.compute_labour_cost matches ───────────────────────────────────


@pytest.mark.asyncio
async def test_costmodel_compute_labour_cost(monkeypatch) -> None:
    svc = LabourActualsService(_FakeSession())  # type: ignore[arg-type]

    async def _fx_ctx(_project_id):
        return "EUR", {"USD": "1.10"}

    monkeypatch.setattr(svc.budget_repo, "_project_fx_context", _fx_ctx)

    rows = [
        {"worker_type": "carpenter", "hours": 8, "cost_rate": "50"},  # 400 EUR
        {"worker_type": "labourer", "hours": 10, "cost_rate": "30", "currency": "USD"},  # 330 EUR
        {"worker_type": "ghost", "hours": 5},  # no rate -> 0
    ]
    total = await svc.compute_labour_cost(PROJECT_ID, rows)
    assert total == Decimal("730")


# ── 8. apply_labour_event idempotency ──────────────────────────────────────────


class _FakeBudgetLine:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.actual_amount = "0"
        self.metadata_ = {"kind": "labour_actuals_auto", "applied_events": []}


@pytest.mark.asyncio
async def test_apply_labour_event_is_idempotent(monkeypatch) -> None:
    svc = LabourActualsService(_FakeSession())  # type: ignore[arg-type]

    async def _fx_ctx(_project_id):
        return "EUR", {}

    monkeypatch.setattr(svc.budget_repo, "_project_fx_context", _fx_ctx)

    line = _FakeBudgetLine()

    async def _get_or_create(_project_id):
        return line

    updates: list[dict] = []

    async def _update_fields(_line_id, **fields):
        updates.append(fields)
        if "actual_amount" in fields:
            line.actual_amount = fields["actual_amount"]
        if "metadata_" in fields:
            line.metadata_ = fields["metadata_"]

    monkeypatch.setattr(svc, "_get_or_create_labour_line", _get_or_create)
    monkeypatch.setattr(svc.budget_repo, "update_fields", _update_fields)

    rows = [{"worker_type": "carpenter", "hours": 8, "cost_rate": "50"}]  # 400 EUR

    first = await svc.apply_labour_event(project_id=PROJECT_ID, report_id="R1", status_value="submitted", rows=rows)
    assert first == Decimal("400")
    assert line.actual_amount == "400.00"

    # Re-fire the SAME (report_id, status) - must be a no-op.
    second = await svc.apply_labour_event(project_id=PROJECT_ID, report_id="R1", status_value="submitted", rows=rows)
    assert second == Decimal("0")
    assert line.actual_amount == "400.00"

    # A different status for the same report (approve after submit) WOULD add
    # again - but the publisher only fires approve when hours exist; here we
    # assert the key discriminates so the guard is per (report, status).
    third = await svc.apply_labour_event(project_id=PROJECT_ID, report_id="R1", status_value="approved", rows=rows)
    assert third == Decimal("400")
    assert line.actual_amount == "800.00"


# ── helpers ────────────────────────────────────────────────────────────────────


async def _labour_via_rows(service: PayrollService, rows: list[dict]):
    """Run the entry-building math the service uses, returning (cost, hours, base)."""
    from app.modules.costmodel.repository import _amount_in_base

    agg, base, fx = await service._aggregate(PROJECT_ID, rows)
    total_cost = Decimal("0")
    total_hours = Decimal("0")
    for a in agg:
        total_cost += _amount_in_base(str(a.hours * a.rate), a.currency, base, fx)
        total_hours += a.hours
    return total_cost.quantize(Decimal("0.01")), total_hours.quantize(Decimal("0.01")), base


def test_to_decimal_guards() -> None:
    assert _to_decimal(None) == Decimal("0")
    assert _to_decimal("abc") == Decimal("0")
    assert _to_decimal("-5") == Decimal("0")  # negative clamped
    assert _to_decimal("12.5") == Decimal("12.5")
