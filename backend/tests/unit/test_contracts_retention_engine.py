# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The retention engine, held against figures worked out by hand.

Every expectation below is arithmetic a person can check on paper, on a
contract sum of 100,000 with the common US policy of 10% stepping down to 5%
at half complete. The cases that matter most are the ones the old flat rate
got wrong: crossing the threshold inside a single claim, a recompute-mode
step-down, a cap, and per-line figures that must add up to the contract
figure to the cent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.regional_packs import resolve_progress_billing
from app.modules.contracts.retention import (
    CONTRACT_RATE_SOURCE,
    allocate_cents,
    canonical_release_event,
    claim_retention,
    compute_retention,
    flat_policy,
    plan_release,
    policy_from_rule,
    step_down_release,
    work_retention,
)

SUM = Decimal("100000")
STEP_DOWN = {
    "tiers": [{"from_percent_complete": "0", "rate": "10"}, {"from_percent_complete": "50", "rate": "5"}],
    "tier_mode": "prospective",
}


def _policy(**overrides):
    return policy_from_rule({**STEP_DOWN, **overrides}, fallback_rate="0")


@pytest.mark.parametrize(
    ("completed", "held"),
    [
        ("0", "0"),
        ("40000", "4000"),
        ("50000", "5000"),
        # 50,000 at 10% plus 10,000 at 5%.
        ("60000", "5500"),
        ("100000", "7500"),
        # Past the contract sum the last tier keeps applying.
        ("110000", "8000"),
    ],
)
def test_prospective_retains_each_band_at_its_own_rate(completed: str, held: str) -> None:
    assert work_retention(Decimal(completed), SUM, _policy()) == Decimal(held)


def test_crossing_the_threshold_inside_one_claim_splits_exactly_at_it() -> None:
    before = compute_retention({"a": "40000"}, contract_sum=SUM, policy=_policy())
    after = compute_retention({"a": "60000"}, contract_sum=SUM, policy=_policy())
    # 10,000 of the claim's 20,000 is below 50% and 10,000 above.
    assert after.work_retention - before.work_retention == Decimal("1500.00")
    assert (before.rate_now, after.rate_now) == (Decimal("10"), Decimal("5"))


def test_recompute_applies_the_rate_in_force_to_all_work() -> None:
    policy = _policy(tier_mode="recompute")
    assert work_retention(Decimal("40000"), SUM, policy) == Decimal("4000")
    assert work_retention(Decimal("60000"), SUM, policy) == Decimal("3000")


def test_a_recompute_step_down_releases_the_difference_and_nothing_else_does() -> None:
    recompute = _policy(tier_mode="recompute")
    freed = step_down_release(recompute, held_before="4000", required_now="3000", rate_before="10", rate_now="5")
    assert freed == Decimal("1000.00")
    # Prospective never lowers what is held on work already done.
    assert step_down_release(_policy(), held_before="4000", required_now="3000", rate_before="10", rate_now="5") == 0
    # A lower requirement at the same rate is a correction, not a release.
    assert step_down_release(recompute, held_before="4000", required_now="3000", rate_before="10", rate_now="10") == 0


def test_a_cap_applies_last_and_cuts_work_before_stored() -> None:
    policy = policy_from_rule(
        {"tiers": [{"from_percent_complete": "0", "rate": "10"}], "cap": {"percent_of_contract_sum": "5"}},
        fallback_rate="0",
    )
    position = compute_retention({"a": "80000"}, contract_sum=SUM, policy=policy, stored_by_line={"a": "10000"})
    assert position.capped
    assert (position.work_retention, position.stored_retention) == (Decimal("5000.00"), Decimal("0.00"))
    below = compute_retention({"a": "30000"}, contract_sum=SUM, policy=policy, stored_by_line={"a": "10000"})
    assert not below.capped
    assert (below.work_retention, below.stored_retention) == (Decimal("3000.00"), Decimal("1000.00"))


def test_stored_materials_follow_the_rate_in_force_unless_the_policy_names_one() -> None:
    at_sixty = compute_retention({"a": "60000"}, contract_sum=SUM, policy=_policy(), stored_by_line={"a": "4000"})
    assert at_sixty.stored_retention == Decimal("200.00")
    own_rate = compute_retention(
        {"a": "60000"}, contract_sum=SUM, policy=_policy(stored_materials_rate="10"), stored_by_line={"a": "4000"}
    )
    assert own_rate.stored_retention == Decimal("400.00")
    # Stored materials do not count towards percent complete.
    at_forty = compute_retention({"a": "40000"}, contract_sum=SUM, policy=_policy(), stored_by_line={"a": "20000"})
    assert at_forty.rate_now == Decimal("10")


