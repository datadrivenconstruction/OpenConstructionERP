# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill is taxed at its own base date, and a quarter is a base date.

The defect
----------
``BOQ.base_date`` is free text and a price base is legitimately stated as a
day, a month, a quarter or a year. The tax lookup accepted only ``YYYY-MM-DD``
and dropped everything else, and a dropped date is not an error: the resolver
falls back to ``date.today()``. Every bill labelled ``2026-Q1`` or ``2026-01``,
which the API accepts and which is how the shipped demo packs state a price
base in their metadata, was therefore taxed at today's rate while its label
said the rates were of another period. Russia is where that is money rather
than pedantry - the shipped seed carries 20 percent to 2025-12-31 and 22 from
2026-01-01 - so a Russian bill priced to 2025 was charged 22.

Which day a period means, and why the first
-------------------------------------------
``app.modules.boq.base_date.price_base_day`` reads a stated period as its
FIRST day. The property that decides it is asserted below: stating the same
instant more precisely never moves the answer, so ``2026``, ``2026-01`` and
``2026-01-01`` are one day and the full ISO date is the most precise case of
one rule rather than an exception to it. Under the last day those three would
be 2026-12-31, 2026-01-31 and 2026-01-01, three tax answers separated by
nothing but typing.

Why a test that only asserts Russia would not have pinned that
--------------------------------------------------------------
Russia's rate changes on 2026-01-01 and Israel's on 2025-01-01, both of them
year, quarter and month boundaries. Every shipped ``base_date`` therefore lands
in the same tax window whichever end of its period is taken, so a suite built
only from shipped values passes under both rules and the next reader may swap
the end for free. ``test_a_window_opening_inside_a_stated_period_is_not_reached``
is the one that fails if the end moves: it puts a rate change in the middle of
a quarter, where the two ends disagree.

Reported rather than guessed
----------------------------
``01.02.2026`` is 1 February in Moscow and 2 January in Denver and this
platform prices both, so it is refused rather than read. A refused value is not
silent: the pricing path logs it against the bill and
``boq_quality.base_date_readable`` puts it on the validation report, which is
the surface the person who typed it actually looks at.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext
from app.core.validation.messages import is_key_present
from app.core.validation.rules import BOQBaseDateReadable
from app.modules.boq.base_date import ACCEPTED_SHAPES, latest_base_date, price_base_day
from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping


def bill(**fields: Any) -> ValidationContext:
    """A context shaped like the one the payload builder hands the engine."""
    return ValidationContext(data={"positions": [], "boq": fields, "markups": []}, metadata={"locale": "en"})


# ── The shapes, and the day each one means ──────────────────────────────────


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ("2026-03-15", date(2026, 3, 15)),
        ("2026-03", date(2026, 3, 1)),
        ("2026-Q1", date(2026, 1, 1)),
        ("2026-Q2", date(2026, 4, 1)),
        ("2026-Q3", date(2026, 7, 1)),
        ("2026-Q4", date(2026, 10, 1)),
        ("2026", date(2026, 1, 1)),
        ("2026-q1", date(2026, 1, 1)),
        ("  2026-Q2  ", date(2026, 4, 1)),
        ("2024-02-29", date(2024, 2, 29)),
    ],
)
def test_each_accepted_shape_resolves_to_the_first_day_of_the_period_it_names(stated: str, expected: date) -> None:
    """The documented mapping, asserted day by day rather than through a rate.

    A tax assertion would pass on any day inside the right window and so would
    not pin which day was chosen. This does.
    """
    assert price_base_day(stated) == expected


def test_stating_the_same_instant_more_precisely_does_not_move_the_day() -> None:
    """The property the first-day rule was chosen for.

    If this fails, the parser has been moved to the end of the period and every
    bill that stated its price base loosely is now taxed later than it says.
    """
    assert price_base_day("2026") == price_base_day("2026-01") == price_base_day("2026-01-01") == date(2026, 1, 1)


