# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The contract rules that check a VAT regime choice, run over the context the service builds.

The contexts here have the shape ``ContractsService.run_contract_rules`` and
``claim_rule_context`` produce. Each failing case changes one fact of an
Egyptian contract that qualifies for the transitional regime, so a rule that
ignores the fact passes it and fails here.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.contracts.messages import translate
from app.modules.contracts.validators import CONTRACTS_RULE_SET, PAY_APPLICATION_RULE_SET
from app.modules.contracts.vat_regime_rules import (
    ClaimVatRegimeInForceRule,
    ContractVatRegimeEligibleRule,
    ContractVatRegimeKnownRule,
    contract_facts,
    stated_regime,
)

pytestmark = pytest.mark.asyncio

TRANSITIONAL = "EG_CONSTR_TRANSITIONAL_36"


def _terms(code: str = TRANSITIONAL, **block: Any) -> dict[str, Any]:
    regime = {
        "code": code,
        "evidence": {
            "approved_certificate": {"reference": "IPC-07", "issued_on": "2025-06-30"},
            "einvoice": {"reference": "ETA-UUID-123", "issued_on": "2025-07-02"},
        },
        "allowed_increase_pct": "25",
    }
    regime.update(block)
    return {"vat_regime": regime}


def _contract(**changes: Any) -> dict[str, Any]:
    contract = {
        "id": "c-1",
        "code": "CT-EG-001",
        "status": "draft",
        "contract_type": "lump_sum",
        "terms": _terms(),
        "country_code": "EG",
        "signed_at": "2024-11-01",
        "start_date": "2024-12-01",
        "is_subcontract": False,
        "total_value": "10000000.0000",
        "original_contract_value": "10000000.0000",
    }
    contract.update(changes)
    return contract


def _ctx(data: dict[str, Any], rule_set: str = CONTRACTS_RULE_SET) -> ValidationContext:
    return ValidationContext(data=data, standard=rule_set, metadata={"locale": "en"})


async def _run(rule: Any, contract: dict[str, Any]) -> list[Any]:
    return await rule.validate(_ctx({"contract": contract}))


async def _failures(contract: dict[str, Any]) -> list[tuple[str, Severity]]:
    results = await _run(ContractVatRegimeKnownRule(), contract) + await _run(ContractVatRegimeEligibleRule(), contract)
    return [(r.details.get("finding", r.rule_id), r.severity) for r in results if not r.passed]


async def test_a_qualifying_contract_passes_both_rules() -> None:
    assert await _failures(_contract()) == []


async def test_a_contract_that_states_no_regime_is_not_reported_on() -> None:
    contract = _contract(terms={})
    assert await _run(ContractVatRegimeKnownRule(), contract) == []
    assert await _run(ContractVatRegimeEligibleRule(), contract) == []


async def test_a_regime_the_country_does_not_have_is_an_error() -> None:
    results = await _run(ContractVatRegimeKnownRule(), _contract(terms=_terms("DE_NOTHING")))
    assert [(r.passed, r.severity) for r in results] == [(False, Severity.ERROR)]
    assert "DE_NOTHING" in results[0].message and "EG" in results[0].message


async def test_an_egyptian_regime_on_a_german_project_is_an_error() -> None:
    assert await _failures(_contract(country_code="DE")) == [("contracts.vat_regime_known", Severity.ERROR)]


async def test_a_project_without_a_country_is_a_warning_not_a_pass() -> None:
    assert await _failures(_contract(country_code=None)) == [("contracts.vat_regime_known", Severity.WARNING)]


async def test_a_contract_signed_after_the_cutoff_is_blocked() -> None:
    failures = await _failures(_contract(signed_at="2025-07-18"))
    assert failures == [("contract_too_late", Severity.ERROR)]


async def test_a_contract_signed_the_day_before_passes() -> None:
    assert await _failures(_contract(signed_at="2025-07-17")) == []


async def test_a_missing_einvoice_is_blocked_and_named() -> None:
    terms = _terms(evidence={"approved_certificate": {"reference": "IPC-07", "issued_on": "2025-06-30"}})
    results = await _run(ContractVatRegimeEligibleRule(), _contract(terms=terms))
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].message == translate(
        "vat_regime.evidence_missing.fail",
        locale="en",
        regime=TRANSITIONAL,
        evidence=translate("vat_regime.evidence_kinds.einvoice", locale="en"),
    )