def test_line_figures_add_up_to_the_contract_figure_to_the_cent() -> None:
    completed = {"a": "33333.33", "b": "33333.33", "c": "13333.34", "credit": "-5000"}
    stored = {"b": "1234.56", "d": "999.99"}
    position = compute_retention(completed, contract_sum=SUM, policy=_policy(), stored_by_line=stored)
    assert sum(line.retention_to_date for line in position.lines.values()) == position.work_retention
    assert sum(line.retention_stored_to_date for line in position.lines.values()) == position.stored_retention
    # A credit line reduces the work but carries no retention of its own.
    assert position.completed_to_date == Decimal("75000.00")
    assert position.lines["credit"].retention_to_date == 0
    assert position.lines["d"].retention_to_date == 0
    assert position.lines["d"].retention_stored_to_date > 0


def test_largest_remainder_gives_the_odd_cent_to_the_biggest_loss_then_input_order() -> None:
    shares = allocate_cents(Decimal("100"), {"a": Decimal("1"), "b": Decimal("1"), "c": Decimal("1")})
    assert shares == {"a": Decimal("33.34"), "b": Decimal("33.33"), "c": Decimal("33.33")}
    assert allocate_cents(Decimal("0"), {"a": Decimal("0")}) == {"a": Decimal("0")}
    with pytest.raises(ValueError, match="no positive weight"):
        allocate_cents(Decimal("5"), {"credit": Decimal("-10")})


def test_the_line_rate_is_what_column_g_multiplies_by_to_give_column_i() -> None:
    position = compute_retention({"a": "60000"}, contract_sum=SUM, policy=_policy())
    assert position.lines["a"].retention_rate == Decimal("9.1667")


def test_with_no_contract_sum_the_first_tier_applies() -> None:
    assert work_retention(Decimal("1000"), Decimal("0"), _policy()) == Decimal("100")


def test_a_rule_without_tiers_is_the_contracts_flat_rate_and_says_so() -> None:
    policy = policy_from_rule({}, fallback_rate="7.5")
    assert policy == flat_policy("7.5")
    assert policy.source == CONTRACT_RATE_SOURCE
    assert work_retention(Decimal("1000"), SUM, policy) == Decimal("75.0")


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"tiers": [{"from_percent_complete": "10", "rate": "10"}]}, "start at 0"),
        (
            {"tiers": [{"from_percent_complete": "0", "rate": "10"}, {"from_percent_complete": "0", "rate": "5"}]},
            "same",
        ),
        ({"tiers": [{"from_percent_complete": "0", "rate": "110"}]}, "between 0 and 100"),
        ({"tiers": [{"from_percent_complete": "0", "rate": "ten"}]}, "not a number"),
        ({**STEP_DOWN, "tier_mode": "averaged"}, "tier_mode"),
        # The shapes that are not tiers at all. They belong in this list and
        # not in one of their own, because what the callers rely on is not
        # that the rule is refused, it is that the refusal is a ValueError:
        # all three guard with except ValueError, and one of them declines to
        # write the row on it. A mapping iterates as its keys and a string as
        # its characters, so each of these used to reach .get on something
        # that has none and raise an AttributeError straight past the guard.
        ({"tiers": "10"}, "must be a list"),
        ({"tiers": {"from_percent_complete": "0", "rate": "10"}}, "must be a list"),
        ({"tiers": ["10"]}, "must be an object"),
        ({"tiers": [10]}, "must be an object"),
        ({"tiers": [[0, 10]]}, "must be an object"),
        # And the rule itself being the wrong shape, which is a layer above the
        # five cases before it and leaked the same AttributeError for the same
        # reason after they were fixed. The value is a JSON column and a pack
        # file, so every one of these is a thing JSON can hold. None, {} and ""
        # are deliberately absent: they are falsy, they mean no rule, and they
        # go on standing in the contract's flat rate.
        ("10 percent", "must be an object"),
        ([{"from_percent_complete": "0", "rate": "10"}], "must be an object"),
        (10, "must be an object"),
        (True, "must be an object"),
    ],
)
def test_a_policy_that_cannot_be_read_is_refused_not_replaced(rule: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        policy_from_rule(rule, fallback_rate="10")


def test_the_us_pack_policy_reads_as_ten_stepping_down_to_five() -> None:
    figures = resolve_progress_billing(country_code="US")
    assert figures is not None
    policy = policy_from_rule(figures["retention_policy"], fallback_rate="0")
    assert policy.tier_mode == "prospective"
    assert work_retention(Decimal("60000"), SUM, policy) == Decimal("5500")


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("practical_completion", "substantial_completion"),
        ("handover", "substantial_completion"),
        ("taking_over", "substantial_completion"),
        ("completion", "substantial_completion"),
        ("final_account", "final_completion"),
        ("performance_certificate", "defects_period_end"),
        ("punch_list_complete", "final_completion"),
        ("defects_liability_end", "defects_period_end"),
        (" Substantial_Completion ", "substantial_completion"),
        ("rate_step_down", "rate_step_down"),
    ],
)
def test_every_release_vocabulary_lands_on_one_event(alias: str, canonical: str) -> None:
    assert canonical_release_event(alias) == canonical