def test_a_full_iso_date_still_resolves_to_itself() -> None:
    """The path that already worked, kept working. Four dates across a year."""
    for iso in ("2019-01-01", "2025-12-31", "2026-01-01", "2026-09-08"):
        assert price_base_day(iso) == date.fromisoformat(iso)


@pytest.mark.parametrize(
    ("stated", "why"),
    [
        ("01.02.2026", "1 February in Moscow and 2 January in Denver; guessing would be worse than reporting"),
        ("2026-Q5", "there is no fifth quarter"),
        ("2026-13", "there is no thirteenth month"),
        ("2026-02-30", "February has no thirtieth, and a string comparison would have ranked it happily"),
        ("2026-1", "a month is stated in two digits, so this is not one of the shapes"),
        ("Q1 2026", "the same quarter written the other way round is still not a shape this reads"),
        ("mid 2026", "prose"),
        ("not a date", "prose"),
    ],
)
def test_a_value_nothing_can_read_is_refused_rather_than_guessed_at(stated: str, why: str) -> None:
    assert price_base_day(stated) is None, why


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_bill_that_states_no_price_base_is_not_a_defect(blank: str | None) -> None:
    """``None`` for a blank and ``None`` for a mistyped value are the same
    return and different events. The caller separates them on the way in, which
    is why ``price_base_day`` does not need a third answer."""
    assert price_base_day(blank) is None


# ── The end of the period, pinned where the two ends disagree ───────────────


_MID_QUARTER_CHANGE = [
    {
        "country_code": "XX",
        "subdivision_code": None,
        "tax_code": "VAT",
        "tax_name": "Test VAT",
        "rate_pct": "10.0",
        "combination": "national",
        "is_default": True,
        "effective_from": "2020-01-01",
        "effective_to": "2026-02-14",
    },
    {
        "country_code": "XX",
        "subdivision_code": None,
        "tax_code": "VAT",
        "tax_name": "Test VAT",
        "rate_pct": "20.0",
        "combination": "national",
        "is_default": True,
        "effective_from": "2026-02-15",
        "effective_to": None,
    },
]


@pytest.mark.parametrize(
    ("stated", "expected", "why"),
    [
        ("2026-Q1", "10", "the quarter opened on 1 January, five weeks before the rise"),
        ("2026-02", "10", "the month opened on 1 February, a fortnight before the rise"),
        ("2026", "10", "the year opened on 1 January"),
        ("2026-02-20", "20", "a full date is nobody's period and is read as the day it is"),
        ("2026-Q2", "20", "the quarter opened on 1 April, after the rise"),
    ],
)
def test_a_window_opening_inside_a_stated_period_is_not_reached(stated: str, expected: str, why: str) -> None:
    """The only test here that fails if the first day is swapped for the last.

    Every rate change in the shipped seed sits on a year boundary, so a suite
    built from shipped values agrees with itself under either end. This puts
    the change on 15 February, in the middle of Q1, where the two ends give
    different money. Synthetic rows on a country code no seed uses, because the
    point is the parser's end of the period and not any real jurisdiction.
    """
    day = price_base_day(stated)
    assert day is not None
    outcome = resolve([row_from_mapping(row) for row in _MID_QUARTER_CHANGE], "XX", on_date=day.isoformat())
    assert outcome.resolved, outcome.reason
    assert outcome.combined_rate_pct == expected, why


# ── The validation rule that makes a bad value visible ──────────────────────


@pytest.mark.asyncio
async def test_a_base_date_nothing_can_read_is_reported_on_the_validation_run() -> None:
    """The log names the bill for an operator; this names it for the estimator."""
    results = await BOQBaseDateReadable().validate(bill(base_date="01.02.2026"))

    assert len(results) == 1
    result = results[0]
    assert not result.passed
    assert result.severity is Severity.WARNING, "a mistyped price base does not stop a bill from being priced"
    assert result.category is RuleCategory.STRUCTURE
    assert result.details["base_date"] == "01.02.2026", "the value has to travel with the finding or nobody can fix it"
    assert "01.02.2026" in result.message
    assert result.suggestion and "2026-Q1" in result.suggestion, "say what a readable value looks like"


