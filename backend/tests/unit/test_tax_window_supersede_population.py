# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The set of rate lines the supersede repair will rewrite is pinned, not merely derived.

Why this file exists at all
---------------------------
``tax_window_supersede`` derives its population from
``tax_configurations.json`` rather than naming a country, which is the whole
argument for it being general: the next time a legislature changes a rate, the
window goes in the seed file and the repair carries every upgraded install
forward without anybody writing a second module.

That is also the risk. Derived means a seed edit changes what a boot-path
repair rewrites on customer data, with nobody necessarily aware that it did. So
the derivation is pinned here. Adding a second window to a rate line is meant
to fail this test and make somebody look at what the repair is now going to do
to every install in the field.

The gap this closes is measured rather than assumed
---------------------------------------------------
Nothing else in the tree notices a new window.
``test_tax_seed_reconcile_covers_the_seed_file`` pins ``anchor_lines()``, which
is a set of ``(country_code, tax_code)`` pairs - giving an existing line a
second window leaves both its count and its digest untouched, and
``test_tax_tables_do_not_drift`` reads rates rather than window structure. That
is exactly how Nova Scotia's cut reached new installs, skipped every old one,
and went a year without a red test.
"""

from __future__ import annotations

import pytest

from app.modules.i18n_foundation import tax_window_supersede
from app.modules.i18n_foundation.tax_seed_reconcile import LINE_FIRST_SHIPPED, REPAIRED_ELSEWHERE
from app.modules.i18n_foundation.tax_window_supersede import (
    EARLIEST_SUPERSEDED_FROM,
    superseded_lines,
)

#: Every rate line the shipped file carries more than one window of, less the
#: lines another repair owns. Written out rather than counted: a count would
#: pass if one line were swapped for another, and the new one is precisely the
#: one nobody has looked at.
#:
#: ``IL/VAT`` was added on 2026-09-02, and this test failing is what it was
#: supposed to do. What was looked at before updating it, since that is the
#: whole purpose of the pin:
#:
#: * Israel raised standard VAT from 17 % to 18 % on 2025-01-01 (Israel Tax
#:   Authority; legislated in the 2025 Economic Arrangements Law). The seed
#:   file had gone on shipping 17 with no ``effective_to``, so the platform
#:   stated 17 as the rate in force while its own methodology catalogue said
#:   18. The 17 % window is closed at 2024-12-31 and the 18 % one added beside
#:   it, so a bill priced before 2025 still prices at 17.
#: * What the repair will therefore do to installs in the field: close the
#:   open 17 % row and insert the 18 % one. That is the intended reading of
#:   the change to the seed file, on the same argument as Nova Scotia's.
#: * The flag stays still. Both Israeli windows ship ``is_default`` true,
#:   which the module docstring covers at length: ``_country_wide_standard``
#:   reads the flag only among rows in force on the date asked about, and two
#:   windows of one line never overlap. So the repair's predicate matches
#:   without ``also_updates`` gaining anything, and the assertion below that
#:   it stays empty still holds.
#:
#: The population growing also moved ``EARLIEST_SUPERSEDED_FROM`` from
#: 2025-04-01 to 2025-01-01, because Israel's rise predates Nova Scotia's cut.
#:
#: ``RU/NDS`` was added on 2026-09-07, and this test failing is what it was
#: supposed to do. What was looked at before updating it:
#:
#: * Russia raised standard VAT from 20 % to 22 % with effect from
#:   2026-01-01 (НК РФ ст. 164 as amended). The seed file had gone on
#:   shipping one open window at 20 % dated from 2019-01-01, so every
#:   Russian document dated in 2026 was priced two points low for the eight
#:   months between the change and this commit. The 20 % window is closed at
#:   2025-12-31 and the 22 % one added beside it, so a bill priced before
#:   2026 still prices at 20.
#: * What the repair will therefore do to installs in the field: close the
#:   open 20 % row and insert the 22 % one, on the same argument as Nova
#:   Scotia's and Israel's.
#: * The flag stays still, and here that is a constraint rather than a
#:   convenience. Both Russian windows ship ``is_default`` true, the Israeli
#:   way and not the Romanian way, and they *must*: Russia's ``NDS_RED``
#:   reduced row is open-ended from 2004-01-01, so it is in force alongside
#:   every standard window. Unflagging the closed 20 % row the way Romania
#:   unflags its 19 % one would leave a 2025 query looking at two unflagged
#:   country-wide rows, which ``_country_wide_standard`` cannot choose
#:   between; ``_is_earlier_period`` does not rescue it either, because that
#:   needs exactly one row in force. Russia would answer
#:   ``default_rate_not_in_force`` for every date from 2019 to 2025 - no rate
#:   at all, not a wrong one. So the repair's predicate matches without
#:   ``also_updates`` gaining anything, and the assertion that it stays empty
#:   still holds.
#: * ``EARLIEST_SUPERSEDED_FROM`` does not move. It is derived from
#:   ``windows[1:]``, the superseding windows only, and 2026-01-01 is later
#:   than Israel's 2025-01-01.
EXPECTED_POPULATION = {("CA", "HST_NS"), ("IL", "VAT"), ("RU", "NDS")}


def test_the_repair_will_touch_exactly_these_rate_lines() -> None:
    """A new window in the seed file must be seen by a person before it ships."""
    assert set(superseded_lines()) == EXPECTED_POPULATION, (
        "the set of rate lines tax_configurations.json ships more than one window of has "
        "changed. That set is what tax_window_supersede rewrites on every install in the "
        "field: it closes the window each of those lines still holds open and inserts the "
        "rate that replaced it. Read the new line, satisfy yourself that closing its old "
        "window is what the change to the seed file meant, then update EXPECTED_POPULATION."
    )


def test_a_line_owned_by_another_repair_is_not_in_the_population() -> None:
    """Two repairs closing one window would half-apply whichever plan ran second.

    Romania's shipped 19 % window is closed in the file exactly as Nova Scotia's
    15 % one is, so an old install's open 19 % row matches this repair's
    predicate as well as ``romania_vat_2025``'s. Only the subtraction in
    :func:`superseded_lines` keeps them apart, and it is one line of code that
    a tidy-up could remove without anything else objecting.
    """
    overlap = set(superseded_lines()) & REPAIRED_ELSEWHERE
    assert not overlap, f"rate lines claimed by two superseding repairs at once: {sorted(overlap)}"


def test_the_romanian_line_really_would_be_claimed_without_the_subtraction() -> None:
    """The check above is only worth having if the thing it forbids is reachable.

    Without this, a subtraction that had quietly stopped matching anything - a
    renamed tax code, say - would leave the test above passing for the wrong
    reason, and it would go on passing right up until two repairs fought over
    one row on a customer's database.
    """
    every_multi_window_line = {line for line, windows in _group_the_shipped_file().items() if len(windows) > 1}
    assert REPAIRED_ELSEWHERE & every_multi_window_line, (
        "no line owned by another repair ships more than one window any more, so the "
        "subtraction in superseded_lines() no longer removes anything and the disjointness "
        "test above proves nothing"
    )


def _group_the_shipped_file() -> dict[tuple[str, str], list[dict]]:
    from app.modules.i18n_foundation.seed import load_tax_seed_rows

    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in load_tax_seed_rows():
        if row.get("tax_code") is None:
            continue
        grouped.setdefault((row["country_code"], row["tax_code"]), []).append(row)
    return grouped


def test_the_declared_effective_date_is_the_earliest_the_population_supersedes() -> None:
    """The declaration a support log reads must not go stale against the file.

    ``SupersededBy.effective_from`` is documentation - nothing branches on it -
    which is exactly why it rots quietly. It is a literal in ``repairs.py``
    because that module is deliberately import-light, so this is what keeps the
    literal honest.
    """
    earliest = min(window["effective_from"] for windows in superseded_lines().values() for window in windows[1:])
    assert earliest == EARLIEST_SUPERSEDED_FROM, (
        f"the repair declares it supersedes from {EARLIEST_SUPERSEDED_FROM} but the earliest "
        f"replacement window in the seed file starts on {earliest}"
    )


def test_the_registered_repair_declares_the_same_date() -> None:
    """And the literal in repairs.py is the one this module pins."""
    from app.core.data_repairs import discover_data_repairs

    repair = next(r for r in discover_data_repairs() if r.repair_id == tax_window_supersede.REPAIR_ID)
    assert repair.superseded is not None
    assert repair.superseded.effective_from == EARLIEST_SUPERSEDED_FROM
    assert repair.superseded.also_updates == (), (
        "this repair requires an existing row to already carry the shipped is_default flag "
        "rather than moving it, so it must not permit itself any edit beyond closing the window"
    )


def test_the_windows_come_back_oldest_first() -> None:
    """The repair reads position, so an unsorted list would close the wrong window."""
    for line, windows in superseded_lines().items():
        dates = [window.get("effective_from") or "" for window in windows]
        assert dates == sorted(dates), f"{line} came back out of order: {dates}"


def test_a_line_the_reconciler_delivers_wholesale_cannot_also_be_stranded_here() -> None:
    """The two repairs' populations may overlap, and it is safe that they do.

    An install that never received a rate line gets every window of it from
    ``tax_seed_reconcile``, including the closed one, and then has no window
    open that the file has closed - so this repair finds nothing. An install
    that holds the line is skipped by the reconciler and carried forward here.
    Neither can act on a line the other has acted on, in either order, which is
    why no subtraction is needed between these two.

    Asserted as the property rather than as today's empty intersection: the
    day they do overlap, this test has to keep meaning something.
    """
    for line in set(superseded_lines()) & set(LINE_FIRST_SHIPPED):
        windows = superseded_lines()[line]
        assert any(window.get("effective_to") is None for window in windows), (
            f"{line} is delivered wholesale by the reconciler and every window of it is closed, "
            "so an install given the whole line would hold no rate in force at all"
        )


class _SyntheticFile:
    """A seed file with one extra rate change in it, to prove the pin can fail."""

    ROWS = [
        {
            "country_code": "DE",
            "tax_name": "VAT",
            "tax_code": "VAT",
            "rate_pct": "19.0",
            "tax_type": "vat",
            "combination": "national",
            "subdivision_code": None,
            "effective_from": "2007-01-01",
            "effective_to": "2026-12-31",
            "is_default": True,
        },
        {
            "country_code": "DE",
            "tax_name": "VAT",
            "tax_code": "VAT",
            "rate_pct": "20.0",
            "tax_type": "vat",
            "combination": "national",
            "subdivision_code": None,
            "effective_from": "2027-01-01",
            "effective_to": None,
            "is_default": True,
        },
        {
            "country_code": "FR",
            "tax_name": "TVA",
            "tax_code": "TVA",
            "rate_pct": "20.0",
            "tax_type": "vat",
            "combination": "national",
            "subdivision_code": None,
            "effective_from": "2014-01-01",
            "effective_to": None,
            "is_default": True,
        },
    ]


def test_the_derivation_notices_a_rate_change_that_is_not_on_the_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative control, without which none of the above is evidence.

    Every check in this file is applied to a file that already has one line in
    it. If the derivation could not see a second one - a wrong grouping key, a
    length test written the wrong way round - they would all pass while the
    repair silently did nothing for the next rate change, which is the failure
    this whole module was built to stop happening twice.
    """
    monkeypatch.setattr(tax_window_supersede, "load_tax_seed_rows", lambda: _SyntheticFile.ROWS)

    found = superseded_lines()

    assert set(found) == {("DE", "VAT")}, (
        f"the derivation did not pick the superseded German rate out of a file that has one: {found}"
    )
    assert [window["rate_pct"] for window in found[("DE", "VAT")]] == ["19.0", "20.0"]
    assert set(found) != EXPECTED_POPULATION, (
        "the derivation returned the real population from a file that does not contain it, so it "
        "is not reading the file it was given"
    )
