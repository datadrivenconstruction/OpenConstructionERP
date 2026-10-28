# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo estate must not stamp a progress claim at a time that has not come.

``seed_contracts_demo`` limits a claim to ``today`` and then lays a business
hour on top of it, so an installation seeded at 07:30 UTC wrote claims
submitted at 10:00 UTC the same morning. Nothing in the product objects to a
timestamp in the future, and the register renders it without comment, so the
only thing that ever caught it was an assertion in the PostgreSQL suite that
fires on the wall clock of the machine running it: green after ten in the
morning, red before, and read as a flake either way.

These tests do not depend on the time of day. The first pins the clamp with a
day that is in the future no matter when it runs, and the second pins the other
side of it, because a clamp that simply returned ``now`` for everything would
pass the first test while flattening the whole history of the ladder into one
instant.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.contracts.seed import _stamp


def test_a_day_that_has_not_arrived_is_pulled_back_to_now() -> None:
    """The failure this exists for, with the wall clock taken out of it."""
    before = datetime.now(UTC)
    stamped = datetime.fromisoformat(_stamp(date.today() + timedelta(days=5), 10))
    after = datetime.now(UTC)

    assert stamped <= after, "a claim was stamped in the future"
    assert stamped >= before, "the clamp reached back further than now"


def test_an_hour_that_has_not_arrived_today_is_pulled_back_to_now() -> None:
    """The original defect exactly: today's date, an hour still ahead of us.

    Written against the last hour of the day so that the assertion means
    something at every hour except the twenty-third, rather than only before
    ten in the morning, which is what made the first report look like a flake.
    """
    stamped = datetime.fromisoformat(_stamp(date.today(), 23))
    assert stamped <= datetime.now(UTC), "a claim was stamped later today"


def test_a_day_that_has_passed_keeps_its_business_hour() -> None:
    """The control, and the reason the clamp is a minimum and not an assignment.

    A ladder whose every stage reads ``now`` is not a history, and a seeder that
    produced one would satisfy the two tests above without seeding anything a
    reader would recognise.
    """
    past = date.today() - timedelta(days=30)
    stamped = datetime.fromisoformat(_stamp(past, 14))

    assert stamped == datetime(past.year, past.month, past.day, 14, 0, 0, tzinfo=UTC)


def test_the_ladder_stays_in_order() -> None:
    """Submitted, then approved, then paid, whatever the clamp does to them.

    Each stage of a claim is derived from a day at or after the one before it,
    so the ceiling has to preserve that ordering rather than only apply to each
    stamp on its own. The stages here straddle the clamp deliberately: the first
    is comfortably in the past, the last is not.
    """
    submitted_day = date.today() - timedelta(days=10)
    approved_day = submitted_day + timedelta(days=14)
    paid_day = approved_day + timedelta(days=12)

    submitted = datetime.fromisoformat(_stamp(submitted_day, 10))
    approved = datetime.fromisoformat(_stamp(approved_day, 14))
    paid = datetime.fromisoformat(_stamp(paid_day, 11))

    assert submitted <= approved <= paid