@pytest.mark.asyncio
@pytest.mark.parametrize("stated", ["2026-03-15", "2026-03", "2026-Q1", "2026"])
async def test_a_readable_base_date_passes_the_rule(stated: str) -> None:
    results = await BOQBaseDateReadable().validate(bill(base_date=stated))
    assert len(results) == 1
    assert results[0].passed, f"{stated} is a shape the pricing path reads, so the rule must not flag it"


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", [None, "", "   "])
async def test_a_bill_with_no_base_date_is_asked_nothing_by_this_rule(blank: str | None) -> None:
    """Whether a bill must state a base date at all is NRM's question, and
    ``NRMBaseDateDeclared`` asks it of the bills NRM governs. Answering it here
    too would put a second, unclearable warning on every bill in every other
    market."""
    assert await BOQBaseDateReadable().validate(bill(base_date=blank)) == []


@pytest.mark.parametrize("locale", ["en", "de", "es", "ru"])
@pytest.mark.parametrize("key", ["boq_quality.base_date_readable.fail", "boq_quality.base_date_readable.suggestion"])
def test_the_rules_messages_are_translated_in_every_shipped_locale(locale: str, key: str) -> None:
    """A rule whose message is missing renders as its own key, which is worse
    than no rule: the reader is told a code they cannot act on."""
    assert is_key_present(key, locale), f"{key} is missing from {locale}.json"


# ── The second reader: which of a project's bills is the freshest ───────────


def test_the_freshest_price_base_is_chosen_by_its_date_and_not_by_string_order() -> None:
    """The defect ``latest_base_date`` replaces, stated as the case that shows it.

    ``SELECT max(base_date)`` ranks the strings, and ``"Q"`` is above every
    digit, so a bill labelled ``2026-Q1`` outranked one dated December of the
    same year. The estimate basis quotes that value to the client as the date
    the prices are current to.
    """
    assert max(["2026-Q1", "2026-12-01"]) == "2026-Q1", "the string order this exists to stop has changed"
    assert latest_base_date(["2026-Q1", "2026-12-01"]) == "2026-12-01"
    assert latest_base_date(["2025-Q4", "2026-Q1", "2024-06-30"]) == "2026-Q1"
    # Two bills that state the same day in different words are a tie, and a tie
    # has no freshest bill. Either label is a true answer, so the day is
    # asserted rather than the spelling of whichever one arrived first.
    assert price_base_day(latest_base_date(["2026-01", "2026-Q1"])) == date(2026, 1, 1)


def test_the_freshest_price_base_comes_back_as_the_bill_wrote_it() -> None:
    """The document quotes the estimator, not this module's reading of them."""
    assert latest_base_date(["2025-06-01", "  2026-Q3  "]) == "2026-Q3"


def test_a_project_whose_bills_state_nothing_has_no_price_base() -> None:
    assert latest_base_date([]) is None
    assert latest_base_date([None, "", "   "]) is None


def test_an_unreadable_basis_is_still_quoted_when_it_is_all_there_is() -> None:
    """Dropping it would delete a line from a client-facing document because
    this module could not parse a value a person chose to write. A readable
    value outranks it, but on its own it stands."""
    assert latest_base_date(["mid 2026", "not a date"]) == "not a date"
    assert latest_base_date(["mid 2026", "2026-Q1"]) == "2026-Q1"


def test_the_accepted_shapes_are_the_shapes_the_parser_reads() -> None:
    """``ACCEPTED_SHAPES`` is quoted at the user in the log line and in the
    rule's suggestion, so a shape listed there that the parser refuses would
    send somebody to retype a value into another rejection."""
    for shape in ACCEPTED_SHAPES:
        assert price_base_day(shape) is not None, f"{shape} is advertised as readable but is not read"
