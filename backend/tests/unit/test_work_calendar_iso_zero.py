# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the ISO-zero repair will and will not touch.

The whole safety of the repair is in one decision - repair this row, or leave
it - and that decision is a pure function, so it is tested here without a
database. The database half is in ``tests/pg/test_work_calendar_iso_zero.py``.

The case that matters most is the one that must NOT be touched: a four-day
Monday-to-Thursday week is unusual and entirely legal on this axis, and a repair
that cannot tell it from a week written on the wrong axis would be rewriting
somebody's deliberate configuration. Unusual is not impossible, and only the
impossible one is repaired.
"""

from __future__ import annotations

import pytest

from app.modules.i18n_foundation.seed import load_work_calendar_seed_rows
from app.modules.i18n_foundation.work_calendar_iso_zero import repaired_week


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        # The shipped Saudi defect, and the only row in the file's whole history
        # that ever carried a 0.
        ([0, 1, 2, 3, 4], [7, 1, 2, 3, 4]),
        # Order is preserved rather than sorted, so a repaired row reads the way
        # the seed file writes it.
        ([1, 2, 3, 4, 0], [1, 2, 3, 4, 7]),
        # A lone impossible day still names Sunday.
        ([0], [7]),
        # Both spellings of Sunday present: the arriving 7 must not double the
        # one already there, or the week grows a day it never had.
        ([0, 7, 1], [7, 1]),
        ([0, 1, 2, 3, 4, 5, 6], [7, 1, 2, 3, 4, 5, 6]),
    ],
)
def test_a_week_carrying_the_impossible_weekday_is_corrected(stored: list[int], expected: list[int]) -> None:
    assert repaired_week(stored) == expected


@pytest.mark.parametrize(
    ("stored", "why"),
    [
        ([1, 2, 3, 4], "a four-day Monday-to-Thursday week is unusual but legal"),
        ([1, 2, 3, 4, 5], "the ordinary Monday-to-Friday week"),
        ([7, 1, 2, 3, 4], "the Gulf week, already correct"),
        ([6, 7], "a weekend-only week, legal on this axis"),
        ([7], "Sunday alone"),
        ([1, 2, 3, 4, 5, 6, 7], "every day of the week"),
    ],
)
def test_a_week_without_the_impossible_weekday_is_left_alone(stored: list[int], why: str) -> None:
    """The negative half of the guard, which is the half that protects a customer."""
    assert repaired_week(stored) is None, f"{why}, so nothing here may be rewritten"


def test_the_repair_is_idempotent_on_its_own_output() -> None:
    """A second boot must find nothing, because the predicate is the data."""
    once = repaired_week([0, 1, 2, 3, 4])
    assert once is not None
    assert repaired_week(once) is None


@pytest.mark.parametrize(
    ("stored", "why"),
    [
        (None, "a null column"),
        ("0,1,2", "a string"),
        ({"0": 1}, "a dict"),
        ([0, "1"], "a list carrying a string"),
        ([False, 1, 2], "a JSON false, which equals 0 in Python and is not a weekday"),
        ([True, 0], "a JSON true beside a real defect"),
    ],
)
def test_a_row_this_repair_does_not_understand_is_left_alone(stored: object, why: str) -> None:
    """A shape problem is a different defect, and guessing at it is worse than leaving it.

    ``False == 0`` in Python, so without the bool guard a JSON ``false`` here
    would be silently promoted to Sunday - inventing a working day out of a
    value that never meant one.
    """
    assert repaired_week(stored) is None, f"{why} is not something this repair can reason about"


def test_nothing_in_the_shipped_seed_file_needs_this_repair() -> None:
    """The file is clean today, so a fresh install never meets this repair.

    If this fails, a week written on the wrong axis has just been added to the
    seed file and the repair is about to paper over it on every boot instead of
    it being fixed at source.
    """
    offenders = [
        (row["country_code"], row["work_days"])
        for row in load_work_calendar_seed_rows()
        if repaired_week(row["work_days"]) is not None
    ]
    assert offenders == [], f"work_calendars.json ships a week carrying the impossible weekday: {offenders}"
