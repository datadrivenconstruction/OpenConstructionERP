# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The UK cost-plan and statutory rules.

Two rule sets, and the split between them is the point. ``nrm`` is a method of
measurement and travels wherever the method is used, so an Australian project
measured to NRM gets those four rules and none of the British statute. The
``uk_statutory`` set is the law of one country, is switched on by the UK pack,
and asks only what an estimate records about itself.

Every statutory rule here checks that something is stated rather than what it
says, with one exception. The higher-risk building test is statute and is
checkable, so it is checked: the estimate's own storeys, height and dwelling
count either produce the answer it declared or they do not.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    NRMBaseDateDeclared,
    NRMContractorCostsPresent,
    NRMCostPlanStageDeclared,
    NRMRiskAllowancePresent,
    UKCDMDutyHoldersDeclared,
    UKContractFormDeclared,
    UKHigherRiskBuildingRegime,
    UKPaymentRegimeDeclared,
    UKRetentionDeclared,
    UKVATTreatmentDeclared,
)

MEASURED = [
    {"id": "p1", "ordinal": "1.1", "unit": "m3", "quantity": 100, "unit_rate": "180", "classification": {"nrm": "1.1"}},
    {"id": "p2", "ordinal": "2.1", "unit": "t", "quantity": 40, "unit_rate": "2100", "classification": {"nrm": "2.1"}},
    {"id": "p3", "ordinal": "5.1", "unit": "m2", "quantity": 900, "unit_rate": "310", "classification": {"nrm": "5.1"}},
]


def bill(
    positions: list[dict[str, Any]] | None = None,
    *,
    markups: list[dict[str, Any]] | None = None,
    **fields: Any,
) -> ValidationContext:
    """A context shaped like the one the payload builder hands the engine.

    The bill block and the markup stack are both in it, because that is what
    the product supplies. A fixture that puts the estimate's own facts in the
    run metadata proves the rule can read a dict and nothing about whether the
    product ever fills one.
    """
    return ValidationContext(
        data={
            "positions": MEASURED if positions is None else positions,
            "boq": fields,
            "markups": markups or [],
        },
        metadata={"locale": "en"},
    )


def markup(category: str, *, active: bool = True) -> dict[str, Any]:
    return {"name": category.title(), "category": category, "percentage": "10", "is_active": active}


# ── The cost plan says what it is ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_bill_that_is_not_measured_to_nrm_is_not_asked_about_a_base_date() -> None:
    """The silence that keeps the rule set readable. A German bill carrying no
    NRM code is not an NRM cost plan missing its base date, and a finding on it
    reads as the rule set malfunctioning rather than as advice."""
    german = [{"id": "p1", "ordinal": "1", "classification": {"din276": "300"}}]
    assert await NRMBaseDateDeclared().validate(bill(german)) == []
    assert await NRMCostPlanStageDeclared().validate(bill(german)) == []
    assert await NRMContractorCostsPresent().validate(bill(german)) == []
    assert await NRMRiskAllowancePresent().validate(bill(german)) == []


@pytest.mark.asyncio
async def test_a_cost_plan_without_a_base_date_is_reported_once() -> None:
    """Once, not once per line. The base date is one fact about the document."""
    results = await NRMBaseDateDeclared().validate(bill())
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].element_ref is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [{"base_date": "2026-Q1"}, {"metadata": {"base_date": "2026-Q1"}}, {"metadata": {"price_level": "2026-Q1"}}],
    ids=["column", "metadata", "price_level"],
)
async def test_a_declared_base_date_passes_from_any_of_its_three_homes(fields: dict[str, Any]) -> None:
    """The bill carries a base date in a column of its own and an importer may
    leave the same fact in the metadata blob under either name. Reading one
    place would have called two thirds of correct estimates silent."""
    results = await NRMBaseDateDeclared().validate(bill(**fields))
    assert results[0].passed
    assert results[0].details["base_date"] == "2026-Q1"


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_a_blank_base_date_is_not_a_declaration(blank: Any) -> None:
    assert not (await NRMBaseDateDeclared().validate(bill(base_date=blank)))[0].passed


