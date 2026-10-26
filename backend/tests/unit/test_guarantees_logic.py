# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ rules of the guarantees register: lifecycle, reduction, alerts, exposure, rules."""

from __future__ import annotations

import typing
from datetime import date
from decimal import Decimal

import pytest

from app.modules.guarantees import logic, schemas
from app.modules.guarantees.validators import (
    RULE_IDS,
    AdvanceCoversOutstanding,
    AmountMatchesContractPercent,
    ExpiryCoversDefectsPeriod,
    PerformanceBondBeforeFirstPayment,
)

D = Decimal


def test_schema_vocabularies_match_logic() -> None:
    assert typing.get_args(schemas.GuaranteeTypeLiteral) == logic.GUARANTEE_TYPES
    assert typing.get_args(schemas.StatusLiteral) == logic.STATUSES
    assert typing.get_args(schemas.DirectionLiteral) == logic.DIRECTIONS


@pytest.mark.parametrize(
    ("current", "target", "ok"),
    [
        ("draft", "issued", True),
        ("issued", "reduced", True),
        ("reduced", "released", True),
        ("released", "issued", False),
        ("called", "released", False),
        ("expired", "extended", True),
        ("draft", "called", False),
    ],
)
def test_transitions(current: str, target: str, ok: bool) -> None:
    assert logic.can_transition(current, target) is ok


@pytest.mark.parametrize(
    ("days", "band"), [(90, None), (60, 60), (45, 60), (30, 30), (15, 30), (14, 14), (0, 14), (-1, None), (None, None)]
)
def test_alert_band(days: int | None, band: int | None) -> None:
    assert logic.alert_band(days) == band


def test_advance_guarantee_reduces_to_outstanding_and_never_rises() -> None:
    assert logic.reduced_advance_amount(D("1000000"), D("1000000"), D("250000")) == D("750000")
    # A guarantee issued below the advance is not raised by a small recovery.
    assert logic.reduced_advance_amount(D("500000"), D("1000000"), D("100000")) == D("500000")
    assert logic.reduced_advance_amount(D("1000000"), D("1000000"), D("1200000")) == D("0")
    assert logic.outstanding_advance(D("100"), D("150")) == D("0")


def test_add_months_clamps_month_end() -> None:
    assert logic.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert logic.add_months(date(2026, 11, 15), 14) == date(2028, 1, 15)


def test_percent_match_tolerance() -> None:
    assert logic.amount_matches_percent(D("1000000"), D("10000000"), D("10")) is True
    assert logic.amount_matches_percent(D("1004000"), D("10000000"), D("10")) is True
    assert logic.amount_matches_percent(D("900000"), D("10000000"), D("10")) is False
    assert logic.amount_matches_percent(D("900000"), None, D("10")) is None


def test_commission_actual_365() -> None:
    assert logic.commission_for(D("1000000"), D("1.5"), 365) == D("15000.00")
    assert logic.commission_for(D("1000000"), None, 365) == D("0")


def test_exposure_by_bank_type_and_credit_line() -> None:
    rows = [
        logic.ExposureRow("performance_bond", "issued", "given", "Gulf Bank", "AED", D("5000000"), "f1"),
        logic.ExposureRow("advance_payment", "reduced", "given", "Gulf Bank", "AED", D("2000000"), "f1"),
        logic.ExposureRow("bid_bond", "released", "given", "Gulf Bank", "AED", D("100000"), "f1"),
        logic.ExposureRow("performance_bond", "issued", "given", "Euro Bank", "EUR", D("300000")),
        logic.ExposureRow("performance_bond", "issued", "received", "Sub Bank", "AED", D("400000")),
    ]
    out = logic.exposure(rows, [{"id": "f1", "bank_name": "Gulf Bank", "currency": "AED", "limit_amount": "10000000"}])
    assert out["live_count"] == 4
    assert {(t["currency"], t["amount"]) for t in out["totals"]} == {("AED", D("7000000")), ("EUR", D("300000"))}
    line = out["credit_lines"][0]
    assert line["used_amount"] == D("7000000")
    assert line["available_amount"] == D("3000000")
    assert line["utilisation_pct"] == D("70.0")
    assert out["held"] == [{"guarantee_type": "performance_bond", "currency": "AED", "amount": D("400000")}]


