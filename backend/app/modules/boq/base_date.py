# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The day a bill's stated price base falls on.

``BOQ.base_date`` is free text (``String(40)``), because a quantity surveyor
states a price base in whatever precision the pricing actually carries: a full
day for a tendered bill, a month for a published index, a quarter or a year for
an early cost plan. All four are legitimate, the API accepts all four, and the
shipped demo packs state quarters and months - though the packs write theirs
into ``boq_metadata`` rather than into this column, so what reaches the column
is what a person or an integration put there.

Anything that dates a bill needs one day rather than a period, and the platform
now has one: a bill of quantities is taxed at its own base date, so the string
has to become a date somewhere. This module is that somewhere, so that a second
reader cannot answer the question differently.

Which day inside the period, and why that end
---------------------------------------------
The **first** day of whatever period the value names:

===============  ============
stated           resolves to
===============  ============
``2026-03-15``   2026-03-15
``2026-03``      2026-03-01
``2026-Q1``      2026-01-01
``2026``         2026-01-01
===============  ============

The property that decides it: under the first day, stating the same instant
more precisely never moves the answer. ``2026``, ``2026-01`` and ``2026-01-01``
are one day, so the full ISO date is the most precise case of a single rule
rather than an exception to it. Taking the last day instead would make those
three read as 2026-12-31, 2026-01-31 and 2026-01-01, three different tax
answers separated by nothing but how precisely somebody typed. It also needs no
month-length arithmetic, so it cannot produce a day that does not exist, and it
runs with the grain of the tax data itself, where every window opens on an
``effective_from`` that is a first-of-period date.

The cost is stated rather than hidden: where a rate change falls *inside* a
stated period, a bill labelled with that period is taxed at the rate that
opened the period, not the one that closed it. That is the right way round for
a price base, whose whole meaning is when the rates were set.

Formats that are deliberately refused
-------------------------------------
``01.02.2026`` is 1 February in Moscow and 2 January in Denver, and this
platform prices both. A value the parser cannot tell apart is reported rather
than guessed at, which is what :func:`price_base_day` returning ``None`` on a
non-empty string means to its callers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

__all__ = ["ACCEPTED_SHAPES", "latest_base_date", "price_base_day"]

#: Every shape :func:`price_base_day` reads, most precise first. Quoted at the
#: reader in the log line and in the validation rule's suggestion, so a person
#: told their base date is unreadable is told in the same breath what is
#: readable.
ACCEPTED_SHAPES = ("2026-03-15", "2026-03", "2026-Q1", "2026")

#: A full ISO day. Kept as the first branch: it is both the commonest value and
#: the one whose behaviour must not change.
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
#: A calendar quarter, ``Q`` in either case.
_QUARTER = re.compile(r"(\d{4})-[Qq]([1-4])")
#: A calendar month.
_YEAR_MONTH = re.compile(r"(\d{4})-(\d{2})")
#: A bare year.
_YEAR = re.compile(r"(\d{4})")


def price_base_day(base_date: str | None) -> date | None:
    """Read a stated price base into the single day it falls on.

    Args:
        base_date: The bill's ``base_date`` as stored, in any of
            :data:`ACCEPTED_SHAPES`, or ``None``/blank when the bill states no
            price base at all.

    Returns:
        The first day of the stated period (see the module docstring for why
        the first), or ``None`` when nothing usable was stated. ``None`` covers
        two different events that the caller must keep apart: a bill that says
        nothing, which is ordinary, and a bill that says something this cannot
        read, which is a defect in somebody's data and has to be reported. Tell
        them apart on the way in - a non-empty ``base_date`` that comes back
        ``None`` is the second.

    Raises:
        Nothing. An unreadable base date is an answer, not an exception: a bill
        must still price when its price base is mistyped.
    """
    value = (base_date or "").strip()
    if not value:
        return None

    if match := _ISO_DATE.fullmatch(value):
        year, month, day = (int(part) for part in match.groups())
    elif match := _QUARTER.fullmatch(value):
        year = int(match.group(1))
        # Q1 opens in January, Q2 in April, Q3 in July, Q4 in October.
        month = (int(match.group(2)) - 1) * 3 + 1
        day = 1
    elif match := _YEAR_MONTH.fullmatch(value):
        year, month = (int(part) for part in match.groups())
        day = 1
    elif match := _YEAR.fullmatch(value):
        year, month, day = int(match.group(1)), 1, 1
    else:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        # A shape this reads but a calendar does not have: "2026-02-30",
        # "2026-13". Refusing it here is what stops an impossible day from
        # travelling on as a string that string comparisons would happily rank.
        return None


def latest_base_date(values: Iterable[str | None]) -> str | None:
    """The freshest price base among several bills, as the bill wrote it.

    A project has more than one bill and they need not share a price base, so
    something has to pick. ``SELECT max(base_date)`` cannot: it ranks the
    strings, and these strings do not sort in the order the dates run.
    ``"2026-Q1"`` sorts above ``"2026-12-01"`` because ``Q`` is above every
    digit, while ``"2026-01"`` sorts below both, so the "freshest" bill in a
    mixed project was whichever one happened to be spelt luckiest.

    Args:
        values: Every bill's ``base_date`` in whatever shapes they carry,
            blanks and ``None`` included.

    Returns:
        The original text of the bill whose price base falls latest, so that a
        document quoting it quotes what the estimator actually wrote rather
        than a day this module inferred. When nothing readable was stated but
        something was, the largest of those strings is returned: the reader is
        no worse off than before and a stated basis does not vanish from a
        client-facing document because this module could not parse it. ``None``
        only when nothing was stated at all.
    """
    stated = [text for text in (str(value or "").strip() for value in values) if text]
    if not stated:
        return None
    readable = [(day, text) for text, day in ((text, price_base_day(text)) for text in stated) if day is not None]
    if readable:
        return max(readable, key=lambda pair: pair[0])[1]
    return max(stated)
