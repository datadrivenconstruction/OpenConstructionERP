# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country's reduced tier must not answer a question about its standard rate.

What was wrong
--------------
``resolve`` picks the country-wide row flagged ``is_default``. When no row in
force carries that flag it falls back to promoting a lone unflagged row, which
is right for a table written before the flag existed and wrong for a table
whose standard rate is on file with a window that has not started yet.

Six of the countries in the shipped seed are the second case, and between them
they misquote every date before their standard rate begins: Germany answers
7 % for 1990, Finland 14 % for 2015, Britain 0 % for 1990, Ireland 13.5 % for
2005, Italy 10 % for 2000 and Russia 10 % for 2010. Each came back with
``resolved`` true and a number a caller would put on an invoice.

Why nothing saw it
------------------
Every one of those is a real published tier of the country that answered it,
on file with a real start date, returned through the branch that exists to be
right. The three-table drift gate compares what each table holds *today*, so
it stayed green while all six misquoted every past date they were asked about.
The wire looked correct too: a status of ``national`` and a number is exactly
what a good answer looks like.

Romania is why the fix is not "refuse whenever nothing is flagged". It holds a
genuine two-row history of one tax - 19 % closed on 2025-07-31, 21 % open from
the next day - so a question about 2020 meets a single unflagged row that
really is the standard rate of that year. It answers 19 % before this change
and after it, through the same branch, and that is asserted in the same run as
the six refusals. A fix that turned Romania red would have been a blanket
refusal wearing a fix's face.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.i18n_foundation.schemas import TaxResolutionResponse
from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import TaxRateRow, resolve, row_from_mapping

#: The status a resolution carries when the country's standard rate exists and
#: was not in force on the date asked about. Written as a literal rather than
#: imported so that this file fails on its assertions rather than on its
#: imports while the status does not exist yet - a red that collects is a red
#: that proves nothing.
NOT_IN_FORCE = "default_rate_not_in_force"

#: One historical date per affected country, and the rate the resolver used to
#: return for it. The rate is carried so a failure says what was answered
#: instead of only that something was, and because each of these is a real
#: tier of that country - which is why the wrong answers were unremarkable.
MISQUOTED = [
    ("DE", "1990-01-01", "7"),
    ("FI", "2015-01-01", "14"),
    ("GB", "1990-01-01", "0"),
    # Greece arrived with its 24 % standard row opening on 2016-06-01 beside a
    # 13 % tier on file from 2011-01-01. The 23 % rate in force from 2010-07-01
    # to 2016-05-31 is not in the seed, so a Greek date in that span has no
    # standard rate to answer with. Refusing is the designed answer, the same
    # one the other members give; filing the 23 % window is a data addition
    # for later, not something this gate should force by staying red.
    ("GR", "2014-01-01", "13"),
    ("IE", "2005-01-01", "13.5"),
    ("IT", "2000-01-01", "10"),
    ("RU", "2010-01-01", "10"),
]


def _seed_rows() -> list[TaxRateRow]:
    """Every shipped rate, flattened the way the resolver reads them."""
    return [row_from_mapping(row) for row in load_tax_seed_rows()]


def _probe_dates(rows: list[TaxRateRow]) -> list[str]:
    """Every window boundary in the seed, and the day either side of it.

    Derived from the data rather than listed, so a rate added with a new start
    date is probed by this file without anybody remembering to add its date.
    The day before and the day after are what turn an off-by-one at a boundary
    into a failure instead of a coincidence.
    """
    dates = {"1970-01-01", date.today().isoformat()}
    for row in rows:
        for bound in (row.effective_from, row.effective_to):
            if bound:
                day = date.fromisoformat(bound)
                dates.update(
                    (
                        (day - timedelta(days=1)).isoformat(),
                        day.isoformat(),
                        (day + timedelta(days=1)).isoformat(),
                    )
                )
    return sorted(dates)


def _census(rows: list[TaxRateRow], dates: list[str]) -> str:
    """The population this file swept, for printing beside any verdict it gives.

    A verdict without its denominator is the failure this whole area kept
    producing: "the resolver is fine" is a claim about however many rows the
    speaker happened to look at.
    """
    countries = {row.country_code for row in rows}
    return (
        f"population: {len(rows)} shipped rate rows, {len(countries)} countries, "
        f"{len(dates)} probe dates, {len(countries) * len(dates)} country-date pairs"
    )


