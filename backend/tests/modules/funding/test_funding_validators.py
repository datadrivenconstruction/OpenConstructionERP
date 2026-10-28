# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The five ways public funding is lost, and the rules that catch them.

Each rule is exercised directly against a hand-built context rather than
through the service, so the assertions are about the rule's own judgement and
not about how a repository happened to load a row. The rules are instantiated
here instead of resolved from the registry for the same reason, and because a
test that registers into the process-wide registry changes what every later
test in the session sees.

Every rule is checked in three directions: the failing case it exists for, the
passing case it must stay quiet about, and the incomplete case where it has
nothing to compare yet. The third is the one that decides whether people read
the findings or learn to scroll past them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.validation.engine import RuleResult, Severity, ValidationContext
from app.modules.funding.validators import (
    FUNDING_RULES,
    FundingCostsFallInTheAwardPeriod,
    FundingCumulationWithinAidIntensity,
    FundingMeasureStartsAfterApplication,
    FundingOwnShareIsCovered,
    FundingProofOfUseIsOnTime,
)


def context(locale: str = "en", **sections: Any) -> ValidationContext:
    """A validation context carrying only the sections a test cares about."""
    data: dict[str, Any] = {
        "application": {},
        "programme": {},
        "disbursements": [],
        "proofs_of_use": [],
        "project_applications": [],
        "clock": {},
    }
    data.update(sections)
    return ValidationContext(
        data=data,
        project_id=str(data["application"].get("project_id") or ""),
        metadata={"locale": locale},
    )


def only(results: list[RuleResult]) -> RuleResult:
    """The single finding a rule was expected to return."""
    assert len(results) == 1, [row.message for row in results]
    return results[0]


# ── The prohibition on starting early ───────────────────────────────────


async def test_work_begun_before_the_application_was_filed_fails() -> None:
    result = only(
        await FundingMeasureStartsAfterApplication().validate(
            context(
                application={"code": "A-1", "measure_start_on": "2026-01-10", "submitted_on": "2026-02-01"},
                programme={"requires_application_before_start": True},
            )
        )
    )
    assert result.passed is False
    assert result.severity == Severity.ERROR
    assert "2026-01-10" in result.message
    assert "2026-02-01" in result.message
    assert result.element_ref == "A-1"


async def test_work_begun_after_the_application_was_filed_passes() -> None:
    result = only(
        await FundingMeasureStartsAfterApplication().validate(
            context(
                application={"code": "A-1", "measure_start_on": "2026-03-01", "submitted_on": "2026-02-01"},
                programme={"requires_application_before_start": True},
            )
        )
    )
    assert result.passed is True
    assert result.suggestion is None


async def test_an_early_start_permitted_in_writing_passes_but_wants_the_reference() -> None:
    """The fact is fine and the evidence for it is missing, which an auditor asks for."""
    result = only(
        await FundingMeasureStartsAfterApplication().validate(
            context(
                application={
                    "code": "A-1",
                    "measure_start_on": "2026-01-10",
                    "submitted_on": "2026-02-01",
                    "early_start_approved": True,
                },
                programme={"requires_application_before_start": True},
            )
        )
    )
    assert result.passed is True
    assert result.suggestion is not None
    assert "2026-01-10" in result.message


async def test_an_early_start_with_its_permission_on_file_says_nothing_further() -> None:
    """Permitted and evidenced is simply in order, and must not read as a breach.

    The failing branch used to fire here as well, so the same finding came back
    passed and carrying the sentence that says the measure is unfundable.
    """
    result = only(
        await FundingMeasureStartsAfterApplication().validate(
            context(
                application={
                    "code": "A-1",
                    "measure_start_on": "2026-01-10",
                    "submitted_on": "2026-02-01",
                    "early_start_approved": True,
                    "early_start_reference": "Az. 12/2026",
                },
                programme={"requires_application_before_start": True},
            )
        )
    )
    assert result.passed is True
    assert result.suggestion is None
    assert "2026-01-10" not in result.message


async def test_a_programme_that_allows_a_free_start_is_not_checked_at_all() -> None:
    """The exemption is a property of the programme, not something an applicant grants itself."""
    results = await FundingMeasureStartsAfterApplication().validate(
        context(
            application={"measure_start_on": "2026-01-10", "submitted_on": "2026-02-01"},
            programme={"requires_application_before_start": False},
        )
    )
    assert results == []


