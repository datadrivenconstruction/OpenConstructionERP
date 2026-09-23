# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Schedule-of-Values tracker must report the retention the claims certified.

``compute_sov_status`` works out retention for itself, ``billed * the
contract's flat retention_percent``, and every claim line it walks is already
carrying ``retention_to_date``, the figure that was actually certified and
printed on the payment application. The two agree only while the contract
retains at one flat rate for the whole job. The moment a contract carries a
ladder, which a signed contract now does by default in a country whose pack
declares one, the tracker and the certificate disagree about the same money,
and the tracker is the one that is wrong.

The payment application already reads it this way: ``aia.py`` prefers the claim
line's own ``retention_to_date`` and computes only when there is none. So the
tracker is not gaining a convention here, it is catching up with one the
document already had, and the two screens that disagree today already had a
right answer between them.

These tests are unit tests because ``compute_sov_status`` is pure. Each claim
line arrives paired with the claim it belongs to, so the function can read both
the status and the billing order from the claim itself rather than from
attributes somebody tagged onto the line on the way in.

Before the fix the first three of these failed, reporting 6,000 where the
claims had certified 5,500, and the last three passed. The last three are the
ones that keep the fix honest: unknown is not zero, a missing column is not a
crash, and a tie in billing order answers the same way whichever row the
database returned first.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

# A line worth 100,000, retained on the United States ladder: 10 per cent up to
# half complete, 5 per cent after it. At 60 per cent complete that is 5,000 on
# the first 50,000 and 500 on the next 10,000.
LADDER_RETENTION_AT_SIXTY = Decimal("5500")
# What the contract's flat rate gives on the same work, and what the tracker
# reports today.
FLAT_RETENTION_AT_SIXTY = Decimal("6000")
# What adding up the claims' to-date figures would give. Naming it is the point:
# a to-date figure is cumulative, so summing counts the first 40,000 twice.
SUMMED_RETENTION_AT_SIXTY = Decimal("9500")


def _contract_line(value: Decimal) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), quantity=Decimal("1"), unit_rate=value)


