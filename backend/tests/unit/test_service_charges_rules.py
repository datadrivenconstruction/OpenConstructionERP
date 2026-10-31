# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges validation rules on plain payloads, and their registration outside the app."""

from __future__ import annotations

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.service_charges.validators import (
    SERVICE_CHARGES_RULE_SET,
    BudgetLinesNonNegativeRule,
    DemandNeedsApprovedBudgetRule,
    DemandsMatchBudgetRule,
    KeySharesTotalRule,
    ReconciliationBalanceRule,
    register_service_charges_validation_rules,
)


def _ctx(data: dict) -> ValidationContext:
    return ValidationContext(data=data)


def _budget(**kw) -> dict:
    base = {
        "id": "b1",
        "status": "approved",
        "year": 2026,
        "periods": 4,
        "lines": [
            {"id": "l1", "category": "Lift", "amount": "1000.00"},
            {"id": "l2", "category": "Water", "amount": "333.33"},
        ],
        "demand_periods": [],
    }
    base.update(kw)
    return base


async def test_permille_shares_must_add_up_to_1000() -> None:
    good = {"keys": [{"id": "k", "name": "A", "method": "permille", "shares": ["500", "500"]}]}
    bad = {"keys": [{"id": "k", "name": "A", "method": "permille", "shares": ["500", "499.9"]}]}
    assert all(r.passed for r in await KeySharesTotalRule().validate(_ctx(good)))
    assert not (await KeySharesTotalRule().validate(_ctx(bad)))[0].passed


async def test_negative_budget_line_fails() -> None:
    rule = BudgetLinesNonNegativeRule()
    assert all(r.passed for r in await rule.validate(_ctx({"budget": _budget()})))
    lines = [{"id": "l1", "category": "Lift", "amount": "-0.01"}, {"id": "l2", "category": "X", "amount": "0"}]
    results = await rule.validate(_ctx({"budget": _budget(lines=lines)}))
    assert [r.passed for r in results] == [False, True]


async def test_demands_need_an_approved_budget() -> None:
    rule = DemandNeedsApprovedBudgetRule()
    draft = {"operation": "demand", "budget": _budget(status="draft")}
    assert not (await rule.validate(_ctx(draft)))[0].passed
    assert (await rule.validate(_ctx({"operation": "demand", "budget": _budget()})))[0].passed


async def test_demands_must_match_the_period_instalment_within_rounding() -> None:
    rule = DemandsMatchBudgetRule()
    # 1333.33 over 4 periods: 333.34, 333.33, 333.33, 333.33
    ok = _budget(demand_periods=[{"period": 1, "units": 3, "demanded": "333.33"}])
    assert (await rule.validate(_ctx({"budget": ok})))[0].passed
    short = _budget(demand_periods=[{"period": 2, "units": 3, "demanded": "300.00"}])
    result = (await rule.validate(_ctx({"budget": short})))[0]
    assert not result.passed
    assert result.details["expected"] == "333.33"
    assert await rule.validate(_ctx({"budget": _budget()})) == []


async def test_reconciliation_balance_must_be_exact() -> None:
    rec = {
        "id": "r",
        "total_actual": "100.00",
        "unallocated": {},
        "unit_balances": [{"unit_ref": "U1", "demanded": "120.00", "actual_share": "100.00", "balance": "20.00"}],
    }
    assert (await ReconciliationBalanceRule().validate(_ctx({"reconciliation": rec})))[0].passed
    rec["unit_balances"][0]["balance"] = "19.99"
    assert not (await ReconciliationBalanceRule().validate(_ctx({"reconciliation": rec})))[0].passed


def test_rule_set_is_registered_and_resolved() -> None:
    register_service_charges_validation_rules()
    assert rule_registry.has_rules(SERVICE_CHARGES_RULE_SET)
    ids = {r["rule_id"] for r in rule_registry.list_rules(SERVICE_CHARGES_RULE_SET)}
    assert {"service_charges.budget_lines_non_negative", "service_charges.demands_match_budget"} <= ids


def test_demo_install_registers_rule_sets_a_module_owns() -> None:
    from app.core.demo_projects import _register_module_rule_sets

    rule_registry.unregister_rule_set(SERVICE_CHARGES_RULE_SET)
    assert not rule_registry.has_rules(SERVICE_CHARGES_RULE_SET)
    _register_module_rule_sets(["boq_quality", SERVICE_CHARGES_RULE_SET, "not-a-module"])
    assert rule_registry.has_rules(SERVICE_CHARGES_RULE_SET)
