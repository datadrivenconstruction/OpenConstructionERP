# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules V6 to V10 and V15 of the cost chain: each fails on its defect and passes on a clean chain."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.chain_rules import (
    COST_CHAIN_RULES,
    PAYLOAD_KEY,
    RULE_SET,
    ChangeApprovalRule,
    CommitmentWithinTargetRule,
    ContractSumRule,
    InvoiceHasContractRule,
    MeasurementWithinCommitmentRule,
    QuantityOverrunRule,
    register_cost_chain_rules,
)

pytestmark = pytest.mark.asyncio


def _contract(**extra: Any) -> dict[str, Any]:
    row = {
        "id": "c1",
        "code": "SC-01",
        "contract_type": "lump_sum",
        "status": "active",
        "total_value": "1000.00",
        "line_count": 2,
        "lines_total": "1000.00",
        "target": "1000.00",
        "committed": "1000.00",
        "measured_value": "400.00",
    }
    row.update(extra)
    return row


def _clean() -> dict[str, Any]:
    return {
        "currency": "EUR",
        "contracts": [_contract()],
        "lines": [
            {
                "id": "l1",
                "code": "010",
                "contract_code": "SC-01",
                "unit": "m3",
                "quantity": "20",
                "measured_quantity": "21",
            }
        ],
        "change_orders": [
            {"id": "o1", "code": "CO-1", "status": "approved", "approved_amount": "50", "approved_at": "2026-03-01"},
            {"id": "o2", "code": "CO-2", "status": "draft", "approved_amount": None, "approved_at": ""},
        ],
        "billed_unapproved": [],
        "accounts": [{"id": "a1", "code": "330", "committed": "1000.00", "planned": "950.00"}],
        "invoices_without_contract": [],
    }


async def _run(rule_cls: type, payload: dict[str, Any], locale: str = "en") -> list:
    context = ValidationContext(data={PAYLOAD_KEY: payload}, metadata={"locale": locale})
    return [r for r in await rule_cls().validate(context) if not r.passed]


@pytest.mark.parametrize("rule_cls", COST_CHAIN_RULES)
async def test_a_clean_chain_passes_every_rule(rule_cls: type) -> None:
    context = ValidationContext(data={PAYLOAD_KEY: _clean()}, metadata={"locale": "en"})
    results = await rule_cls().validate(context)
    assert results and all(r.passed for r in results)


async def test_rules_are_silent_on_other_data() -> None:
    assert await ContractSumRule().validate(ValidationContext(data={"positions": []})) == []


async def test_the_rule_set_holds_the_six_rules() -> None:
    register_cost_chain_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([RULE_SET])}
    assert ids == {
        "cost_chain.contract_sum",
        "cost_chain.change_approval",
        "cost_chain.commitment_within_target",
        "cost_chain.quantity_overrun",
        "cost_chain.measurement_within_commitment",
        "cost_chain.invoice_has_contract",
    }


async def test_v6_schedule_differs_error_on_measured_warning_on_lump_sum() -> None:
    payload = _clean()
    payload["contracts"] = [
        _contract(id="c1", lines_total="990.00"),
        _contract(id="c2", code="SC-02", contract_type="unit_price", lines_total="1100.00"),
        _contract(id="c3", code="SC-03", line_count=0, lines_total="0"),
        _contract(id="c4", code="SC-04", lines_total="1000.01"),
    ]
    found = {r.element_ref: r for r in await _run(ContractSumRule, payload)}
    assert set(found) == {"c1", "c2", "c3"}
    assert found["c1"].severity.value == "warning"
    assert found["c1"].details["difference"] == "10.00"
    assert found["c2"].severity.value == "error"
    assert found["c2"].details["difference"] == "-100.00"
    assert found["c3"].details["problem"] == "contract_without_schedule"
    assert "1,000.00" in found["c3"].message or "1000.00" in found["c3"].message


async def test_v7_approved_change_needs_amount_and_date_and_no_billing_before_approval() -> None:
    payload = _clean()
    payload["change_orders"] = [
        {"id": "o1", "code": "CO-1", "status": "executed", "approved_amount": None, "approved_at": ""},
    ]
    payload["billed_unapproved"] = [
        {"line_id": "l9", "contract_code": "SC-01", "change_code": "CO-2", "change_status": "submitted", "billed": "75"}
    ]
    found = await _run(ChangeApprovalRule, payload)
    assert [r.details["problem"] for r in found] == [
        "change_without_agreed_amount",
        "change_without_approval_date",
        "billed_before_approval",
    ]
    assert found[2].element_ref == "l9" and found[2].severity.value == "warning"
    assert "CO-2" in found[2].message


async def test_v8_contract_over_its_bill_and_account_over_plan_beyond_tolerance() -> None:
    payload = _clean()
    payload["contracts"] = [_contract(committed="1150.00"), _contract(id="c2", committed="1090.00")]
    payload["accounts"] = [{"id": "a1", "code": "330", "committed": "1200.00", "planned": "1000.00"}]
    found = await _run(CommitmentWithinTargetRule, payload)
    assert [(r.element_ref, r.details["problem"]) for r in found] == [
        ("c1", "contract_over_target"),
        ("a1", "account_over_plan"),
    ]
    assert found[0].details["difference"] == "150.00"
    assert found[0].details["tolerance"] == "10"


async def test_v8_tolerance_comes_from_the_payload() -> None:
    payload = _clean()
    payload["target_tolerance"] = "0.20"
    payload["contracts"] = [_contract(committed="1150.00")]
    assert await _run(CommitmentWithinTargetRule, payload) == []


async def test_v9_measured_quantity_beyond_tolerance() -> None:
    payload = _clean()
    payload["lines"][0]["measured_quantity"] = "23"
    found = await _run(QuantityOverrunRule, payload)
    assert len(found) == 1
    assert found[0].details["over"] == "15.0"
    assert "m3" in found[0].message


async def test_v10_measurement_above_the_commitment() -> None:
    payload = _clean()
    payload["contracts"] = [_contract(measured_value="1000.02")]
    found = await _run(MeasurementWithinCommitmentRule, payload)
    assert [r.details["difference"] for r in found] == ["0.02"]


async def test_v15_supplier_invoice_without_a_commitment_is_an_error() -> None:
    payload = _clean()
    payload["invoices_without_contract"] = [{"id": "i1", "number": "INV-7", "amount": "120.00"}]
    found = await _run(InvoiceHasContractRule, payload)
    assert len(found) == 1
    assert found[0].severity.value == "error"
    assert "INV-7" in found[0].message


async def test_messages_follow_the_callers_locale() -> None:
    payload = _clean()
    payload["invoices_without_contract"] = [{"id": "i1", "number": "INV-7", "amount": "120.00"}]
    en = (await _run(InvoiceHasContractRule, payload, "en"))[0]
    de = (await _run(InvoiceHasContractRule, payload, "de"))[0]
    assert en.message != de.message
    assert "INV-7" in de.message
    assert not en.message.startswith("cost_chain.")
    assert not de.suggestion.startswith("cost_chain.")
