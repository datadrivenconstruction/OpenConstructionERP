# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``payment_plan`` rule set, over plain dict contexts.

The deposit rule warns and never blocks: the statutory table is research that
no lawyer has checked for a given contract, so the person drawing up the
contract decides. Where it cannot compare at all it says so as information.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import Severity, validation_engine
from app.modules.contracts.validators import PAYMENT_PLAN_RULE_SET, register_contracts_validation_rules

pytestmark = pytest.mark.asyncio


def _context(
    *milestones: dict[str, Any],
    total: str = "100000",
    status: str = "active",
    currency: str = "USD",
    subdivision: str | None = None,
) -> dict[str, Any]:
    return {
        "contract": {"id": "c1", "status": status, "currency": currency, "total_value": total},
        "project": {"subdivision_code": subdivision},
        "milestones": [
            {
                "id": f"m{i}",
                "code": f"M{i}",
                "kind": "progress",
                "trigger": "date",
                "status": "pending",
                "client_visible": False,
                "activity_id": None,
                **m,
            }
            for i, m in enumerate(milestones)
        ],
    }


async def _failed(context: dict[str, Any]) -> dict[str, Any]:
    register_contracts_validation_rules()
    report = await validation_engine.validate(data=context, rule_sets=[PAYMENT_PLAN_RULE_SET], target_type="contract")
    assert not report.engine_errors
    return {(r.rule_id, r.element_ref): r for r in report.results if not r.passed}


async def test_a_full_plan_passes() -> None:
    failed = await _failed(_context({"amount": "40000"}, {"amount": "60000"}))
    assert failed == {}


async def test_a_plan_over_the_contract_sum_is_an_error_and_only_that() -> None:
    failed = await _failed(_context({"amount": "70000"}, {"amount": "40000"}))
    assert set(failed) == {("payment_plan.total_within_contract", "c1")}
    assert failed["payment_plan.total_within_contract", "c1"].severity == Severity.ERROR


async def test_a_plan_short_of_the_contract_sum_warns() -> None:
    failed = await _failed(_context({"amount": "40000"}))
    result = failed["payment_plan.percent_sum", "c1"]
    assert result.severity == Severity.WARNING
    assert result.details["percent"] == "40"


async def test_a_pending_completion_instalment_without_an_activity_warns() -> None:
    failed = await _failed(
        _context(
            {"amount": "50000", "trigger": "completion"},
            {"amount": "30000", "trigger": "approval", "activity_id": "a1"},
            {"amount": "20000", "trigger": "completion", "status": "reached"},
        )
    )
    assert set(failed) == {("payment_plan.completion_trigger_linked", "m0")}


@pytest.mark.parametrize(("status", "blocked"), [("draft", True), ("active", False), ("completed", False)])
async def test_a_client_visible_instalment_needs_a_contract_in_force(status, blocked) -> None:
    failed = await _failed(_context({"amount": "100000", "client_visible": True}, status=status))
    key = ("payment_plan.client_visible_requires_active", "m0")
    assert (key in failed) is blocked
    if blocked:
        assert failed[key].severity == Severity.ERROR


async def test_a_deposit_over_the_california_ceiling_warns_with_its_source() -> None:
    # 10 percent of 100000 is 10000, so the 1000 dollar cap is the lesser.
    failed = await _failed(_context({"amount": "1500", "kind": "deposit"}, {"amount": "98500"}, subdivision="US-CA"))
    result = failed["payment_plan.consumer_deposit_cap", "c1"]
    assert result.severity == Severity.WARNING
    assert result.details["reference"] == "Cal. Bus. & Prof. Code 7159.5(a)(3)"
    assert result.details["source_url"].startswith("https://leginfo.legislature.ca.gov/")
    assert result.details["verified"] == "False"


async def test_a_deposit_within_the_ceiling_passes() -> None:
    failed = await _failed(_context({"amount": "1000", "kind": "deposit"}, {"amount": "99000"}, subdivision="US-CA"))
    assert ("payment_plan.consumer_deposit_cap", "c1") not in failed


@pytest.mark.parametrize(
    ("total", "currency", "outcome"),
    [("400", "USD", "below_threshold"), ("100000", "EUR", "other_currency")],
)
async def test_a_deposit_that_cannot_be_compared_is_information(total, currency, outcome) -> None:
    failed = await _failed(
        _context({"amount": total, "kind": "deposit"}, total=total, currency=currency, subdivision="US-CA")
    )
    result = failed["payment_plan.consumer_deposit_cap", "c1"]
    assert result.severity == Severity.INFO
    assert result.details["jurisdiction"] == "US-CA"


async def test_no_limit_recorded_or_no_deposit_checks_nothing() -> None:
    unknown = await _failed(_context({"amount": "90000", "kind": "deposit"}, {"amount": "10000"}, subdivision="DE-BY"))
    no_deposit = await _failed(_context({"amount": "100000"}, subdivision="US-CA"))
    assert ("payment_plan.consumer_deposit_cap", "c1") not in unknown
    assert ("payment_plan.consumer_deposit_cap", "c1") not in no_deposit
