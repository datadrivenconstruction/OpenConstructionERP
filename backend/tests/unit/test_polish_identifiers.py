# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Polish NIP, REGON, KRS and postal code: the checks and where they are enforced.

Every valid value below has its check digit worked out in the comment beside
it, so a reader can see the case is a real distinguishing one and not a value
copied from the implementation under test.
"""

from __future__ import annotations

import pytest

from app.core.pl_ids import krs_is_valid, nip_is_valid, pl_postcode_is_valid, regon_is_valid
from app.core.provenance import Source
from app.core.validation.address import get_address_rules, validate_address
from app.modules.subcontractors.tax_id import canonical_tax_id, validate_tax_id

# ── NIP ───────────────────────────────────────────────────────────────────────
#
# Weights 6 5 7 2 3 4 5 6 7 over the first nine digits, sum mod 11.
#
# 526-025-09-95: 5*6 + 2*5 + 6*7 + 0*2 + 2*3 + 5*4 + 0*5 + 9*6 + 9*7
#              = 30 + 10 + 42 + 0 + 6 + 20 + 0 + 54 + 63 = 225; 225 mod 11 = 5 -> tenth digit 5.
# 123-456-32-18: 6 + 10 + 21 + 8 + 15 + 24 + 15 + 12 + 7 = 118; 118 mod 11 = 8 -> 8.
# 123-450-00-7x: 6 + 10 + 21 + 8 + 15 + 0 + 0 + 0 + 49 = 109; 109 mod 11 = 10 -> no digit can match.


@pytest.mark.parametrize("value", ["5260250995", "1234563218", "PL 526-025-09-95", "pl5260250995", "123-45-63-218"])
def test_a_nip_with_a_correct_check_digit_is_valid_in_every_printed_spelling(value: str) -> None:
    assert nip_is_valid(value)


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("5260250994", "last digit changed by one"),
        ("1234563219", "last digit changed by one"),
        ("1234500070", "remainder 10, no tenth digit can match"),
        ("1234500071", "remainder 10, no tenth digit can match"),
        ("526025099", "nine digits"),
        ("52602509950", "eleven digits"),
        ("52602509A5", "a letter inside"),
        ("", "empty"),
    ],
)
def test_a_nip_that_fails_its_check_is_refused(value: str, why: str) -> None:
    assert not nip_is_valid(value), why


# ── REGON ─────────────────────────────────────────────────────────────────────
#
# Nine digits, weights 8 9 2 3 4 5 6 7, sum mod 11, 10 written as 0.
# 12345678x: 8 + 18 + 6 + 12 + 20 + 30 + 42 + 56 = 192; 192 mod 11 = 5 -> 123456785.
# 12345616x: 8 + 18 + 6 + 12 + 20 + 30 + 6 + 42 = 142; 142 mod 11 = 10 -> 0 -> 123456160.
#
# Fourteen digits, weights 2 4 8 5 0 9 7 3 6 1 2 4 8, sum mod 11, 10 written as 0.
# 1234567850001x: 2 + 8 + 24 + 20 + 0 + 54 + 49 + 24 + 30 + 0 + 0 + 0 + 8 = 219;
#                 219 mod 11 = 10 -> 0 -> 12345678500010.
# 1234567800001x: own check 2, but its parent 123456780 is not a valid REGON (needs 5).


@pytest.mark.parametrize("value", ["123456785", "123456160", "12345678500010", "123-456-785"])
def test_a_regon_with_correct_check_digits_is_valid(value: str) -> None:
    assert regon_is_valid(value)


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("123456786", "nine digits, check digit changed"),
        ("123456161", "nine digits, the 10 -> 0 case written as 1"),
        ("12345678500011", "fourteen digits, check digit changed"),
        ("12345678000012", "own check digit right, parent nine digits wrong"),
        ("1234567850", "ten digits is neither form"),
        ("12345678A", "a letter inside"),
        ("", "empty"),
    ],
)
def test_a_regon_that_fails_its_check_is_refused(value: str, why: str) -> None:
    assert not regon_is_valid(value), why


# ── KRS ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["0000012345", "0000 012 345", "1234567890"])
def test_a_krs_number_is_ten_digits(value: str) -> None:
    assert krs_is_valid(value)


@pytest.mark.parametrize("value", ["000012345", "00000123456", "000001234X", ""])
def test_a_krs_number_of_another_shape_is_refused(value: str) -> None:
    assert not krs_is_valid(value)


# ── Postal code ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["00-950", "31-042", " 80-001 "])
def test_a_polish_postcode_is_two_digits_hyphen_three(value: str) -> None:
    assert pl_postcode_is_valid(value)


@pytest.mark.parametrize("value", ["00950", "0-950", "000-950", "00 950", "AB-123", ""])
def test_a_polish_postcode_without_its_hyphen_or_of_another_shape_is_refused(value: str) -> None:
    assert not pl_postcode_is_valid(value)


# ── Where the checks are enforced ─────────────────────────────────────────────


def test_the_subcontractor_form_refuses_a_well_shaped_nip_with_a_wrong_check_digit() -> None:
    """Ten digits matched the old format-only rule; the check digit now decides."""
    good = validate_tax_id("PL", "PL 526-025-09-95")
    bad = validate_tax_id("PL", "PL 526-025-09-94")

    assert good.format_valid is True
    assert good.tax_id_normalised == "5260250995"
    assert good.reason is None

    assert bad.format_valid is False
    assert bad.standard == "EU VAT (PL)"
    assert bad.reason == "checksum_mismatch:EU VAT (PL)"


def test_a_wrong_shape_is_still_reported_as_a_format_mismatch_not_a_checksum_one() -> None:
    result = validate_tax_id("PL", "PL526025099")
    assert result.format_valid is False
    assert result.reason == "format_mismatch:EU VAT (PL)"


def test_the_identity_key_of_a_polish_number_does_not_depend_on_its_check_digit() -> None:
    """Two rows holding the same mistyped NIP must still be found as one firm."""
    assert canonical_tax_id("PL", "PL 526-025-09-94") == canonical_tax_id("PL", "5260250994") == "5260250994"


def test_another_country_is_not_checked_against_the_polish_algorithm() -> None:
    """SK shares the ten-digit shape; a value failing the NIP check must still pass there."""
    assert not nip_is_valid("5260250994")
    assert validate_tax_id("SK", "5260250994").format_valid is True


def _warsaw(postcode: str) -> dict[str, str]:
    return {"street": "ul. Marszałkowska 1", "postcode": postcode, "city": "Warszawa", "country": "PL"}


def test_a_polish_address_is_judged_by_polish_rules() -> None:
    jurisdiction = get_address_rules("PL")["jurisdiction"]
    assert jurisdiction.source is Source.DECLARED
    assert jurisdiction.used == "PL"


def test_a_polish_address_with_a_bad_postcode_now_fails() -> None:
    """Under the presence-only fallback this address passed; under PL rules it does not."""
    result = validate_address(_warsaw("00950"), "PL")
    assert not result.passed
    assert result.error_fields == ["postcode"]
    assert result.errors[0].code == "invalid_format"


def test_a_polish_address_with_a_good_postcode_passes() -> None:
    assert validate_address(_warsaw("00-950"), "PL").passed


def test_a_polish_address_without_a_postcode_fails() -> None:
    address = _warsaw("")
    result = validate_address(address, "PL")
    assert not result.passed
    assert "postcode" in result.error_fields