@pytest.mark.parametrize(
    "application",
    [
        {},
        {"measure_start_on": "2026-01-10"},
        {"submitted_on": "2026-02-01"},
        {"measure_start_on": "", "submitted_on": "2026-02-01"},
    ],
)
async def test_a_draft_with_nothing_to_compare_is_not_a_finding(application: dict[str, Any]) -> None:
    """Reporting a draft as a breach trains people to ignore the rule."""
    results = await FundingMeasureStartsAfterApplication().validate(
        context(application=application, programme={"requires_application_before_start": True})
    )
    assert results == []


# ── Costs inside the awarded window ─────────────────────────────────────

PERIOD = {"award_period_start": "2026-01-01", "award_period_end": "2026-12-31"}


@pytest.mark.parametrize(
    ("period_from", "period_to", "marker"),
    [
        ("2025-12-01", "2026-03-01", "2026-01-01"),
        ("2026-06-01", "2027-02-01", "2026-12-31"),
    ],
)
async def test_a_draw_reaching_outside_the_window_fails(period_from: str, period_to: str, marker: str) -> None:
    result = only(
        await FundingCostsFallInTheAwardPeriod().validate(
            context(
                application=PERIOD,
                disbursements=[
                    {
                        "id": "d1",
                        "code": "MA-1",
                        "status": "submitted",
                        "period_from": period_from,
                        "period_to": period_to,
                    }
                ],
            )
        )
    )
    assert result.passed is False
    assert result.severity == Severity.ERROR
    assert "MA-1" in result.message
    assert marker in result.message


async def test_a_draw_reaching_outside_both_ends_says_so_once() -> None:
    result = only(
        await FundingCostsFallInTheAwardPeriod().validate(
            context(
                application=PERIOD,
                disbursements=[
                    {
                        "id": "d1",
                        "code": "MA-1",
                        "status": "submitted",
                        "period_from": "2025-12-01",
                        "period_to": "2027-02-01",
                    }
                ],
            )
        )
    )
    assert result.passed is False
    assert "2026-01-01" in result.message
    assert "2026-12-31" in result.message


async def test_a_draw_inside_the_window_passes() -> None:
    result = only(
        await FundingCostsFallInTheAwardPeriod().validate(
            context(
                application=PERIOD,
                disbursements=[
                    {
                        "id": "d1",
                        "code": "MA-1",
                        "status": "submitted",
                        "period_from": "2026-02-01",
                        "period_to": "2026-03-01",
                    }
                ],
            )
        )
    )
    assert result.passed is True


async def test_the_boundary_days_themselves_are_inside_the_window() -> None:
    """An award period that opens on the first funds costs dated the first."""
    result = only(
        await FundingCostsFallInTheAwardPeriod().validate(
            context(
                application=PERIOD,
                disbursements=[
                    {
                        "id": "d1",
                        "code": "MA-1",
                        "status": "submitted",
                        "period_from": "2026-01-01",
                        "period_to": "2026-12-31",
                    }
                ],
            )
        )
    )
    assert result.passed is True


async def test_a_draft_draw_is_a_working_note_and_is_not_judged() -> None:
    results = await FundingCostsFallInTheAwardPeriod().validate(
        context(
            application=PERIOD,
            disbursements=[
                {"id": "d1", "code": "MA-1", "status": "draft", "period_from": "2020-01-01", "period_to": "2020-02-01"},
                {"id": "d2", "code": "MA-2", "period_from": "2020-01-01", "period_to": "2020-02-01"},
            ],
        )
    )
    assert results == []


async def test_without_an_award_period_there_is_nothing_to_be_outside_of() -> None:
    results = await FundingCostsFallInTheAwardPeriod().validate(
        context(
            application={},
            disbursements=[{"id": "d1", "status": "submitted", "period_from": "2020-01-01", "period_to": "2020-02-01"}],
        )
    )
    assert results == []


async def test_a_submitted_draw_that_names_no_period_is_skipped_not_failed() -> None:
    results = await FundingCostsFallInTheAwardPeriod().validate(
        context(application=PERIOD, disbursements=[{"id": "d1", "status": "submitted"}])
    )
    assert results == []


