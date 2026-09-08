# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""A money threshold was a fixed number in no currency.

``boq_quality.unrealistic_rate`` compared every unit rate against 100,000 and
every total against 10,000,000; ``boq_quality.rate_vs_benchmark`` compared a
rate per m2 against 10,000 and per m3 against 50,000. None of the four numbers
named a currency, so they were euros on a German bill and rupiah on an
Indonesian one. A unit rate of 100,000 is a fortune in EUR and about six euros
in IDR: the rules fired on every line of every Indonesian, Vietnamese, Korean
or Hungarian bill and could not fire on a real outlier in a strong currency
below the same nominal figure.

The thresholds are now written in one reference currency (EUR) and scaled into
the bill's currency through the platform's FX bridge. Four things are asserted:

* the same nominal figure is an outlier in EUR and ordinary in IDR, and a real
  outlier in IDR still fires, so the fix is a scale and not a silencer;
* a EUR bill keeps exactly the thresholds it always had;
* a currency no source can price, and a bill that names no currency at all,
  yield an explicit not-assessed row that is neither a pass nor a finding and
  moves neither the status nor the score;
* the currency is read from where each surface puts it: the position, the bill
  header, the project record the shared builder carries, and a rate the project
  typed itself prices a currency the register has never heard of.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationReport,
    ValidationStatus,
)
from app.core.validation.rules import RateVsBenchmark, UnrealisticRate

# ISO 4217 reserves XTS for testing. No feed quotes it and the bundled seed
# does not carry it, so it stands for every currency the register cannot price
# (a Colombian bill before anyone has entered a COP rate, for instance).
UNPRICED = "XTS"


def _pos(pid: str, rate: float, *, currency: str | None = None, unit: str = "m2", qty: float = 1.0) -> dict[str, Any]:
    pos: dict[str, Any] = {
        "id": pid,
        "ordinal": pid,
        "description": f"item {pid}",
        "unit": unit,
        "quantity": qty,
        "unit_rate": rate,
        "total": rate * qty,
    }
    if currency:
        pos["metadata"] = {"currency": currency}
    return pos


def _ctx(positions: list[dict[str, Any]], **payload: Any) -> ValidationContext:
    return ValidationContext(data={"positions": positions, **payload}, metadata={"locale": "en"})


async def _units_per_eur(code: str) -> float:
    """What the rules themselves scale by: the register read without a session."""
    from app.modules.fx.service import FxService

    resolved = await FxService(None).resolve_rates()
    assert resolved.base_currency == "EUR"
    return float(resolved.rates[code])


def _judged(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if not r.is_engine_error]


def _not_assessed(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if r.is_engine_error]


# ── the scale, not a silencer ─────────────────────────────────────────────────


async def test_the_same_nominal_rate_is_an_outlier_in_eur_and_ordinary_in_idr() -> None:
    rows_eur = await UnrealisticRate().validate(_ctx([_pos("p1", 150_000, currency="EUR")]))
    rows_idr = await UnrealisticRate().validate(_ctx([_pos("p1", 150_000, currency="IDR")]))

    assert [r.passed for r in rows_eur] == [False]
    assert [r.passed for r in rows_idr] == [True]
    assert not _not_assessed(rows_eur) and not _not_assessed(rows_idr)


async def test_the_benchmark_per_unit_is_scaled_the_same_way() -> None:
    eur = await RateVsBenchmark().validate(
        _ctx([_pos("m2", 15_000, currency="EUR"), _pos("m3", 60_000, currency="EUR", unit="m3")])
    )
    idr = await RateVsBenchmark().validate(
        _ctx([_pos("m2", 15_000, currency="IDR"), _pos("m3", 60_000, currency="IDR", unit="m3")])
    )

    assert [r.passed for r in eur] == [False, False]
    assert [r.passed for r in idr] == [True, True]


async def test_a_real_outlier_in_a_weak_currency_still_fires_and_reads_in_that_currency() -> None:
    per_eur = await _units_per_eur("IDR")
    outlier = UnrealisticRate.RATE_THRESHOLD * per_eur * 1.5

    (row,) = await UnrealisticRate().validate(_ctx([_pos("1", outlier, currency="IDR")]))

    assert row.passed is False
    assert row.details["currency"] == "IDR"
    assert row.details["rate_threshold"] == pytest.approx(UnrealisticRate.RATE_THRESHOLD * per_eur)
    assert row.details["reference_currency"] == "EUR"
    assert row.details["reference_rate_threshold"] == UnrealisticRate.RATE_THRESHOLD
    assert row.details["fx_source"], "the row must say which source priced the pair"
    # The rupiah has no subunit: the figures in the message carry none either.
    assert "IDR" in row.message
    assert ".00" not in row.message


async def test_a_eur_bill_keeps_the_thresholds_it_always_had() -> None:
    at_limit, over = await UnrealisticRate().validate(
        _ctx([_pos("a", 100_000, currency="EUR"), _pos("b", 100_000.01, currency="EUR")])
    )

    assert at_limit.passed is True
    assert over.passed is False
    assert over.details["rate_threshold"] == 100_000
    assert over.details["total_threshold"] == 10_000_000
    assert "100,000.00 EUR" in over.message

    (bench,) = await RateVsBenchmark().validate(_ctx([_pos("c", 10_000.01, currency="EUR")]))
    assert bench.passed is False
    assert bench.details["benchmark_threshold"] == 10_000
    assert "10,000.00 EUR/m2" in bench.message


