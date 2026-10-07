"""Retention accrual and release conserve the currency's smallest unit."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.modules.contracts.retention import (
    allocate_cents,
    claim_retention,
    compute_retention,
    flat_policy,
    plan_release,
    step_down_release,
)


@pytest.mark.parametrize(
    ("currency", "gross", "expected"),
    [
        ("JPY", "123", "6"),
        ("EUR", "12.345", ".62"),
        ("KWD", "12.345", ".617"),
        (None, "12.345", ".62"),
    ],
)
def test_accrual_uses_currency_precision(currency, gross, expected):
    position = compute_retention({"a": gross}, contract_sum=1000, policy=flat_policy(5), currency=currency)
    assert position.currency == currency
    assert position.work_retention == D(expected)
    assert position.lines["a"].retention_to_date == D(expected)


@pytest.mark.parametrize(("currency", "unit"), [("JPY", "1"), ("EUR", ".01"), ("KWD", ".001")])
def test_allocation_ties_and_negative_credit_conserve_smallest_unit(currency, unit):
    quantum = D(unit)
    shares = allocate_cents(quantum * 2, {"a": D(1), "b": D(1), "c": D(1), "credit": D(-1)}, currency=currency)
    assert shares == {"a": quantum, "b": quantum, "c": 0, "credit": 0}
    assert sum(shares.values()) == 2 * quantum


@pytest.mark.parametrize(
    ("currency", "cap", "work", "stored"),
    [
        ("JPY", "2", "1", "1"),
        ("EUR", "1.73", "1.23", ".50"),
        ("KWD", "1.728", "1.234", ".494"),
    ],
)
def test_cap_and_stored_allocations(currency, cap, work, stored):
    policy = replace(flat_policy(10), cap_percent_of_contract_sum=D("1.4"))
    position = compute_retention(
        {"a": "12.34"}, stored_by_line={"b": "20"}, contract_sum="123.45", policy=policy, currency=currency
    )
    assert position.capped
    assert (position.work_retention, position.stored_retention, position.total) == (D(work), D(stored), D(cap))
    assert sum(v.retention_to_date + v.retention_stored_to_date for v in position.lines.values()) == D(cap)


@pytest.mark.parametrize(
    ("currency", "half", "remaining"),
    [
        ("JPY", "6", "6"),
        ("EUR", "6.17", "6.18"),
        ("KWD", "6.173", "6.172"),
    ],
)
def test_partial_and_full_release(currency, half, remaining):
    rule = {"events": [{"event": "custom", "release_percent_of_held": 50}]}
    plan = plan_release("12.345", "custom", rule, currency=currency)
    assert (plan.amount, plan.remaining) == (D(half), D(remaining))
    final = plan_release(plan.remaining, "custom", amount=999, currency=currency)
    assert final.amount == plan.remaining and final.remaining == 0


@pytest.mark.parametrize(("currency", "expected"), [("JPY", "1"), ("EUR", "1.23"), ("KWD", "1.234")])
def test_step_down_and_open_items(currency, expected):
    policy = replace(flat_policy(5), tier_mode="recompute")
    assert step_down_release(
        policy, held_before="2.468", required_now="1.234", rate_before=10, rate_now=5, currency=currency
    ) == D(expected)
    rule = {"events": [{"event": "custom", "release_percent_of_held": 100}]}
    plan = plan_release(10, "custom", rule, open_items_value="1.234", currency=currency)
    assert plan.withheld_for_open_items == D(expected)
    assert plan.amount + plan.remaining == D(10)


@pytest.mark.parametrize(("currency", "unit"), [("JPY", "1"), ("EUR", ".01"), ("KWD", ".001")])
def test_prior_claim_and_release_use_position_currency_and_release_stored_last(currency, unit):
    q = D(unit)
    position = compute_retention(
        {"a": 100 * q}, stored_by_line={"b": 100 * q}, contract_sum=1000 * q, policy=flat_policy(10), currency=currency
    )
    figures = claim_retention(
        position,
        completed_by_line={"a": 100 * q},
        stored_by_line={"b": 100 * q},
        accrued_before=15 * q,
        released_to_date=12 * q,
    )
    assert figures.accrual == 5 * q
    assert figures.held == figures.held_on_stored == 8 * q
    assert figures.held_on_work == 0
    assert sum(v.retention_to_date + v.retention_stored_to_date for v in figures.lines.values()) == figures.held


@pytest.mark.parametrize(("currency", "unit"), [("JPY", "1"), ("EUR", ".01"), ("KWD", ".001")])
def test_legacy_fractional_accrual_cannot_create_room_above_required(currency, unit):
    q = D(unit)
    position = compute_retention({"a": 1000 * q}, contract_sum=1000 * q, policy=flat_policy(10), currency=currency)
    raw_before = D("98.4") * q
    figures = claim_retention(
        position, completed_by_line={"a": 1000 * q}, accrued_before=raw_before, released_to_date=0
    )
    assert figures.accrual == q
    assert raw_before + figures.accrual <= position.total
    assert figures.accrued_to_date == figures.held == 99 * q
    assert figures.lines["a"].retention_to_date == figures.held
    # Less than one whole minor unit remains: do not fill it by overcharging.
    near_cap = claim_retention(
        position, completed_by_line={"a": 1000 * q}, accrued_before=D("99.4") * q, released_to_date=0
    )
    assert near_cap.accrual == 0


@pytest.mark.parametrize(("currency", "unit"), [("JPY", "1"), ("EUR", ".01"), ("KWD", ".001")])
def test_legacy_release_is_subtracted_before_display_rounding(currency, unit):
    q = D(unit)
    position = compute_retention({"a": 1000 * q}, contract_sum=1000 * q, policy=flat_policy(10), currency=currency)
    figures = claim_retention(
        position, completed_by_line={"a": 1000 * q}, accrued_before=D("100.4") * q, released_to_date=D(".6") * q
    )
    assert figures.accrual == 0
    assert figures.held == 100 * q  # raw 99.8, not rounded-before 100 minus rounded-release 1
    assert figures.lines["a"].retention_to_date == figures.held