# ── The share the applicant has to carry ────────────────────────────────


async def test_an_own_contribution_below_the_required_share_fails() -> None:
    result = only(
        await FundingOwnShareIsCovered().validate(
            context(
                application={
                    "code": "A-1",
                    "currency": "EUR",
                    "eligible_cost_base": Decimal("100000"),
                    "own_share_amount": "15000",
                },
                programme={"own_share_percent": Decimal("20")},
            )
        )
    )
    assert result.passed is False
    assert result.severity == Severity.WARNING
    # Both amounts say which currency they are in. A workspace running a euro
    # programme beside a sterling one otherwise gets two findings whose
    # figures look comparable and are not.
    assert "20,000.00 EUR" in result.message
    assert "15,000.00 EUR" in result.message


async def test_a_currency_with_no_subunit_is_not_given_two_decimals() -> None:
    """Two decimals on a rupiah invite the reader to hunt a decimal error."""
    result = only(
        await FundingOwnShareIsCovered().validate(
            context(
                application={
                    "code": "A-1",
                    "currency": "IDR",
                    "eligible_cost_base": "1000000",
                    "own_share_amount": "0",
                },
                programme={"own_share_percent": "20"},
            )
        )
    )
    assert "200,000 IDR" in result.message


async def test_an_application_with_no_currency_still_states_its_amounts() -> None:
    """A missing currency degrades to a bare figure rather than to no finding."""
    result = only(
        await FundingOwnShareIsCovered().validate(
            context(
                application={"code": "A-1", "eligible_cost_base": "100000", "own_share_amount": "15000"},
                programme={"own_share_percent": "20"},
            )
        )
    )
    assert "20,000.00" in result.message
    assert "EUR" not in result.message


async def test_an_own_contribution_that_meets_the_share_passes() -> None:
    result = only(
        await FundingOwnShareIsCovered().validate(
            context(
                application={"eligible_cost_base": "100000", "own_share_amount": "20000"},
                programme={"own_share_percent": "20"},
            )
        )
    )
    assert result.passed is True


async def test_a_gap_smaller_than_a_cent_is_rounding_and_not_a_finding() -> None:
    result = only(
        await FundingOwnShareIsCovered().validate(
            context(
                application={"eligible_cost_base": "100000", "own_share_amount": "19999.995"},
                programme={"own_share_percent": "20"},
            )
        )
    )
    assert result.passed is True


async def test_carrying_more_than_required_is_not_a_finding() -> None:
    result = only(
        await FundingOwnShareIsCovered().validate(
            context(
                application={"eligible_cost_base": "100000", "own_share_amount": "45000"},
                programme={"own_share_percent": "20"},
            )
        )
    )
    assert result.passed is True


@pytest.mark.parametrize(
    ("application", "programme"),
    [
        ({"eligible_cost_base": "100000"}, {"own_share_percent": "0"}),
        ({"eligible_cost_base": "100000"}, {}),
        ({"eligible_cost_base": "0"}, {"own_share_percent": "20"}),
        ({}, {"own_share_percent": "20"}),
        # Junk where a number belongs reads as absent rather than as zero,
        # because a rule that fails on an unparsable figure reports the
        # parser and not the funding.
        ({"eligible_cost_base": "n/a"}, {"own_share_percent": "20"}),
    ],
)
async def test_without_a_declared_share_or_a_base_the_rule_stays_quiet(
    application: dict[str, Any], programme: dict[str, Any]
) -> None:
    assert await FundingOwnShareIsCovered().validate(context(application=application, programme=programme)) == []


# ── Cumulation across programmes ────────────────────────────────────────


def peer(**fields: Any) -> dict[str, Any]:
    row = {"status": "approved", "approved_amount": "0", "requested_amount": "0", "aid_intensity_cap_percent": "0"}
    row.update(fields)
    return row


