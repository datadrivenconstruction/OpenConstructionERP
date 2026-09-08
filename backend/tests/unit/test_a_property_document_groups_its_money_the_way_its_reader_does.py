"""A property document punctuates an amount the way the locale it is issued in does.

Digit grouping is not three-by-three everywhere, and the renderer behind every
contract, receipt and certificate the property module issues assumed it was.
``_format_money`` chunked the reversed integer part in threes for every locale,
so a Hindi contract printed ``47,657,972.78`` where India writes
``4,76,57,972.78`` - three digits, then twos, because ``lakh`` names the sixth
digit and ``crore`` the eighth. A figure grouped the other way cannot be read
aloud without counting the digits first.

The separators were the second half. ``_separators_for_locale`` named nine
languages and let the other eighteen offered ones fall through to the English
pair. Ten of those were wrong. For five (cs, fi, no, sv, bg) the reader writes
a space and a comma. For five more (da, vi, id, ro, hr) the fall-through
changed what the figure says rather than how it looks: those readers take ``,``
as the decimal separator, so ``47,657,972.78`` opens with something that reads
as forty-seven point six five seven.

Measured across the 27 locales the picker offers, 12 were written wrongly.

The expectations below are pinned as whole strings rather than assembled from a
separator and a group size, because assembling them would be this module's own
grouping code written twice and would agree with itself whatever it did. Each
is what ``Intl.NumberFormat(<root>)`` produces for the same amount on the CLDR
data every browser in that market already uses, with the one deliberate
substitution the renderer documents: U+00A0 stands in for the U+202F CLDR gives
French, the two being non-breaking spaces no reader can tell apart in print.

Both directions are asserted for the grouping, because either alone is green
against code that is still broken: a test that only demands the lakh spelling
for Hindi passes if every locale is switched to it, and one that only demands
threes for English passes against the renderer being fixed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.property_dev.document_templates import (
    _SEPARATORS,
    SUPPORTED_LOCALES,
    _base_language,
    _format_money,
)

#: Eight integer digits, which is the shortest amount at which the Indian and
#: the Western grouping disagree in more than one place, and a non-zero digit
#: in every position so no expectation below is satisfied by a rounder number.
AMOUNT = Decimal("47657972.78")

#: A non-breaking space, spelled out so this file carries no invisible
#: character whose identity a reader has to take on trust.
NBSP = "\u00a0"

WESTERN = "47,657,972.78"
CONTINENTAL = "47.657.972,78"
SPACED = f"47{NBSP}657{NBSP}972,78"
INDIAN = "4,76,57,972.78"

#: Every locale the document picker offers, and the one string its reader
#: writes this amount as. The population under test is this table, and it is
#: asserted below to be the whole picker rather than a convenient subset.
EXPECTED: dict[str, str] = {
    "ar": WESTERN,
    "bg": SPACED,
    "cs": SPACED,
    "da": CONTINENTAL,
    "de": CONTINENTAL,
    "en": WESTERN,
    "es": CONTINENTAL,
    "fi": SPACED,
    "fr": SPACED,
    "hi": INDIAN,
    "hr": CONTINENTAL,
    "id": CONTINENTAL,
    "it": CONTINENTAL,
    "ja": WESTERN,
    "ko": WESTERN,
    "mn": WESTERN,
    "nl": CONTINENTAL,
    "no": SPACED,
    "pl": SPACED,
    "pt": CONTINENTAL,
    "ro": CONTINENTAL,
    "ru": SPACED,
    "sv": SPACED,
    "th": WESTERN,
    "tr": CONTINENTAL,
    "vi": CONTINENTAL,
    "zh": WESTERN,
}


def test_the_four_spellings_are_actually_four_different_strings() -> None:
    """Without this the table above could be green and measuring nothing."""
    spellings = {WESTERN, CONTINENTAL, SPACED, INDIAN}
    assert len(spellings) == 4, f"the expectations collapse onto each other: {sorted(spellings)}"


def test_every_offered_locale_is_under_test() -> None:
    """The denominator, asserted rather than assumed.

    A pinned table is only worth its verdict if it covers the whole picker. A
    28th locale added to ``SUPPORTED_LOCALES`` fails here rather than being
    quietly rendered in English and reported as no defect.
    """
    offered = {_base_language(code) for code in SUPPORTED_LOCALES}
    assert offered == set(EXPECTED), (
        f"the picker and this test disagree about the population "
        f"({len(offered)} offered, {len(EXPECTED)} under test): "
        f"offered only {sorted(offered - set(EXPECTED))}, tested only {sorted(set(EXPECTED) - offered)}"
    )


def test_every_offered_locale_has_a_separator_row_of_its_own() -> None:
    """The drift assertion, and the one that outlives this file's table.

    The renderer answers a locale it has no row for with the English pair. That
    is right for a locale nobody offers and wrong the moment one is added to
    the picker, because the fall-through renders and raises nothing: the
    contract is issued, in somebody else's punctuation. Ten of the offered
    locales reached the reader that way before this was written.
    """
    offered = {_base_language(code) for code in SUPPORTED_LOCALES}
    missing = sorted(offered - set(_SEPARATORS))
    assert not missing, (
        f"{len(missing)} of {len(offered)} offered document locales have no separator row "
        f"and would be issued in English punctuation: {missing}"
    )


@pytest.mark.parametrize("locale", sorted(EXPECTED))
def test_an_amount_is_written_the_way_that_locale_writes_one(locale: str) -> None:
    written = _format_money(AMOUNT, locale, "EUR")
    assert written == EXPECTED[locale], (
        f"{locale} document money is written {written!r}, "
        f"its reader writes {EXPECTED[locale]!r} "
        f"(population: {len(EXPECTED)} offered document locales)"
    )


def test_a_hindi_contract_is_grouped_in_lakh_and_crore() -> None:
    """The defect, stated on its own so a failure names it.

    Hindi is the one offered locale in the Indian system, and it was the one
    the old code could not express at all: no locale argument reached the
    chunking, so the grouping was the same for every reader in the picker.
    """
    written = _format_money(AMOUNT, "hi", "EUR")
    assert written == INDIAN, f"a Hindi contract is grouped {written!r}, India writes {INDIAN!r}"
    assert written != WESTERN, f"a Hindi contract is still grouped by threes: {written!r}"


def test_an_english_contract_is_still_grouped_by_threes() -> None:
    """The control, and the other direction of the same assertion.

    A fix that grouped every locale in lakh would satisfy the test above and
    fail here. Twenty-six of the twenty-seven offered locales group by threes,
    so this is the majority behaviour and not a special case.
    """
    written = _format_money(AMOUNT, "en", "EUR")
    assert written == WESTERN, f"an English contract is grouped {written!r}, not {WESTERN!r}"
    assert written != INDIAN, f"an English contract picked up the Indian grouping: {written!r}"


@pytest.mark.parametrize(
    ("digits", "expected"),
    [
        # The boundaries of the twos, either side of where the first pair
        # opens. Below four digits the two systems agree and the grouping has
        # nothing to say; a test that only measured large amounts would pass
        # against code that punctuated "999" as "9,99".
        (Decimal("999"), "999.00"),
        (Decimal("1000"), "1,000.00"),
        (Decimal("99999"), "99,999.00"),
        (Decimal("100000"), "1,00,000.00"),
        (Decimal("10000000"), "1,00,00,000.00"),
        (Decimal("1000000000"), "1,00,00,00,000.00"),
    ],
)
def test_the_indian_grouping_opens_its_pairs_in_the_right_place(digits: Decimal, expected: str) -> None:
    assert _format_money(digits, "hi", "EUR") == expected


def test_a_forint_keeps_the_indian_grouping_without_a_decimal_separator() -> None:
    """The zero-subunit path runs through the same grouping and past the rest.

    ``_format_money`` returns early for a currency with no minor unit, so the
    grouping and the decimal separator are reached by different lines and a fix
    applied to one of them only would leave the forint behind.
    """
    assert _format_money(AMOUNT, "hi", "HUF") == "4,76,57,973"
