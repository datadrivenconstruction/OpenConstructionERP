# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Russia charges 20 % before 2026 and 22 % from 2026-01-01, and both halves are asserted.

The defect this pins
--------------------
Russia raised standard VAT from 20 % to 22 % with effect from 2026-01-01
(Tax Code article 164 as amended, sourced below). The seed file went on
shipping a single window at
20 % dated from 2019-01-01 with no ``effective_to``, so every Russian document
dated in 2026 was priced two points low, and had been for the eight months
between the change and the commit that added this file.

Why both directions are asserted, and why that is the point
-----------------------------------------------------------
The obvious repair is to edit ``20.0`` to say ``22.0``. It is wrong, and a test
that checked only the new rate would pass against it just as happily. Editing
in place leaves one open window running from 2019-01-01, so every Russian
document ever priced - all of 2019 through 2025 - silently re-resolves at 22 %
on its next read. Estimates and invoices already issued at the rate of their
day quietly change value. The date windows exist to stop exactly that, so the
2025 assertion below is not a courtesy check on old data: it is the half that
catches the wrong fix.

Read against the shipped file, not a fixture
--------------------------------------------
The rows come from ``seed_data/tax_configurations.json`` itself. A hand-built
fixture would let this file go green while the shipped data stayed wrong, which
is the vacuous pass the whole exercise is about.

Where the rate comes from
-------------------------
Not from anything already in this repository. The repository said 20 in five
places, consistently, and that consistency was the thing under suspicion rather
than evidence about Russian law. Grepping the Romanian rows teaches the file
format and nothing else.

* Federal Tax Service of Russia, "Taxes 2026", https://www.nalog.gov.ru/new2026/
  (read 2026-09-07). It gives the standard rate as "20% -> 22%" and states that
  the tax at those rates applies to sales of goods, works and services from
  1 January 2026. The calculation rate moves with it, 20/120 becoming 22/122
  and 16.67 becoming 18.03.
* The instrument that page implements is Federal Law No. 425-FZ of 28 November
  2025, amending parts one and two of the Tax Code, official publication number
  0001202511280017 on the state publication portal at publication.pravo.gov.ru.
  That identity is taken from the portal's index record. The law text itself
  did not load, so nothing here is quoted from it and the rate above rests on
  the tax service page.

The reduced rate did not move
-----------------------------
Sourced rather than inferred from the headline rate, because a reform that
raises the standard rate is under no obligation to leave the reduced one alone.
The same tax service page enumerates the 2026 rate changes and lists 22, 22/122
and 18.03 as changed while listing 10 as unchanged. Corroboration from that
same page, so not a second source: the 10/110 calculation rate stays as it is
while 20/120 becomes 22/122, which it could not do if the 10 had moved.
``test_the_reduced_rate_did_not_change`` below holds the shipped row to that.

Which date the resolver is handed, and why that is still open
-------------------------------------------------------------
A dated window is only as good as the date it is queried with.
``BOQService.apply_default_markups`` passes ``BOQ.base_date`` into
``_seeded_vat_rate``, which forwards it to ``resolve`` as ``on_date`` when and
only when it fullmatches ``YYYY-MM-DD``; anything else is dropped and the bill
is dated today. But ``base_date`` is documented in ``boq/schemas.py`` as the
price level reference, the date the unit rates are indexed to, while the tax
service wording keys the new rate on realisation of the works from 1 January
2026 whatever date the contract carries. Those are two different axes. A
Russian bill indexed to 2025 prices for works performed in 2026 therefore
resolves at 20 where the works attract 22.

The exposure is one sided and narrow. The shipped demo packs put "2026-Q1" and
"2026-01" in that column, neither of which is an ISO date, so they are dropped
and land on today, which is currently the right answer by accident of the
fallback. It bites only a bill carrying a real past ISO date, and the number it
produces is a seeded suggestion that both the project's ``default_vat_rate``
and the bill's own ``tax_rate`` override. Which date a bill of quantities is
taxed on is a product decision and not a data repair, so it is recorded here
and left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.i18n_foundation.tax_rules import resolve, row_from_mapping

_SEED = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "modules"
    / "i18n_foundation"
    / "seed_data"
    / "tax_configurations.json"
)


