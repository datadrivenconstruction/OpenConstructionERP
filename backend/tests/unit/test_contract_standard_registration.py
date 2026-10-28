# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A contract family is registered in three places or it is half present.

Three modules hold a table of contract standards and they are at three
different granularities:

* ``contracts.CONTRACT_CLAUSE_TEMPLATES`` - the document catalogue, one row per
  standard-form document and option (``nec4_ecc_option_a`` and
  ``nec4_ecc_option_c`` are different contracts).
* ``variations._VARIATION_CLAUSES`` - the variation clause reference, one row
  per standard edition, because the clause number moves between editions.
* ``change_intelligence.NOTICE_PERIODS`` - the notice periods, one row per
  family, because the windows are family-level and stable across editions.

They are not duplicates of each other and unifying them would force one
granularity onto all three. What they do share is a bridge:
``time_bar.normalize_standard`` maps any of these vocabularies onto a family.
These tests guard the bridge, so that a family added to one table and forgotten
in another is a red test rather than a contract that silently gets neutral
fallback notice periods, or a blank variation clause on every record.

Reaching a family is not the same as reaching periods. ``normalize_standard``
recognises families the notice engine deliberately holds no periods for
(``NOTICE_PERIODS_HELD``), so "the bridge answered" cannot stand in for "the
engine can time this". The question asked below is therefore whether a code
reaches a family that is *in* ``NOTICE_PERIODS``, which is the property every
caller of these tables actually depends on.

Adding a family to only some of the tables is allowed. Saying so out loud is
not optional: put it on the deliberately-absent list below with the consequence
spelled out, so whoever reads it is deciding rather than discovering.
"""

from __future__ import annotations

import pytest

from app.modules.change_intelligence.time_bar import (
    NOTICE_PERIODS,
    STANDARD_UNKNOWN,
    normalize_standard,
)
from app.modules.contracts.service import CONTRACT_CLAUSE_TEMPLATES
from app.modules.variations.service import _VARIATION_CLAUSES

#: Codes that resolve to no notice-period family on purpose. The value is the
#: consequence of leaving it that way, not a description of the code.
NO_NOTICE_PERIODS_ON_PURPOSE: dict[str, str] = {
    "GENERIC": (
        "The standard-neutral sentinel. It is what an unrecognised standard falls back to, "
        "so it must not have a family of its own."
    ),
    "PPC2000": (
        "No notice periods configured, so a PPC2000 record is timed by the standard-neutral "
        "fallback window and nothing on screen says the period is neutral rather than PPC2000's. "
        "PPC2000 does state timescales; adding them is a domain decision, not a wiring one."
    ),
    "VOB_B": (
        "No notice periods configured, so a VOB/B record is timed by the standard-neutral "
        "fallback window while carrying its own clause reference. VOB/B Section 6(1) states the "
        "delay notice as 'unverzueglich' with no fixed count, so a neutral reminder window is "
        "defensible, but it is a fallback and not a derivation."
    ),
}

#: Families with notice periods but no variation clause reference. The value is
#: again the consequence.
NO_VARIATION_CLAUSE_ON_PURPOSE: dict[str, str] = {
    "AIA": (
        "default_clause_for_standard returns an empty string for any AIA code, so an AIA "
        "variation record carries no default clause stamp and shows only whatever the user typed."
    ),
    "CCDC": (
        "No default clause stamp on a CCDC variation record; the user enters the clause reference "
        "manually. CCDC 2-2020 GC 6.1 and GC 6.3 are the relevant variation clauses but have not "
        "been registered in the variation clause table yet."
    ),
    "CONSENSUSDOCS": ("Same as AIA: no default clause stamp on a ConsensusDocs variation record."),
}


def _families_with_notice_periods() -> set[str]:
    """The families the notice engine can actually time a record against."""
    return set(NOTICE_PERIODS)


def _unregistered_notice_families(templates: dict[str, object], clauses: dict[str, str]) -> list[str]:
    """Codes from the outer two tables that reach no notice-period family.

    Written as a function of its inputs rather than of the module globals so the
    tests below can hand it a table with something new in it and watch it react.

    A code fails here when the family it resolves to has no row in
    ``NOTICE_PERIODS``, which covers both ways of getting there: the bridge does
    not recognise the code at all, or it recognises it as a family whose periods
    are held. Asking only whether the bridge answered would pass a held family
    and leave the record untimed anyway - the gate would be blind to its own
    defect class. The skip list stays keyed by code rather than by family
    because that is what these tables hold; a held family arriving in one of
    them has to be named here as the code it arrives as, with its consequence.
    """
    missing: list[str] = []
    for code in list(templates) + list(clauses):
        if code in NO_NOTICE_PERIODS_ON_PURPOSE:
            continue
        if normalize_standard(code) not in NOTICE_PERIODS:
            missing.append(code)
    return sorted(missing)


def test_every_contract_template_reaches_a_family_with_notice_periods() -> None:
    """A contract you can create is a contract the notice engine can time."""
    unreachable = [
        code
        for code in CONTRACT_CLAUSE_TEMPLATES
        if code not in NO_NOTICE_PERIODS_ON_PURPOSE and normalize_standard(code) not in _families_with_notice_periods()
    ]
    assert unreachable == []


def test_every_variation_standard_reaches_a_family_with_notice_periods_or_is_listed() -> None:
    """A variation standard times against its own periods, or says it does not.

    PPC2000 and VOB/B are on the list. They are timed by the standard-neutral
    fallback, which is a real answer but not a derived one, and the list is
    where that is said rather than discovered by someone reading a date.
    """
    assert _unregistered_notice_families({}, _VARIATION_CLAUSES) == []


def test_every_family_with_notice_periods_has_a_variation_clause_or_is_listed() -> None:
    """The other direction: periods without a clause reference is half present too."""
    stamped = {normalize_standard(code) for code in _VARIATION_CLAUSES} - {STANDARD_UNKNOWN}
    unstamped = sorted(_families_with_notice_periods() - stamped - set(NO_VARIATION_CLAUSE_ON_PURPOSE))
    assert unstamped == []


def test_a_family_added_to_one_table_only_is_named_rather_than_ignored() -> None:
    """The gate is not vacuous: give it a half-registered family and it reports it.

    Without this, the tests above prove only that a list comprehension can
    return an empty list. The synthetic code below normalises to UNKNOWN and
    has no row in NOTICE_PERIODS, so the gate reports it - exactly what would
    happen if someone added a contract template without configuring periods.
    """
    reported = _unregistered_notice_families({"acme_contract_2025": {}}, {})

    assert reported == ["acme_contract_2025"]


def test_a_deliberately_absent_code_carries_the_consequence_of_leaving_it_absent() -> None:
    """An entry on either list must say what it costs, not just that it is known."""
    for code, reason in {**NO_NOTICE_PERIODS_ON_PURPOSE, **NO_VARIATION_CLAUSE_ON_PURPOSE}.items():
        assert len(reason) > 60, f"{code} needs a reason that states the consequence"


@pytest.mark.parametrize("code", sorted(CONTRACT_CLAUSE_TEMPLATES))
def test_a_template_code_and_its_declared_family_agree(code: str) -> None:
    """The catalogue's own ``family`` field and the bridge must not disagree.

    ``normalize_standard`` matches on a substring of the code, so a template
    whose code and declared family drift apart would be timed as one family and
    reported as another.
    """
    declared = str(CONTRACT_CLAUSE_TEMPLATES[code]["family"])
    assert normalize_standard(code) == normalize_standard(declared)