def _claim(
    number: str,
    *,
    period_to: date,
    status: str = "certified",
    created_at: datetime = datetime(2026, 1, 1, 12, 0),
) -> SimpleNamespace:
    """A parent claim, carrying what ``claim_order_key`` sorts a contract by."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        period_to=period_to,
        created_at=created_at,
        claim_number=number,
    )


def _claim_line(
    line: SimpleNamespace,
    claim: SimpleNamespace,
    *,
    period: Decimal,
    cumulative: Decimal,
    retention_to_date: Decimal | None,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """One claim line paired with its claim, as the repository hands them over."""
    row = SimpleNamespace(
        contract_line_id=line.id,
        period_completed_value=period,
        cumulative_completed_value=cumulative,
        retention_to_date=retention_to_date,
    )
    return (row, claim)


def _two_claims_to_sixty(line: SimpleNamespace) -> tuple[tuple, tuple]:
    """Forty per cent certified in April, sixty by the end of May."""
    first = _claim_line(
        line,
        _claim("PC-0001", period_to=date(2026, 4, 30)),
        period=Decimal("40000"),
        cumulative=Decimal("40000"),
        retention_to_date=Decimal("4000"),
    )
    second = _claim_line(
        line,
        _claim("PC-0002", period_to=date(2026, 5, 31)),
        period=Decimal("20000"),
        cumulative=Decimal("60000"),
        retention_to_date=LADDER_RETENTION_AT_SIXTY,
    )
    return first, second


def test_the_tracker_reports_the_retention_the_claims_certified() -> None:
    """Two claims on a laddered contract: the tracker must agree with them.

    The assertion refuses both wrong answers at once. 6,000 is the flat rate
    applied to everything billed, which is what the tracker computes today.
    9,500 is what adding the two to-date figures together would give, which is
    the mistake waiting on the other side of the fix, because a to-date figure
    already contains the one before it.
    """
    from app.modules.contracts.service import compute_sov_status

    line = _contract_line(Decimal("100000"))
    first, second = _two_claims_to_sixty(line)

    result = compute_sov_status([line], [first, second], retention_percent=Decimal("10"))

    row = result["by_line"][str(line.id)]
    assert row["billed"] == Decimal("60000")
    assert row["retained"] == LADDER_RETENTION_AT_SIXTY
    assert row["retained"] != FLAT_RETENTION_AT_SIXTY
    assert row["retained"] != SUMMED_RETENTION_AT_SIXTY
    assert result["totals"]["retained"] == LADDER_RETENTION_AT_SIXTY


def test_the_latest_claim_is_the_one_in_billing_order() -> None:
    """The figure comes from the last claim, not the last row the query returned.

    The claim lines arrive from a single JOIN with no ORDER BY, so the order
    they are walked in is whatever the database chose. Handing them over
    backwards must not change the answer.
    """
    from app.modules.contracts.service import compute_sov_status

    line = _contract_line(Decimal("100000"))
    first, second = _two_claims_to_sixty(line)

    forwards = compute_sov_status([line], [first, second], retention_percent=Decimal("10"))
    backwards = compute_sov_status([line], [second, first], retention_percent=Decimal("10"))

    assert forwards["by_line"][str(line.id)]["retained"] == LADDER_RETENTION_AT_SIXTY
    assert backwards["by_line"][str(line.id)] == forwards["by_line"][str(line.id)]


def test_a_rejected_claim_certifies_no_retention() -> None:
    """A rejected claim is not the latest anything, however late it is.

    It is left out of every other figure in this tracker for the same reason,
    and a later rejected claim carrying a stale to-date figure would otherwise
    overwrite the certified one.
    """
    from app.modules.contracts.service import compute_sov_status

    line = _contract_line(Decimal("100000"))
    certified = _claim_line(
        line,
        _claim("PC-0002", period_to=date(2026, 5, 31)),
        period=Decimal("60000"),
        cumulative=Decimal("60000"),
        retention_to_date=LADDER_RETENTION_AT_SIXTY,
    )
    rejected = _claim_line(
        line,
        _claim("PC-0003", period_to=date(2026, 6, 30), status="rejected"),
        period=Decimal("20000"),
        cumulative=Decimal("80000"),
        retention_to_date=Decimal("6500"),
    )

    result = compute_sov_status([line], [certified, rejected], retention_percent=Decimal("10"))

    assert result["by_line"][str(line.id)]["retained"] == LADDER_RETENTION_AT_SIXTY


def test_two_claims_that_tie_in_billing_order_still_answer_the_same_way() -> None:
    """A tie must be broken by something stable, not by the row order.

    ``claim_order_key`` is total over a contract's claims only as far as the
    data lets it be: it falls back to the claim number, and the column has no
    unique constraint and defaults to an empty string. Two claims closing on
    the same day, created in the same transaction and both unnumbered, tie on
    all three parts of the key. The generator never produces that pair, so this
    is about the answer being stable rather than about which claim wins: a
    figure that flips between two numbers depending on what the database
    returned first is the one thing worse than a figure that is wrong.

    The tiebreak is the claim id, which is arbitrary and stable, and stable is
    the property being pinned here rather than the choice.
    """
    from app.modules.contracts.service import compute_sov_status

    line = _contract_line(Decimal("100000"))
    one = _claim_line(
        line,
        _claim("", period_to=date(2026, 5, 31)),
        period=Decimal("30000"),
        cumulative=Decimal("30000"),
        retention_to_date=Decimal("3000"),
    )
    other = _claim_line(
        line,
        _claim("", period_to=date(2026, 5, 31)),
        period=Decimal("30000"),
        cumulative=Decimal("60000"),
        retention_to_date=LADDER_RETENTION_AT_SIXTY,
    )

    forwards = compute_sov_status([line], [one, other], retention_percent=Decimal("10"))
    backwards = compute_sov_status([line], [other, one], retention_percent=Decimal("10"))

    assert backwards["by_line"][str(line.id)] == forwards["by_line"][str(line.id)]


def test_a_claim_with_no_retention_recorded_is_not_read_as_having_none() -> None:
    """No figure on the line means unknown, and unknown is not zero.

    Claims written before the per-line retention columns existed have nothing
    in them, and so does a claim line saved by a route that does not fill them.
    Reading that absence as zero retention would report a laddered contract as
    retaining nothing at all, which is a worse answer than the flat rate it
    falls back to here.
    """
    from app.modules.contracts.service import compute_sov_status

    line = _contract_line(Decimal("100000"))
    unrecorded = _claim_line(
        line,
        _claim("PC-0001", period_to=date(2026, 5, 31)),
        period=Decimal("60000"),
        cumulative=Decimal("60000"),
        retention_to_date=None,
    )

    result = compute_sov_status([line], [unrecorded], retention_percent=Decimal("10"))

    assert result["by_line"][str(line.id)]["retained"] == FLAT_RETENTION_AT_SIXTY


def test_a_claim_line_from_an_older_caller_still_gets_a_figure() -> None:
    """A line with no retention column at all falls back, it does not raise.

    The tracker is called with whatever rows the tree holds, and not every one
    of them has been through the claim builder that fills these columns.
    """
    from app.modules.contracts.service import compute_sov_status

    line = _contract_line(Decimal("100000"))
    bare = SimpleNamespace(
        contract_line_id=line.id,
        period_completed_value=Decimal("60000"),
    )

    result = compute_sov_status(
        [line],
        [(bare, _claim("PC-0001", period_to=date(2026, 5, 31)))],
        retention_percent=Decimal("10"),
    )

    assert result["by_line"][str(line.id)]["retained"] == FLAT_RETENTION_AT_SIXTY