async def test_evidence_issued_on_the_cutoff_is_blocked() -> None:
    terms = _terms(
        evidence={
            "approved_certificate": {"reference": "IPC-07", "issued_on": "2025-06-30"},
            "einvoice": {"reference": "ETA-UUID-123", "issued_on": "2025-07-18"},
        }
    )
    assert await _failures(_contract(terms=terms)) == [("evidence_too_late", Severity.ERROR)]


async def test_a_subcontract_without_the_main_contractor_certificate_is_blocked() -> None:
    assert await _failures(_contract(is_subcontract=True)) == [("evidence_missing", Severity.ERROR)]


async def test_a_scope_increase_beyond_the_contracts_limit_is_blocked() -> None:
    failures = await _failures(_contract(total_value="12500001.0000"))
    assert failures == [("scope_increase_new_contract", Severity.ERROR)]


async def test_an_increase_with_no_stated_limit_is_a_warning() -> None:
    contract = _contract(terms=_terms(allowed_increase_pct=None), total_value="10000001.0000")
    assert await _failures(contract) == [("scope_increase_unjudged", Severity.WARNING)]


async def test_the_standard_regime_needs_no_evidence() -> None:
    contract = _contract(terms={"vat_regime": {"code": "EG_CONSTR_STANDARD"}}, signed_at="2026-01-10")
    assert await _failures(contract) == []


def test_the_facts_are_read_from_the_terms_and_the_contract() -> None:
    contract = _contract()
    block = stated_regime(contract["terms"])
    assert block is not None
    facts = contract_facts(contract, block)
    assert facts.signed_on is not None and facts.signed_on.isoformat() == "2024-11-01"
    assert set(facts.evidence) == {"approved_certificate", "einvoice"}
    assert str(facts.allowed_increase_pct) == "25"
    assert stated_regime({"vat_regime": {"code": "  "}}) is None


# ── A claim dated outside the regime ─────────────────────────────────────────


async def _claim_results(code: str, **claim: Any) -> list[Any]:
    data = {
        "claim": {"id": "pc-1", "number": "IPC-12", **claim},
        "vat_regime": {"code": code, "country_code": "EG"},
    }
    return await ClaimVatRegimeInForceRule().validate(_ctx(data, PAY_APPLICATION_RULE_SET))


async def test_a_claim_after_the_schedule_tax_ended_is_blocked() -> None:
    results = await _claim_results("EG_CONSTR_SCHEDULE_5", application_date="2025-07-18")
    assert [(r.passed, r.severity) for r in results] == [(False, Severity.ERROR)]
    assert "2025-07-17" in results[0].message
    assert "EG_CONSTR_STANDARD" in results[0].message


async def test_a_claim_on_the_last_day_of_the_schedule_tax_passes() -> None:
    results = await _claim_results("EG_CONSTR_SCHEDULE_5", application_date="2025-07-17")
    assert [r.passed for r in results] == [True]


async def test_a_transitional_claim_before_the_regime_existed_is_blocked() -> None:
    results = await _claim_results(TRANSITIONAL, claim_date="2025-07-17")
    assert [r.passed for r in results] == [False]
    assert "2025-07-18" in results[0].message


async def test_a_claim_on_a_contract_with_no_regime_is_not_reported_on() -> None:
    data = {"claim": {"id": "pc-1", "application_date": "2025-07-18"}}
    assert await ClaimVatRegimeInForceRule().validate(_ctx(data, PAY_APPLICATION_RULE_SET)) == []


async def test_the_rules_are_registered_where_the_service_runs_them() -> None:
    from app.core.validation.engine import rule_registry
    from app.modules.contracts.validators import register_contracts_validation_rules

    register_contracts_validation_rules()
    contract_ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets([CONTRACTS_RULE_SET])}
    claim_ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets([PAY_APPLICATION_RULE_SET])}
    assert {"contracts.vat_regime_known", "contracts.vat_regime_eligible"} <= contract_ids
    assert "pay_application.vat_regime_in_force" in claim_ids