@pytest.mark.asyncio
async def test_the_stage_is_read_from_the_phase_or_from_the_estimate_type() -> None:
    """A cost plan's expected accuracy is set by the stage it was produced at.
    The stage is recorded as a phase by the demo templates and as an estimate
    type by the bill itself, and either answers the question."""
    assert (await NRMCostPlanStageDeclared().validate(bill(metadata={"phase": "RIBA Stage 4"})))[0].passed
    assert (await NRMCostPlanStageDeclared().validate(bill(estimate_type="Cost Plan 2")))[0].passed
    assert not (await NRMCostPlanStageDeclared().validate(bill()))[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "estimate_type",
    ["Cost Plan 2", "formal_cost_plan_1", "Order of Cost Estimate", "pre-tender estimate", "RIBA Stage 3", "Stage 4"],
)
async def test_an_estimate_type_naming_a_stage_declares_it(estimate_type: str) -> None:
    assert (await NRMCostPlanStageDeclared().validate(bill(estimate_type=estimate_type)))[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize("estimate_type", ["budget", "detailed", "order_of_magnitude", "preliminary", "conceptual"])
async def test_an_estimate_type_that_is_no_stage_does_not_declare_one(estimate_type: str) -> None:
    """The field also says what kind of bill it is. The demo seeder labels
    every control budget "budget", and the warning must not go quiet because
    of a label that says nothing about the design stage."""
    assert not (await NRMCostPlanStageDeclared().validate(bill(estimate_type=estimate_type)))[0].passed


# ── The money that is never measured ─────────────────────────────────────


@pytest.mark.asyncio
async def test_preliminaries_and_profit_are_two_findings_not_one() -> None:
    """They are two decisions and go missing separately. One finding covering
    both would name neither."""
    results = await NRMContractorCostsPresent().validate(bill())
    assert len(results) == 2
    assert not any(result.passed for result in results)


@pytest.mark.asyncio
async def test_contractor_costs_carried_as_markups_are_carried() -> None:
    """The half of this rule that stops it being noise. A UK cost plan puts
    preliminaries and OH&P either in NRM groups 9 and 10 or in a markup stack
    on top of the measured work, and both are correct. Reading only the groups
    would convict every estimate built the second way, which is most of them."""
    results = await NRMContractorCostsPresent().validate(bill(markups=[markup("overhead"), markup("profit")]))
    assert all(result.passed for result in results)
    assert all(result.details["carried_as_markup"] for result in results)


@pytest.mark.asyncio
async def test_contractor_costs_carried_as_group_elements_are_carried() -> None:
    lines = [*MEASURED, {"id": "p9", "ordinal": "9", "classification": {"nrm": "9.1"}}]
    lines.append({"id": "p10", "ordinal": "10", "classification": {"nrm": "10.1"}})
    results = await NRMContractorCostsPresent().validate(bill(lines))
    assert all(result.passed for result in results)
    assert all(result.details["carried_as_element"] for result in results)


@pytest.mark.asyncio
async def test_a_switched_off_markup_is_not_a_carried_cost() -> None:
    """A line switched off is money the estimate is not asking for. Counting it
    would let a cost plan pass by carrying a preliminaries line at nothing."""
    results = await NRMContractorCostsPresent().validate(bill(markups=[markup("overhead", active=False)]))
    assert not results[0].passed


@pytest.mark.asyncio
async def test_a_risk_allowance_is_read_from_either_carrier() -> None:
    assert not (await NRMRiskAllowancePresent().validate(bill()))[0].passed
    assert (await NRMRiskAllowancePresent().validate(bill(markups=[markup("contingency")])))[0].passed
    risk_line = [*MEASURED, {"id": "p13", "ordinal": "13", "classification": {"nrm": "13.1"}}]
    assert (await NRMRiskAllowancePresent().validate(bill(risk_line)))[0].passed


# ── The statutory set ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_contract_form_is_a_thing_the_estimate_has_to_say() -> None:
    """Preliminaries, risk and the payment terms are priced differently under a
    different form, so a figure without one means little."""
    assert not (await UKContractFormDeclared().validate(bill()))[0].passed
    results = await UKContractFormDeclared().validate(bill(metadata={"contract_form": "JCT SBC/Q 2024"}))
    assert results[0].passed
    assert results[0].details["contract_form"] == "JCT SBC/Q 2024"


@pytest.mark.asyncio
async def test_a_payment_regime_needs_both_dates_and_names_the_one_it_lacks() -> None:
    """The Construction Act requires a contract to fix when a payment becomes
    due and its final date for payment. A contract fixing neither is not free
    of them; the Scheme supplies both, and the parties then find their payment
    terms in a statutory instrument rather than in what they signed."""
    half = await UKPaymentRegimeDeclared().validate(bill(metadata={"payment_regime": {"due_date_days": 21}}))
    assert not half[0].passed
    assert "final date for payment" in half[0].message
    assert "due date" not in half[0].message

    whole = await UKPaymentRegimeDeclared().validate(
        bill(metadata={"payment_regime": {"due_date_days": 21, "final_date_for_payment_days": 35}})
    )
    assert whole[0].passed


@pytest.mark.asyncio
async def test_a_payment_regime_may_also_sit_flat_on_the_metadata() -> None:
    """An importer that has no nested block still records the two dates."""
    results = await UKPaymentRegimeDeclared().validate(
        bill(metadata={"due_date": "21 days from the valuation", "final_date": "14 days after that"})
    )
    assert results[0].passed


@pytest.mark.asyncio
async def test_no_retention_is_an_answer_and_an_empty_block_is_not() -> None:
    """Retention is cash the contractor has earned and cannot draw. Saying none
    applies is a decision; leaving the field blank is not."""
    assert (await UKRetentionDeclared().validate(bill(metadata={"retention": "none, waived at tender"})))[0].passed
    assert not (await UKRetentionDeclared().validate(bill(metadata={"retention": {}})))[0].passed
    assert not (await UKRetentionDeclared().validate(bill(metadata={"retention": "  "})))[0].passed


@pytest.mark.asyncio
async def test_a_missing_cdm_appointment_is_named() -> None:
    """Where more than one contractor works on a project the client must
    appoint both in writing, and a client who does not holds the duties."""
    results = await UKCDMDutyHoldersDeclared().validate(
        bill(metadata={"cdm_2015": {"principal_designer": "Halberd Whitmore"}})
    )
    assert not results[0].passed
    assert "principal contractor" in results[0].message
    both = await UKCDMDutyHoldersDeclared().validate(
        bill(metadata={"cdm_2015": {"principal_designer": "A", "principal_contractor": "B"}})
    )
    assert both[0].passed


# ── The one statutory rule that checks an answer, not its presence ───────


@pytest.mark.asyncio
async def test_an_unanswered_higher_risk_question_is_reported() -> None:
    results = await UKHigherRiskBuildingRegime().validate(bill())
    assert not results[0].passed
    assert results[0].details["higher_risk_building"] is None


@pytest.mark.asyncio
async def test_a_tall_office_is_not_a_higher_risk_building() -> None:
    """Both halves of the statutory test count. Ten storeys clears the height
    half; with no dwellings the building is out of the regime, and treating it
    as in buys a gateway programme nobody needed."""
    results = await UKHigherRiskBuildingRegime().validate(
        bill(
            metadata={
                "building_safety_act": {
                    "higher_risk_building": False,
                    "storeys": 10,
                    "height_m": 44.5,
                    "residential_units": 0,
                }
            }
        )
    )
    assert results[0].passed
    assert results[0].details["derived"] is False


@pytest.mark.asyncio
async def test_a_tall_office_declared_higher_risk_is_contradicted_by_its_own_dimensions() -> None:
    """The finding this rule exists for, in the direction that costs money for
    nothing rather than the direction that stops occupation."""
    results = await UKHigherRiskBuildingRegime().validate(
        bill(
            metadata={
                "building_safety_act": {
                    "higher_risk_building": True,
                    "storeys": 10,
                    "height_m": 44.5,
                    "residential_units": 0,
                }
            }
        )
    )
    assert not results[0].passed
    assert results[0].details["derived"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("storeys", "height_m", "units", "expected"),
    [
        (7, 21.0, 40, True),
        (6, 19.0, 40, True),
        (8, 17.0, 40, True),
        (6, 17.0, 40, False),
        (12, 40.0, 1, False),
        (12, 40.0, 2, True),
    ],
    ids=["seven_storeys", "over_eighteen_metres", "storeys_alone", "under_both", "one_dwelling", "two_dwellings"],
)
async def test_the_statutory_threshold_is_height_or_storeys_and_two_dwellings(
    storeys: int, height_m: float, units: int, expected: bool
) -> None:
    """The threshold, read as an OR inside an AND. The single-dwelling row is
    the one that matters: a tall building with one flat in it is not higher
    risk, and the rule has to agree with that rather than with the height."""
    results = await UKHigherRiskBuildingRegime().validate(
        bill(
            metadata={
                "building_safety_act": {
                    "higher_risk_building": expected,
                    "storeys": storeys,
                    "height_m": height_m,
                    "residential_units": units,
                }
            }
        )
    )
    assert results[0].passed, f"{storeys} storeys, {height_m} m, {units} dwellings should derive {expected}"
    assert results[0].details["derived"] is expected


@pytest.mark.asyncio
async def test_a_declaration_with_no_dimensions_is_left_alone() -> None:
    """Declared but not checkable. Reported as passing rather than as a second
    finding: the estimate answered what it was asked, and inventing a dimension
    to disagree with it would be the rule making something up."""
    results = await UKHigherRiskBuildingRegime().validate(
        bill(metadata={"building_safety_act": {"higher_risk_building": True}})
    )
    assert results[0].passed
    assert results[0].details["derived"] is None


@pytest.mark.asyncio
async def test_vat_is_declared_by_a_note_or_by_the_markup_stack() -> None:
    """An estimate that carries a tax line has said how VAT is treated. One
    that carries none has to say so in words, because zero-rated new dwellings
    and the domestic reverse charge both look like a missing line."""
    assert not (await UKVATTreatmentDeclared().validate(bill()))[0].passed
    assert (await UKVATTreatmentDeclared().validate(bill(markups=[markup("tax")])))[0].passed
    assert (await UKVATTreatmentDeclared().validate(bill(metadata={"vat_treatment": "Zero-rated new dwellings"})))[
        0
    ].passed


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["care_home", "hospital"])
async def test_a_care_home_or_hospital_meets_the_occupancy_half(flag: str) -> None:
    """The dwelling count is a number the building has; these are a question
    about what it is for. A care home clearing the height test is inside the
    design and construction regime with no dwellings in it at all."""
    results = await UKHigherRiskBuildingRegime().validate(
        bill(metadata={"building_safety_act": {"higher_risk_building": True, "storeys": 8, flag: True}})
    )
    assert results[0].passed
    assert results[0].details["derived"] is True
    assert results[0].details["occupancy_flags"] == [flag]


@pytest.mark.asyncio
async def test_a_low_care_home_still_needs_the_height() -> None:
    """The two halves are an AND. An occupancy flag does not carry a building
    that is neither tall enough nor high enough into the regime."""
    results = await UKHigherRiskBuildingRegime().validate(
        bill(metadata={"building_safety_act": {"higher_risk_building": False, "storeys": 3, "care_home": True}})
    )
    assert results[0].passed
    assert results[0].details["derived"] is False