async def test_two_faultless_applications_can_breach_the_ceiling_together() -> None:
    """Neither one is over on its own, which is the whole point of the rule."""
    result = only(
        await FundingCumulationWithinAidIntensity().validate(
            context(
                application={"project_id": "p1", "eligible_cost_base": "1000000"},
                project_applications=[
                    peer(approved_amount="400000", aid_intensity_cap_percent="40"),
                    peer(approved_amount="100000", aid_intensity_cap_percent="80"),
                ],
            )
        )
    )
    assert result.passed is False
    assert "50" in result.message
    assert result.element_ref == "p1"


async def test_the_lowest_ceiling_any_programme_names_is_the_one_that_binds() -> None:
    """A forty percent cap does not stop caring because a second programme allows eighty."""
    result = only(
        await FundingCumulationWithinAidIntensity().validate(
            context(
                application={"project_id": "p1", "eligible_cost_base": "1000000"},
                project_applications=[
                    peer(approved_amount="300000", aid_intensity_cap_percent="40"),
                    peer(approved_amount="100000", aid_intensity_cap_percent="80"),
                ],
            )
        )
    )
    assert result.passed is True


async def test_a_withdrawn_application_carries_no_money() -> None:
    result = only(
        await FundingCumulationWithinAidIntensity().validate(
            context(
                application={"project_id": "p1", "eligible_cost_base": "1000000"},
                project_applications=[
                    peer(approved_amount="400000", aid_intensity_cap_percent="40"),
                    peer(status="withdrawn", approved_amount="500000", aid_intensity_cap_percent="40"),
                    peer(status="rejected", approved_amount="500000", aid_intensity_cap_percent="40"),
                ],
            )
        )
    )
    assert result.passed is True


async def test_an_application_still_in_review_counts_at_the_amount_it_asked_for() -> None:
    """Booking a ceiling on the assumption a pending application will fail is planning for its failure."""
    result = only(
        await FundingCumulationWithinAidIntensity().validate(
            context(
                application={"project_id": "p1", "eligible_cost_base": "1000000"},
                project_applications=[
                    peer(approved_amount="400000", aid_intensity_cap_percent="40"),
                    peer(status="in_review", requested_amount="100000", aid_intensity_cap_percent="40"),
                ],
            )
        )
    )
    assert result.passed is False


@pytest.mark.parametrize(
    ("base", "peers"),
    [
        ("1000000", []),
        ("1000000", [peer(approved_amount="900000")]),
        ("0", [peer(approved_amount="900000", aid_intensity_cap_percent="40")]),
    ],
)
async def test_without_peers_a_ceiling_or_a_base_the_rule_stays_quiet(base: str, peers: list[dict[str, Any]]) -> None:
    results = await FundingCumulationWithinAidIntensity().validate(
        context(application={"project_id": "p1", "eligible_cost_base": base}, project_applications=peers)
    )
    assert results == []


# ── The report that closes the award ────────────────────────────────────

CLOSED = {"code": "A-1", "status": "approved", "award_period_end": "2026-06-30"}
AFTERWARDS = {"today": "2026-09-01"}


async def test_a_finished_award_with_no_report_at_all_fails() -> None:
    result = only(await FundingProofOfUseIsOnTime().validate(context(application=CLOSED, clock=AFTERWARDS)))
    assert result.passed is False
    assert result.severity == Severity.WARNING
    assert "2026-06-30" in result.message


async def test_a_report_still_inside_its_due_date_passes() -> None:
    result = only(
        await FundingProofOfUseIsOnTime().validate(
            context(
                application=CLOSED,
                clock=AFTERWARDS,
                proofs_of_use=[{"id": "v1", "kind": "final", "due_on": "2026-09-30", "status": "pending"}],
            )
        )
    )
    assert result.passed is True


async def test_a_report_nobody_has_filed_and_whose_date_has_passed_fails() -> None:
    result = only(
        await FundingProofOfUseIsOnTime().validate(
            context(
                application=CLOSED,
                clock=AFTERWARDS,
                proofs_of_use=[{"id": "v1", "kind": "final", "due_on": "2026-08-31", "status": "pending"}],
            )
        )
    )
    assert result.passed is False
    assert "2026-08-31" in result.message


async def test_a_report_filed_after_its_date_fails_even_though_it_exists() -> None:
    result = only(
        await FundingProofOfUseIsOnTime().validate(
            context(
                application=CLOSED,
                clock=AFTERWARDS,
                proofs_of_use=[
                    {"id": "v1", "kind": "final", "due_on": "2026-08-31", "submitted_on": "2026-09-05"},
                ],
            )
        )
    )
    assert result.passed is False
    assert "2026-09-05" in result.message


