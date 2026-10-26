# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cash-flow forecast arithmetic: months, position, peak funding, scenarios, currencies."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.costmodel.cashflow_forecast import (
    ActualLine,
    CashLine,
    Scenario,
    aggregate,
    build_forecast,
    parse_terms_days,
    spread,
)
from app.modules.costmodel.cashflow_forecast_rules import (
    PAYLOAD_KEY,
    ForecastMissingRule,
    NegativePositionRule,
    ReceiptOverdueRule,
)

D = Decimal
TODAY = date(2026, 10, 15)


def _in(on: date, amount: str, ccy: str = "EUR", source: str = "billing", open_: str | None = None) -> CashLine:
    return CashLine("in", source, on, D(amount), D(open_ if open_ is not None else amount), ccy)


def _out(on: date, amount: str, ccy: str = "EUR", source: str = "subcontract") -> CashLine:
    return CashLine("out", source, on, D(amount), D(amount), ccy)


def test_position_dips_and_recovers_with_its_peak_month() -> None:
    lines = [
        _out(date(2026, 11, 30), "100000.00"),
        _out(date(2026, 12, 31), "50000.00"),
        _in(date(2027, 1, 31), "200000.00"),
    ]
    actuals = [ActualLine("in", date(2026, 9, 10), D("30000.00"), "EUR")]
    (eur,) = build_forecast(lines, actuals, today=TODAY)
    by = {m.period: m for m in eur.months}
    assert [m.period for m in eur.months] == ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]
    assert by["2026-09"].cumulative == D("30000.00")
    assert by["2026-11"].cumulative == D("-70000.00")
    assert by["2026-12"].cumulative == D("-120000.00")
    assert eur.peak is not None and eur.peak.amount == D("120000.00") and eur.peak.period == "2026-12"
    assert eur.closing_position == D("80000.00")


def test_overdue_open_amount_lands_in_the_current_month_and_plan_stays_in_its_month() -> None:
    (eur,) = build_forecast([_in(date(2026, 8, 31), "1000.00", open_="400.00")], [], today=TODAY)
    by = {m.period: m for m in eur.months}
    assert by["2026-08"].planned_in == D("1000.00") and by["2026-08"].expected_in == D("0")
    assert by["2026-10"].expected_in == D("400.00")


def test_actual_against_plan_variance_only_for_past_months() -> None:
    lines = [_in(date(2026, 9, 30), "1000.00", open_="0")]
    (eur,) = build_forecast(lines, [ActualLine("in", date(2026, 9, 30), D("700.00"), "EUR")], today=TODAY)
    sep = next(m for m in eur.months if m.period == "2026-09")
    assert sep.variance_in == D("-300.00")
    assert next(m for m in eur.months if m.period == "2026-10").variance_in == D("0")


def test_currencies_are_never_mixed() -> None:
    tables = build_forecast(
        [_in(date(2026, 11, 1), "10.00", "EUR"), _in(date(2026, 11, 1), "20.00", "USD")], [], today=TODAY
    )
    assert [t.currency for t in tables] == ["EUR", "USD"]
    with pytest.raises(ValueError, match="currencies"):
        aggregate(tables)


def test_aggregate_sums_projects_in_one_currency() -> None:
    a = build_forecast([_out(date(2026, 11, 30), "100.00")], [], today=TODAY)[0]
    b = build_forecast([_in(date(2026, 12, 31), "300.00")], [], today=TODAY)[0]
    total = aggregate([a, b])
    assert total.peak is not None and total.peak.amount == D("100.00")
    assert total.closing_position == D("200.00")


def test_receipt_delay_moves_open_receipts_later() -> None:
    lines = [_in(date(2026, 11, 20), "500.00")]
    (eur,) = build_forecast(lines, [], today=TODAY, scenario=Scenario(receipt_delay_days=45))
    assert {m.period: m.expected_in for m in eur.months}["2027-01"] == D("500.00")


def test_cost_overrun_scales_estimates_not_issued_invoices() -> None:
    lines = [_out(date(2026, 11, 30), "1000.00"), _out(date(2026, 11, 30), "1000.00", source="payable_invoice")]
    (eur,) = build_forecast(lines, [], today=TODAY, scenario=Scenario(cost_overrun_pct=D("10")))
    nov = next(m for m in eur.months if m.period == "2026-11")
    assert nov.expected_out == D("2100.00")


def test_spread_keeps_every_cent() -> None:
    shares = spread(D("100.00"), [D(1), D(1), D(1)])
    assert shares == [D("33.33"), D("33.33"), D("33.34")]
    assert spread(D("10.00"), [D(0), D(0)]) == [D("5.00"), D("5.00")]


@pytest.mark.parametrize(("text", "days"), [("Net 45", 45), ("60 days", 60), (14, 14), ("", 30), (None, 30)])
def test_payment_terms_are_read_from_text(text: object, days: int) -> None:
    assert parse_terms_days(text) == days


def _run(rule, payload: dict) -> list:
    return asyncio.run(rule.validate(ValidationContext(data={PAYLOAD_KEY: payload}, metadata={"locale": "en"})))


def test_negative_position_rule_respects_the_threshold() -> None:
    payload = {
        "threshold": "50000",
        "currencies": [{"currency": "EUR", "peak_funding": {"amount": "120000", "period": "2026-12"}}],
    }
    (hit,) = _run(NegativePositionRule(), payload)
    assert not hit.passed and hit.element_ref == "EUR:2026-12" and "2026-12" in hit.message
    payload["threshold"] = "150000"
    assert _run(NegativePositionRule(), payload)[0].passed


def test_overdue_and_missing_rules() -> None:
    overdue = {
        "overdue": [{"ref": "x", "label": "AR-7", "amount": "10", "currency": "EUR", "due": "2026-09-01", "days": "44"}]
    }
    (hit,) = _run(ReceiptOverdueRule(), overdue)
    assert not hit.passed and "AR-7" in hit.message
    (miss,) = _run(ForecastMissingRule(), {"has_inputs": False, "project_status": "active", "project_name": "P"})
    assert not miss.passed
    assert _run(ForecastMissingRule(), {"has_inputs": False, "project_status": "archived"})[0].passed