@pytest.mark.parametrize(("country", "on_date", "was"), MISQUOTED)
def test_a_reduced_tier_in_force_alone_does_not_answer_for_the_standard_rate(
    country: str, on_date: str, was: str
) -> None:
    """Each country whose standard rate starts after some of its tiers."""
    outcome = resolve(_seed_rows(), country, on_date=on_date)
    assert outcome.status == NOT_IN_FORCE, (
        f"{country} on {on_date} answered {outcome.status} with {outcome.combined_rate_pct}. "
        f"Its standard rate had not started on that date; {was} % is a reduced tier that runs "
        "alongside the standard rate, and promoting it prices a contract at the wrong rate "
        "while reporting the answer as resolved."
    )
    assert outcome.combined_rate_pct is None, (
        f"{country} refused and still returned {outcome.combined_rate_pct}. A refusal that "
        "carries a number is the one shape a caller cannot tell from an answer."
    )
    assert outcome.resolved is False
    assert on_date in (outcome.reason or ""), "the reason has to name the date that could not be priced"


def test_romania_still_prices_a_date_before_its_own_reform() -> None:
    """The control. One unflagged row that is a genuine earlier period still answers.

    Romania closed its 19 % row on 2025-07-31 and opened 21 % the next day.
    Nothing is flagged in force for 2020, and the answer is still 19 %,
    because a window that ends where the next begins is a predecessor rather
    than a parallel tier. This assertion is what separates the fix from a
    blanket refusal, and it runs beside the six above rather than in a file of
    its own so that neither can be read without the other.
    """
    rows = _seed_rows()
    for on_date, expected in (("2018-06-01", "19"), ("2020-01-01", "19"), ("2025-07-31", "19")):
        outcome = resolve(rows, "RO", on_date=on_date)
        assert outcome.status == "national", f"RO on {on_date} answered {outcome.status}, {outcome.reason}"
        assert outcome.combined_rate_pct == expected, f"RO on {on_date} answered {outcome.combined_rate_pct}"
    after = resolve(rows, "RO", on_date="2025-08-01")
    assert (after.status, after.combined_rate_pct) == ("national", "21")


def test_the_whole_seed_is_swept_and_only_these_countries_hold_a_dormant_standard_rate() -> None:
    """Every country against every boundary in the file, with the population named.

    The set is asserted rather than the count. A seventh country arriving here
    is a finding either way: either a rate was added with a start date later
    than a tier it sits beside, or somebody flagged the wrong row.
    """
    rows = _seed_rows()
    dates = _probe_dates(rows)
    census = _census(rows, dates)
    countries = sorted({row.country_code for row in rows})
    assert len(countries) >= 40 and len(dates) >= 100, f"the sweep collapsed to nothing - {census}"

    refusing = {
        country
        for country in countries
        for on_date in dates
        if resolve(rows, country, on_date=on_date).status == NOT_IN_FORCE
    }
    print(census)
    assert refusing == {country for country, _, _ in MISQUOTED}, (
        f"the countries whose standard rate is dormant on some date changed: {sorted(refusing)}, "
        f"expected {sorted({c for c, _, _ in MISQUOTED})}. {census}"
    )


def test_a_country_that_never_flagged_a_default_is_still_priced() -> None:
    """The legacy path this fix had to preserve, stated as its own assertion.

    A table with one country-wide row and no ``is_default`` anywhere is not
    ambiguous and not dormant - it is a row written before the flag existed.
    It still answers, and it has to, because that is most of the fixtures in
    this repo and every install seeded before the flag.
    """
    rows = [
        TaxRateRow(
            country_code="ZZ",
            tax_code="VAT",
            tax_name="Value added tax",
            rate_pct="17.5",
            tax_type="vat",
            combination="national",
            subdivision_code=None,
            effective_from="1991-04-01",
            effective_to=None,
            is_default=False,
        )
    ]
    outcome = resolve(rows, "ZZ", on_date="2000-01-01")
    assert (outcome.status, outcome.combined_rate_pct) == ("national", "17.5"), outcome.reason


def test_the_new_status_reaches_the_wire_and_carries_no_number() -> None:
    """The response model has to accept the status, and fail towards no answer.

    ``TaxResolutionStatus`` in schemas.py is a hand-copied mirror of the
    resolver's vocabulary, and it is what the endpoint validates against. A
    status added on one side only turns a country this fix repairs into a
    failed request, which is worse than the wrong number it replaced. The
    second half is the direction of the failure: a client that has never heard
    of this status still reads ``resolved`` false and ``combined_rate_pct``
    null, so it degrades to having no answer rather than to a number.
    """
    outcome = resolve(_seed_rows(), "DE", on_date="1990-01-01")
    payload = TaxResolutionResponse(
        country_code=outcome.country_code,
        subdivision_code=outcome.subdivision_code,
        subdivision_name=outcome.subdivision_name,
        status=outcome.status,
        resolved=outcome.resolved,
        combined_rate_pct=outcome.combined_rate_pct,
        federal_rate_pct=outcome.federal_rate_pct,
        as_of=outcome.as_of,
        components=[],
        reason=outcome.reason,
    )
    assert payload.status == NOT_IN_FORCE
    assert payload.resolved is False
    assert payload.combined_rate_pct is None
