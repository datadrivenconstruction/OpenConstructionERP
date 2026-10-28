# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A progress claim's period strings read as dates, and claims order by them.

``app.modules.contracts.periods`` decides what a payment application counts as
previously certified: the claims before this one in period order. A parser that
guesses, or an order that falls back to "every other claim", moves money
between applications without an error anywhere. So the parser is held to the
exact population it may accept and to the values it must refuse, and the order
is held to the "strictly before" reading the founder settled on.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.modules.contracts.periods import (
    BillingPeriod,
    claim_dates_for_write,
    claim_dates_to_backfill,
    claim_order_key,
    claims_before,
    parse_iso_day,
    period_contains,
    resolve_billing_period,
)


@pytest.mark.parametrize(
    ("raw", "bound", "expected"),
    [
        ("2026-03-31", "start", date(2026, 3, 31)),
        ("  2026-03-31  ", "end", date(2026, 3, 31)),
        (date(2026, 3, 1), "start", date(2026, 3, 1)),
        (datetime(2026, 3, 1, 23, 30), "end", date(2026, 3, 1)),
        # A bare month covers the whole month, whichever end it sits at.
        ("2026-02", "start", date(2026, 2, 1)),
        ("2026-02", "end", date(2026, 2, 28)),
        ("2028-02", "end", date(2028, 2, 29)),
        # A timestamp keeps the day as written, it is not moved to UTC first.
        ("2026-03-31T23:30:00Z", "start", date(2026, 3, 31)),
        ("2026-03-31T23:30:00-07:00", "start", date(2026, 3, 31)),
        ("2026-03-31 08:00:00", "start", date(2026, 3, 31)),
    ],
)
def test_a_readable_value_gives_its_day(raw: object, bound: str, expected: date) -> None:
    assert parse_iso_day(raw, bound=bound) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "garbage",
        # Shaped like a day and not one.
        "2026-02-30",
        "2026-13",
        "2026-00",
        # Day-month against month-day is a coin toss, so neither is taken.
        "03/04/2026",
        "31/03/2026",
        "2026/03/31",
        "2026-03-31Tnonsense",
    ],
)
def test_an_unreadable_value_is_unknown_rather_than_guessed(raw: object) -> None:
    assert parse_iso_day(raw) is None
    assert parse_iso_day(raw, bound="end") is None


def test_a_write_carries_every_date_whose_string_it_writes_and_no_other() -> None:
    fields = {"period_start": "2026-03-01", "period_end": "not a date", "notes": "x"}
    assert claim_dates_for_write(fields) == {"period_from": date(2026, 3, 1), "period_to": None}
    # Clearing a string clears its date rather than leaving the old one behind.
    assert claim_dates_for_write({"claim_date": ""}) == {"application_date": None}
    assert claim_dates_for_write({}) == {}


def test_a_backfill_fills_only_a_missing_date_it_can_read() -> None:
    row = {
        "period_start": "2026-03-01",
        "period_end": "2026-03",
        "claim_date": "31/03/2026",
        "period_from": None,
        "period_to": None,
        "application_date": None,
    }
    assert claim_dates_to_backfill(row) == {"period_from": date(2026, 3, 1), "period_to": date(2026, 3, 31)}

    # A date already on file is kept even when the string beside it disagrees.
    row_set = dict(row, period_from=date(2026, 2, 1))
    assert "period_from" not in claim_dates_to_backfill(row_set)


def _claim(number: str, period_to: date | None, created: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=number, claim_number=number, period_to=period_to, created_at=created)


def test_claims_order_by_period_end_then_creation_then_number() -> None:
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 6, 1, tzinfo=UTC)
    claims = [
        _claim("PC-3", date(2026, 4, 30), early),
        _claim("PC-2b", date(2026, 3, 31), late),
        _claim("PC-2a", date(2026, 3, 31), early),
        _claim("PC-1", date(2026, 2, 28), late),
    ]
    ordered = sorted(claims, key=claim_order_key)
    assert [c.claim_number for c in ordered] == ["PC-1", "PC-2a", "PC-2b", "PC-3"]


def test_an_undated_claim_is_placed_on_the_day_it_was_raised() -> None:
    # It used to sort after every dated claim, so the claim that followed it
    # read nothing as previously certified and billed the job twice.
    claims = [
        _claim("PC-3", date(2026, 4, 30), datetime(2026, 5, 1, tzinfo=UTC)),
        _claim("PC-2", None, datetime(2026, 3, 20, tzinfo=UTC)),
        _claim("PC-1", date(2026, 2, 28), datetime(2026, 3, 1, tzinfo=UTC)),
    ]
    assert [c.claim_number for c in sorted(claims, key=claim_order_key)] == ["PC-1", "PC-2", "PC-3"]


def test_rows_with_neither_a_period_nor_a_creation_time_still_order_by_number() -> None:
    # Legacy rows: the order has to be total and stable, whatever is missing.
    claims = [_claim("PC-2", None, None), _claim("PC-1", None, None)]
    assert [c.claim_number for c in sorted(claims, key=claim_order_key)] == ["PC-1", "PC-2"]


def test_prior_means_strictly_before_in_period_order() -> None:
    claims = [_claim(f"PC-{n}", date(2026, n, 28)) for n in (1, 2, 3)]
    assert [c.id for c in claims_before(claims, "PC-3")] == ["PC-1", "PC-2"]
    assert claims_before(claims, "PC-1") == []
    # A claim that is not stored yet sees every stored claim as prior.
    assert [c.id for c in claims_before(claims, "new")] == ["PC-1", "PC-2", "PC-3"]


def test_a_period_rejects_ends_in_the_wrong_order() -> None:
    with pytest.raises(ValueError, match="after it ends"):
        BillingPeriod(date(2026, 3, 31), date(2026, 3, 1))


def test_a_day_falls_inside_a_period_including_both_ends() -> None:
    march = BillingPeriod(date(2026, 3, 1), date(2026, 3, 31))
    assert period_contains(march, date(2026, 3, 1))
    assert period_contains(march, date(2026, 3, 31))
    assert not period_contains(march, date(2026, 4, 1))
    assert not period_contains(march, None)


@pytest.mark.parametrize(
    ("as_of", "cycle", "frm", "to"),
    [
        (date(2026, 2, 14), None, date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 2, 14), {"period_end": "month_end"}, date(2026, 2, 1), date(2026, 2, 28)),
        # A cycle closing on the 25th: the 25th itself closes this month.
        (date(2026, 3, 25), {"period_end": "day:25"}, date(2026, 2, 26), date(2026, 3, 25)),
        (date(2026, 3, 26), {"period_end": "day:25"}, date(2026, 3, 26), date(2026, 4, 25)),
        # Across the year boundary in both directions.
        (date(2026, 12, 30), {"period_end": "day:25"}, date(2026, 12, 26), date(2027, 1, 25)),
        (date(2027, 1, 3), {"period_end": "day:25"}, date(2026, 12, 26), date(2027, 1, 25)),
        # A day that does not exist in every month is read as the month end.
        (date(2026, 2, 14), {"period_end": "day:31"}, date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 2, 14), {"period_end": "day:x"}, date(2026, 2, 1), date(2026, 2, 28)),
    ],
)
def test_the_billing_period_containing_a_day(as_of: date, cycle: dict | None, frm: date, to: date) -> None:
    period = resolve_billing_period(as_of, cycle)
    assert (period.frm, period.to) == (frm, to)
    assert period_contains(period, as_of)