class _Ctx:
    def __init__(self, data: dict) -> None:
        self.data = data


async def _run(rule, data: dict):
    return [r for r in await rule.validate(_Ctx(data)) if not r.passed]


def test_rule_ids_are_stable() -> None:
    assert RULE_IDS == (
        "guarantees.performance_bond_before_first_payment",
        "guarantees.expiry_covers_defects_period",
        "guarantees.advance_covers_outstanding",
        "guarantees.amount_matches_contract_percent",
    )


@pytest.mark.asyncio
async def test_performance_bond_missing_at_first_payment() -> None:
    data = {"guarantees": [], "contracts": {"c1": {"code": "MC-1", "payment_due": True}}}
    assert len(await _run(PerformanceBondBeforeFirstPayment(), data)) == 1
    data["guarantees"] = [{"guarantee_type": "performance_bond", "status": "issued", "contract_id": "c1"}]
    assert await _run(PerformanceBondBeforeFirstPayment(), data) == []
    data["guarantees"][0]["status"] = "requested"
    assert len(await _run(PerformanceBondBeforeFirstPayment(), data)) == 1


@pytest.mark.asyncio
async def test_expiry_before_completion_plus_defects_period() -> None:
    g = {
        "reference": "PB-1",
        "guarantee_type": "performance_bond",
        "status": "issued",
        "contract_id": "c1",
        "expiry_date": "2027-06-30",
    }
    contracts = {"c1": {"completion_date": "2027-03-31", "defects_period_months": 12}}
    found = await _run(ExpiryCoversDefectsPeriod(), {"guarantees": [g], "contracts": contracts})
    assert len(found) == 1
    assert found[0].details["required_until"] == "2028-03-31"
    g["auto_extend"] = True
    assert await _run(ExpiryCoversDefectsPeriod(), {"guarantees": [g], "contracts": contracts}) == []


@pytest.mark.asyncio
async def test_advance_guarantee_below_outstanding() -> None:
    g = {
        "reference": "APG-1",
        "guarantee_type": "advance_payment",
        "status": "reduced",
        "amount": "600000",
        "advance_amount": "1000000",
        "advance_recovered": "300000",
        "currency": "AED",
    }
    assert len(await _run(AdvanceCoversOutstanding(), {"guarantees": [g]})) == 1
    g["amount"] = "700000"
    assert await _run(AdvanceCoversOutstanding(), {"guarantees": [g]}) == []


@pytest.mark.asyncio
async def test_amount_not_matching_contract_percent() -> None:
    g = {
        "reference": "PB-1",
        "guarantee_type": "performance_bond",
        "status": "issued",
        "amount": "800000",
        "percent_of_contract": "10",
        "contract_value": "10000000",
        "currency": "AED",
    }
    found = await _run(AmountMatchesContractPercent(), {"guarantees": [g]})
    assert len(found) == 1
    assert found[0].details["expected_amount"] == "1000000.00"


def test_defaults_are_fidic_then_gcc_pack() -> None:
    from app.modules.guarantees.defaults import defaults_for

    neutral = defaults_for(None)
    assert neutral["types"]["performance_bond"]["percent_of_contract"] == "10"
    assert neutral["origin"] == "FIDIC 2017"
    sa = defaults_for("SA")
    assert sa["types"]["performance_bond"]["percent_of_contract"] == "5"
    assert sa["types"]["performance_bond"]["claim_period_days"] == 28
    ae = defaults_for("ae")
    assert ae["types"]["performance_bond"]["form_code"] == "AE-PB-ONDEMAND"
    # A country no pack writes for gets the neutral figures unchanged.
    assert defaults_for("IS")["types"] == neutral["types"]