def test_substantial_completion_under_the_us_pack_withholds_the_open_items() -> None:
    rule = resolve_progress_billing(country_code="US")["release_events"]
    plan = plan_release("7500", "practical_completion", rule, open_items_value="1000")
    assert plan.event == "substantial_completion"
    assert plan.withheld_for_open_items == Decimal("1500.00")
    assert (plan.amount, plan.remaining) == (Decimal("6000.00"), Decimal("1500.00"))
    assert plan.required_documents == ("certificate_substantial_completion",)
    assert plan.required_documents_when_bonded == ("consent_of_surety",)


def test_release_percentages_are_of_what_is_held_at_the_event() -> None:
    rule = {
        "events": [
            {"event": "substantial_completion", "release_percent_of_held": "50"},
            {"event": "final_completion", "release_percent_of_held": "100"},
        ]
    }
    first = plan_release("1000", "substantial_completion", rule)
    second = plan_release(first.remaining, "final_completion", rule)
    assert (first.amount, second.amount, second.remaining) == (Decimal("500.00"), Decimal("500.00"), Decimal("0.00"))


def test_a_release_without_a_percentage_needs_an_amount_and_never_exceeds_what_is_held() -> None:
    with pytest.raises(ValueError, match="give the amount"):
        plan_release("1000", "rate_step_down", {"events": [{"event": "rate_step_down"}]})
    plan = plan_release("1000", "rate_step_down", None, amount="1200")
    assert (plan.amount, plan.remaining, plan.percent_of_held) == (Decimal("1000.00"), Decimal("0.00"), None)


# ── One claim's line 5 and column I ──────────────────────────────────────


def test_a_claim_crossing_the_threshold_holds_by_band_and_its_lines_add_up() -> None:
    completed = {"A": Decimal("36000"), "B": Decimal("24000")}
    position = compute_retention(completed, contract_sum=SUM, policy=_policy())
    figures = claim_retention(position, completed_by_line=completed, accrued_before="4000", released_to_date="0")
    # 50,000 at 10% and 10,000 at 5%; 4,000 was accrued before.
    assert (figures.accrual, figures.held, figures.accrued_to_date) == (
        Decimal("1500"),
        Decimal("5500"),
        Decimal("5500"),
    )
    assert figures.completed_stored_to_date == Decimal("60000")
    assert {key: line.retention_to_date for key, line in figures.lines.items()} == {
        "A": Decimal("3300"),
        "B": Decimal("2200"),
    }
    assert figures.lines["A"].retention_rate == Decimal("9.1667")


def test_a_release_comes_off_work_first_and_stored_materials_last() -> None:
    completed, stored = {"A": Decimal("30000")}, {"A": Decimal("10000")}
    position = compute_retention(completed, contract_sum=SUM, policy=flat_policy("10"), stored_by_line=stored)
    figures = claim_retention(
        position, completed_by_line=completed, stored_by_line=stored, accrued_before="4000", released_to_date="3500"
    )
    assert (figures.accrual, figures.held) == (Decimal("0"), Decimal("500"))
    assert (figures.held_on_work, figures.held_on_stored) == (Decimal("0"), Decimal("500"))
    assert (figures.lines["A"].retention_to_date, figures.lines["A"].retention_stored_to_date) == (
        Decimal("0"),
        Decimal("500"),
    )


def test_a_policy_that_now_asks_for_less_never_accrues_a_negative_period() -> None:
    completed = {"A": Decimal("60000")}
    position = compute_retention(completed, contract_sum=SUM, policy=_policy())
    figures = claim_retention(position, completed_by_line=completed, accrued_before="6000", released_to_date="0")
    # Prospective: 5,500 is required, the 6,000 already held stays until released.
    assert (figures.accrual, figures.held) == (Decimal("0"), Decimal("6000"))


def test_column_i_adds_up_to_line_5_to_the_cent() -> None:
    completed = {"A": Decimal("10000"), "B": Decimal("10000"), "C": Decimal("10000")}
    position = compute_retention(completed, contract_sum=SUM, policy=flat_policy("10"))
    figures = claim_retention(position, completed_by_line=completed, accrued_before="3000", released_to_date="2900")
    shares = [line.retention_to_date for line in figures.lines.values()]
    assert sorted(shares) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(shares) == figures.held == Decimal("100")


def test_a_policy_that_cannot_be_read_is_refused_by_the_call_that_stores_it() -> None:
    # Otherwise it is every payment application on that contract that fails.
    import uuid

    from pydantic import ValidationError

    from app.modules.contracts.schemas import RetentionScheduleCreate

    with pytest.raises(ValidationError, match="cannot be applied"):
        RetentionScheduleCreate(
            contract_id=uuid.uuid4(),
            accrual_rule={"tiers": [{"from_percent_complete": "0", "rate": "ten"}]},
        )
    stored = RetentionScheduleCreate(contract_id=uuid.uuid4(), accrual_rule=STEP_DOWN)
    assert stored.accrual_rule == STEP_DOWN