async def test_the_total_threshold_is_scaled_as_well_as_the_rate() -> None:
    per_eur = await _units_per_eur("IDR")
    # Ordinary rate, enormous quantity: only the total crosses its line.
    (row,) = await UnrealisticRate().validate(
        _ctx([_pos("t", 1_000 * per_eur, currency="IDR", qty=20_000)]),
    )

    assert row.passed is False
    assert "total" in row.message and "unit_rate" not in row.message
    assert row.details["total_threshold"] == pytest.approx(UnrealisticRate.TOTAL_THRESHOLD * per_eur)


# ── the honest outcome when nothing can be scaled ─────────────────────────────


@pytest.mark.parametrize("rule_cls", [UnrealisticRate, RateVsBenchmark])
async def test_a_currency_no_source_can_price_yields_one_not_assessed_row_per_currency(rule_cls: type) -> None:
    positions = [_pos("x1", 150_000, currency=UNPRICED), _pos("x2", 5, currency=UNPRICED)]

    results = await rule_cls().validate(_ctx(positions))

    assert _judged(results) == [], "a rate nobody can scale must not be judged against the reference"
    (row,) = _not_assessed(results)
    assert row.rule_id == rule_cls.rule_id
    assert row.is_engine_error is True
    assert row.passed is False
    assert row.severity == Severity.INFO
    assert row.category == RuleCategory.DIAGNOSTIC
    assert row.element_ref is None
    assert row.details["fx_reason"] == "no_rate"
    assert row.details["currency"] == UNPRICED
    assert row.details["reference_currency"] == "EUR"
    assert row.details["position_ids"] == ["x1", "x2"]
    assert row.details["position_count"] == 2
    assert UNPRICED in row.message and "EUR" in row.message
    assert row.suggestion


@pytest.mark.parametrize("rule_cls", [UnrealisticRate, RateVsBenchmark])
async def test_a_bill_that_names_no_currency_is_not_judged_against_the_reference(rule_cls: type) -> None:
    results = await rule_cls().validate(_ctx([_pos("n1", 150_000)]))

    assert _judged(results) == []
    (row,) = _not_assessed(results)
    assert row.details["fx_reason"] == "no_currency"
    assert row.details["currency"] == ""
    assert row.details["position_ids"] == ["n1"]
    assert "no currency" in row.message


async def test_a_row_carrying_no_money_passes_whatever_the_currency_situation() -> None:
    section = {
        "id": "sec",
        "ordinal": "1",
        "description": "Earthworks",
        "unit": "",
        "quantity": 0,
        "unit_rate": 0,
        "total": 0,
    }

    (row,) = await UnrealisticRate().validate(_ctx([section]))

    assert row.passed is True
    assert row.is_engine_error is False


async def test_the_not_assessed_row_moves_neither_the_status_nor_the_score() -> None:
    results = await UnrealisticRate().validate(_ctx([_pos("x1", 150_000, currency=UNPRICED)]))
    report = ValidationReport(results=results)

    assert report.warnings == [] and report.errors == [] and report.infos == []
    assert report.engine_errors == results
    assert report.status == ValidationStatus.SKIPPED
    assert report.score is None


async def test_mixed_currencies_judge_what_they_can_and_say_what_they_cannot() -> None:
    positions = [
        _pos("e", 150_000, currency="EUR"),
        _pos("i", 150_000, currency="IDR"),
        _pos("x", 150_000, currency=UNPRICED),
        _pos("n", 150_000),
    ]

    results = await UnrealisticRate().validate(_ctx(positions))

    judged = {r.element_ref: r.passed for r in _judged(results)}
    assert judged == {"e": False, "i": True}
    reasons = {(r.details["fx_reason"], r.details["currency"]) for r in _not_assessed(results)}
    assert reasons == {("no_rate", UNPRICED), ("no_currency", "")}


# ── where the currency is read from ──────────────────────────────────────────


async def test_the_currency_is_read_from_the_project_record_the_builder_carries() -> None:
    idr = await UnrealisticRate().validate(_ctx([_pos("p", 150_000)], project_record={"currency": "IDR"}))
    eur = await UnrealisticRate().validate(_ctx([_pos("p", 150_000)], project_record={"currency": "EUR"}))

    assert [r.passed for r in idr] == [True]
    assert [r.passed for r in eur] == [False]


async def test_the_currency_is_read_from_the_bill_header_the_audit_supplies() -> None:
    (row,) = await UnrealisticRate().validate(_ctx([_pos("p", 150_000)], boq={"currency": "idr"}))

    assert row.passed is True
    assert row.details["currency"] == "IDR"


async def test_a_position_currency_outranks_the_project_currency() -> None:
    (row,) = await UnrealisticRate().validate(
        _ctx([_pos("p", 150_000, currency="IDR")], project_record={"currency": "EUR"}),
    )

    assert row.passed is True
    assert row.details["currency"] == "IDR"


async def test_a_rate_the_project_typed_prices_a_currency_the_register_cannot() -> None:
    # Project.fx_rates convention: base units per 1 unit of the foreign currency,
    # so 4,500 here means 4,500 XTS buy one euro.
    record = {"currency": UNPRICED, "fx_rates": [{"code": "EUR", "rate": "4500"}]}

    ordinary, outlier = await UnrealisticRate().validate(
        _ctx([_pos("o", 150_000), _pos("u", 500_000_000)], project_record=record),
    )

    assert ordinary.passed is True
    assert outlier.passed is False
    assert outlier.details["rate_threshold"] == pytest.approx(100_000 * 4_500)
    assert outlier.details["fx_source"] == "project_fx_rates"

    (bench,) = await RateVsBenchmark().validate(_ctx([_pos("b", 50_000_000)], project_record=record))
    assert bench.passed is False
    assert bench.details["benchmark_threshold"] == pytest.approx(10_000 * 4_500)