async def test_a_report_filed_in_time_passes() -> None:
    result = only(
        await FundingProofOfUseIsOnTime().validate(
            context(
                application=CLOSED,
                clock=AFTERWARDS,
                proofs_of_use=[
                    {"id": "v1", "kind": "final", "due_on": "2026-08-31", "submitted_on": "2026-08-15"},
                ],
            )
        )
    )
    assert result.passed is True


async def test_acceptance_closes_the_question_however_late_it_arrived() -> None:
    """The authority has already decided it was in time, and it outranks us."""
    result = only(
        await FundingProofOfUseIsOnTime().validate(
            context(
                application=CLOSED,
                clock=AFTERWARDS,
                proofs_of_use=[
                    {
                        "id": "v1",
                        "kind": "final",
                        "due_on": "2026-08-31",
                        "submitted_on": "2026-09-05",
                        "status": "accepted",
                    },
                ],
            )
        )
    )
    assert result.passed is True


async def test_an_interim_report_is_not_the_one_that_closes_the_award() -> None:
    results = await FundingProofOfUseIsOnTime().validate(
        context(
            application=CLOSED,
            clock=AFTERWARDS,
            proofs_of_use=[{"id": "v1", "kind": "interim", "due_on": "2026-01-31", "status": "pending"}],
        )
    )
    # No final report exists, so the rule reports the missing one rather than
    # judging the interim in its place.
    assert only(results).passed is False


@pytest.mark.parametrize(
    ("application", "clock"),
    [
        ({"status": "draft", "award_period_end": "2026-06-30"}, AFTERWARDS),
        ({"status": "approved"}, AFTERWARDS),
        # Without a clock the rule cannot say what is late, and the server's
        # own date would make the same record pass or fail depending on which
        # machine asked.
        (CLOSED, {}),
        (CLOSED, {"today": "2026-05-01"}),
        (CLOSED, {"today": "2026-06-30"}),
    ],
)
async def test_before_the_period_ends_or_without_a_clock_the_rule_stays_quiet(
    application: dict[str, Any], clock: dict[str, Any]
) -> None:
    assert await FundingProofOfUseIsOnTime().validate(context(application=application, clock=clock)) == []


# ── Every rule, as a set ────────────────────────────────────────────────


def test_every_rule_declares_the_funding_standard_and_a_dotted_id() -> None:
    assert len(FUNDING_RULES) == 5
    for rule_class in FUNDING_RULES:
        rule = rule_class()
        assert rule.standard == "funding"
        assert rule.rule_id.startswith("funding.")
        assert rule.description
    assert len({rule_class().rule_id for rule_class in FUNDING_RULES}) == len(FUNDING_RULES)


def test_the_two_rules_that_block_are_the_two_that_cannot_be_argued_with() -> None:
    """A date has already passed; the work started when it started."""
    blocking = {rule_class().rule_id for rule_class in FUNDING_RULES if rule_class().severity == Severity.ERROR}
    assert blocking == {
        "funding.measure_starts_after_application",
        "funding.costs_fall_in_the_award_period",
    }


@pytest.mark.parametrize("locale", ["de", "es", "ru"])
async def test_a_finding_reaches_the_reader_in_their_own_language(locale: str) -> None:
    """A message that came back as its own key means the bundle has a hole."""
    english = only(
        await FundingMeasureStartsAfterApplication().validate(
            context(
                application={"code": "A-1", "measure_start_on": "2026-01-10", "submitted_on": "2026-02-01"},
                programme={"requires_application_before_start": True},
            )
        )
    )
    translated = only(
        await FundingMeasureStartsAfterApplication().validate(
            context(
                locale=locale,
                application={"code": "A-1", "measure_start_on": "2026-01-10", "submitted_on": "2026-02-01"},
                programme={"requires_application_before_start": True},
            )
        )
    )
    assert not translated.message.startswith("funding.")
    assert translated.message != english.message
    assert translated.suggestion != english.suggestion
    # The dates are data and survive translation unchanged.
    assert "2026-01-10" in translated.message
