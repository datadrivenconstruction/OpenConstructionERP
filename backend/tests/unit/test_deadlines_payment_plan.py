# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-free parts of the payment-plan reminders in the deadlines module."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.deadlines import service, sweeper


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        (None, service.DEFAULT_CLAIM_WITHIN_DAYS),
        ({}, service.DEFAULT_CLAIM_WITHIN_DAYS),
        ({"payment_plan": None}, service.DEFAULT_CLAIM_WITHIN_DAYS),
        ({"payment_plan": {"claim_within_days": 14}}, 14),
        ({"payment_plan": {"claim_within_days": "21"}}, 21),
        ({"payment_plan": {"claim_within_days": 0}}, 0),
        ({"payment_plan": {"claim_within_days": -3}}, service.DEFAULT_CLAIM_WITHIN_DAYS),
        ({"payment_plan": {"claim_within_days": "soon"}}, service.DEFAULT_CLAIM_WITHIN_DAYS),
        ({"payment_plan": {"claim_within_days": True}}, service.DEFAULT_CLAIM_WITHIN_DAYS),
    ],
)
def test_claim_within_days(terms, expected) -> None:
    assert service.claim_within_days(terms) == expected


def test_claim_due_counts_from_the_claimable_day() -> None:
    # Reached on the 1st, claimable after a 10-day lag, a 7-day window.
    assert service.plan_claim_due("2026-10-01T15:30:00+00:00", 10, {}) == date(2026, 10, 18)
    assert service.plan_claim_due("2026-10-01", None, {"payment_plan": {"claim_within_days": 3}}) == date(2026, 10, 4)
    # A negative lag is not a head start.
    assert service.plan_claim_due("2026-10-01", -5, {}) == date(2026, 10, 8)
    assert service.plan_claim_due(None, 0, {}) is None


def test_aware_normalises_both_timestamp_shapes() -> None:
    naive = datetime(2026, 10, 5, 9, 0)
    assert service._aware(naive) == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    assert service._aware("2026-10-05T09:00:00Z") == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    assert service._aware("2026-10-05T09:00:00+00:00") > service._aware(naive.replace(hour=8))
    assert service._aware(None) is None
    assert service._aware("not a time") is None


def test_payment_plan_sources_are_registered_and_reminded_ahead() -> None:
    keys = [m for m, _c, _o in service._COLLECTORS]
    assert "contracts_payment_plan_claim" in keys
    assert "contracts_payment_plan" in keys
    # Every source reminded ahead of time is a registered collector, or the
    # sweep would collect nothing for it and say nothing.
    assert set(sweeper.APPROACHING_NOTIFY) <= set(keys)
    assert sweeper.APPROACHING_NOTIFY["contracts_payment_plan"] == 7
    assert sweeper.APPROACHING_TYPE == "deadline_approaching"


def test_approaching_reminder_has_templates_and_a_catalogue_entry() -> None:
    from app.modules.notifications.service import KNOWN_EVENT_TYPES
    from app.modules.notifications.templates import icon_category_for, render

    assert render("notifications.deadline.approaching.title", {"title": "C-001 - Roof"}) == "Due soon: C-001 - Roof"
    body = render(
        "notifications.deadline.approaching.body",
        {"module": "contracts_payment_plan", "title": "Roof", "due_date": "2026-10-12"},
    )
    assert body == 'contracts_payment_plan item "Roof" is due on 2026-10-12.'
    assert icon_category_for(sweeper.APPROACHING_TYPE) == "warning"
    etypes = {e["event_type"] for e in KNOWN_EVENT_TYPES}
    assert {f"deadlines.{m}.approaching" for m in sweeper.APPROACHING_NOTIFY} <= etypes


def test_plan_title_joins_contract_and_instalment() -> None:
    class _M:
        name = "Roof"
        code = "M-2"

    assert service._plan_title("C-001", _M()) == "C-001 - Roof"
    assert service._plan_title(None, _M()) == "Roof"
