# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An agreement and a contract that look like one subcontract are reported, never merged.

A subcontract can be written as an agreement on the Subcontractors page and as
a contract with a subcontractor in the contracts module. Linked, the pair
counts once; unlinked, finance counts it twice. Nothing in the data proves two
records are the same subcontract, so the matcher only proposes a pair when the
agreement is unlinked, no agreement claims the contract, both are live, the
currency is the same and the counterparty is the same by id or by company
name. A close value is recorded and decides nothing.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.subcontractors.validators import (
    check_unlinked_contract_twin,
    match_unlinked_twins,
    normalise_company_name,
)

register_builtin_rules()

SUB = "sub-1"
CONTACT = "contact-1"


def _agreement(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "ag-1",
        "title": "Drywall, block B",
        "status": "active",
        "currency": "EUR",
        "total_value": "120000.00",
        "contract_id": None,
        "dismissed_contract_ids": [],
        "party_ids": [SUB, CONTACT],
        "party_names": ["Suhi Zid d.o.o."],
    }
    row.update(over)
    return row


def _contract(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "ct-1",
        "code": "SC-009",
        "title": "Drywall subcontract",
        "status": "active",
        "currency": "EUR",
        "total_value": "120000.00",
        "party_ids": [SUB],
        "party_names": [],
    }
    row.update(over)
    return row


def test_the_same_subcontractor_and_currency_is_a_pair() -> None:
    (pair,) = match_unlinked_twins([_agreement()], [_contract()])
    assert (pair["agreement_id"], pair["contract_id"]) == ("ag-1", "ct-1")
    assert pair["matched_on"] == "counterparty"
    assert pair["value_close"] is True


def test_the_contact_the_contract_names_is_the_same_counterparty() -> None:
    (pair,) = match_unlinked_twins([_agreement()], [_contract(party_ids=[CONTACT])])
    assert pair["matched_on"] == "counterparty"


def test_the_same_company_under_another_spelling_is_a_pair() -> None:
    contract = _contract(party_ids=["someone-else"], party_names=["SUHI ZID, d.o.o"])
    (pair,) = match_unlinked_twins([_agreement()], [contract])
    assert pair["matched_on"] == "name"


def test_a_value_far_apart_is_still_proposed_and_says_so() -> None:
    (pair,) = match_unlinked_twins([_agreement()], [_contract(total_value="80000.00")])
    assert pair["value_close"] is False


@pytest.mark.parametrize(
    ("agreement", "contract"),
    [
        pytest.param(_agreement(), _contract(party_ids=["other"], party_names=["Beton Plus"]), id="other-party"),
        pytest.param(_agreement(), _contract(currency="USD"), id="other-currency"),
        pytest.param(_agreement(contract_id="ct-7"), _contract(), id="agreement-linked"),
        pytest.param(_agreement(dismissed_contract_ids=["ct-1"]), _contract(), id="dismissed"),
        pytest.param(_agreement(status="terminated"), _contract(), id="agreement-ended"),
        pytest.param(_agreement(), _contract(status="terminated"), id="contract-ended"),
        pytest.param(_agreement(currency=""), _contract(currency=""), id="no-currency"),
    ],
)
def test_no_pair(agreement: dict[str, object], contract: dict[str, object]) -> None:
    assert match_unlinked_twins([agreement], [contract]) == []


def test_a_contract_another_agreement_links_is_not_proposed_again() -> None:
    linked = _agreement(id="ag-0", contract_id="ct-1")
    assert match_unlinked_twins([linked, _agreement()], [_contract()]) == []


@pytest.mark.parametrize(
    ("a", "b"),
    [("Suhi Zid d.o.o.", "SUHI ZID"), ("Acme GmbH", "acme"), ("Beton-Plus Ltd.", "Beton Plus")],
)
def test_legal_forms_and_punctuation_do_not_decide_a_name(a: str, b: str) -> None:
    assert normalise_company_name(a) == normalise_company_name(b)


def test_a_name_of_only_a_legal_form_matches_nothing() -> None:
    assert normalise_company_name("d.o.o.") == ""
    contract = _contract(party_ids=["x"], party_names=["Ltd"])
    assert match_unlinked_twins([_agreement(party_names=["GmbH"])], [contract]) == []


def test_the_check_names_both_records() -> None:
    (pair,) = match_unlinked_twins([_agreement()], [_contract()])
    (finding,) = check_unlinked_contract_twin({"title": "Drywall, block B", "twin_candidates": [pair]})
    assert finding.params == {"agreement": "Drywall, block B", "contract": "SC-009 Drywall subcontract"}
    assert finding.details["contract_id"] == "ct-1"


@pytest.mark.asyncio
async def test_the_rule_warns_in_the_subcontract_set() -> None:
    (pair,) = match_unlinked_twins([_agreement()], [_contract()])
    report = await validation_engine.validate(
        data={"id": "ag-1", "title": "Drywall, block B", "twin_candidates": [pair]},
        rule_sets=["subcontract"],
        target_type="subcontract_agreement",
        target_id="ag-1",
        metadata={"locale": "en"},
    )
    (warning,) = [r for r in report.warnings if r.rule_id == "subcontract.unlinked_contract_twin"]
    assert "Drywall, block B" in warning.message
    assert "SC-009 Drywall subcontract" in warning.message
    assert "twice" in warning.message
    assert not [r for r in report.errors if r.rule_id == "subcontract.unlinked_contract_twin"]


@pytest.mark.asyncio
async def test_an_agreement_with_no_twin_passes_the_rule() -> None:
    report = await validation_engine.validate(
        data={"id": "ag-1", "title": "Drywall, block B", "twin_candidates": []},
        rule_sets=["subcontract"],
        target_type="subcontract_agreement",
        target_id="ag-1",
        metadata={"locale": "en"},
    )
    assert not [r for r in report.warnings if r.rule_id == "subcontract.unlinked_contract_twin"]