def _shipped_rows():
    """Every rate line in the shipped seed file, flattened for the resolver."""
    with _SEED.open(encoding="utf-8") as handle:
        return [row_from_mapping(row) for row in json.load(handle)]


def _russian_standard_windows() -> list[dict]:
    """The shipped ``NDS`` windows, oldest first."""
    with _SEED.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    windows = [row for row in rows if row["country_code"] == "RU" and row["tax_code"] == "NDS"]
    return sorted(windows, key=lambda row: row["effective_from"] or "")


@pytest.mark.parametrize(
    ("on_date", "expected", "why"),
    [
        ("2025-06-01", "20", "a document dated before the change keeps the rate of its day"),
        ("2025-12-31", "20", "the last day of the old window is still charged at the old rate"),
        ("2026-01-01", "22", "the first day of the new window is charged at the new rate"),
        ("2026-09-07", "22", "the day this defect was found, eight months into the new rate"),
    ],
)
def test_a_russian_document_is_priced_at_the_rate_of_its_own_date(on_date: str, expected: str, why: str) -> None:
    """Both sides of 2026-01-01, from the shipped seed file.

    ``resolved`` is asserted alongside the number because the failure mode of
    a later edit to the ``is_default`` flags is not a wrong rate but no rate at
    all - ``default_rate_not_in_force``, with ``combined_rate_pct`` None. A
    bare rate comparison would report that as ``None != "20"`` and send the
    next reader looking for a missing row rather than a moved flag.
    """
    outcome = resolve(_shipped_rows(), "RU", on_date=on_date)

    assert outcome.resolved, (
        f"Russia could not be priced on {on_date} ({outcome.status}: {outcome.reason}). "
        "If this says default_rate_not_in_force, the is_default flags moved: both NDS "
        "windows must ship it true, because the open-ended NDS_RED row would otherwise "
        "leave two unflagged country-wide rows in force and nothing to choose between them."
    )
    assert outcome.combined_rate_pct == expected, f"{on_date}: {why}"


def test_the_old_rate_was_closed_rather_than_overwritten() -> None:
    """The shape of the change, asserted directly rather than only through its effects.

    The parametrised test above already fails if the 20 % window is overwritten,
    but it fails on an arithmetic comparison and leaves the reader to work out
    why. This names the mistake.
    """
    windows = _russian_standard_windows()

    assert len(windows) == 2, (
        f"expected two NDS windows, the 20 % one closed and the 22 % one open, found {len(windows)}. "
        "One window means the rate was edited in place, which re-prices every document "
        "back to 2019 at whatever the single window now says."
    )

    old, new = windows
    assert (old["rate_pct"], old["effective_from"], old["effective_to"]) == ("20.0", "2019-01-01", "2025-12-31")
    assert (new["rate_pct"], new["effective_from"], new["effective_to"]) == ("22.0", "2026-01-01", None)


def test_both_standard_windows_stay_flagged_the_default() -> None:
    """Russia is the Israeli shape, not the Romanian one, and it has to be.

    Romania unflags its closed window and flags its successor, because there
    the flag names the current standard rate and moves with it. Copying that
    here breaks Russia: ``NDS_RED`` is open-ended from 2004-01-01, so it is in
    force alongside every standard window, and an unflagged closed window would
    leave two unflagged country-wide rows in force for every date from 2019 to
    2025. ``_country_wide_standard`` cannot choose between them and
    ``_is_earlier_period`` cannot rescue it, because that path needs exactly
    one row in force. Russia would answer with no rate at all.

    The flags are safe to leave alone because the resolver reads them only
    among the rows in force on the date asked about, and two windows of one
    line never overlap.
    """
    assert [row["is_default"] for row in _russian_standard_windows()] == [True, True]


def test_the_reduced_rate_did_not_change() -> None:
    """The amendment raised the standard rate only, so NDS_RED is left alone.

    Stated as an assertion rather than left unexamined: the 10 % class covers
    food, medicine, children's goods and books, and it was retained. If a later
    reform moves it, this is the test that should fail and bring somebody here.
    """
    with _SEED.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    reduced = [row for row in rows if row["country_code"] == "RU" and row["tax_code"] == "NDS_RED"]

    assert len(reduced) == 1, "the reduced class was not part of the 2026 change and should still be one window"
    assert reduced[0]["rate_pct"] == "10.0"
    assert reduced[0]["effective_to"] is None
