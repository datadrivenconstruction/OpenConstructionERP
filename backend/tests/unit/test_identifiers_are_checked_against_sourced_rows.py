# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""National identifiers are checked against rows that say where they came from.

The Egyptian rows are the first in the catalogue. None of them was verified
against a primary regulator text, so every one ships flagged for expert review,
and the national ID check stops at the structure that sources agree on: it
does not invent a check-digit algorithm nobody has published.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.validation.address import validate_address
from app.core.validation.identifiers import IDENTIFIER_RULES, rule_for, validate_identifier
from app.core.validation.phone import validate_phone
from app.modules.subcontractors.tax_id import canonical_tax_id, validate_tax_id

# Century 2 (1900s), born 1985-03-15, Cairo (01), serial 2345 (13th digit 5: male), check digit 7.
NATIONAL_ID = "28503150123457"


def test_every_egyptian_row_names_its_source_and_awaits_review() -> None:
    rows = [rule for (country, _kind), rule in IDENTIFIER_RULES.items() if country == "EG"]
    assert {rule.kind for rule in rows} == {"tax_registration", "national_id", "company_register"}
    for rule in rows:
        assert rule.source and rule.source_url.startswith("https://"), rule.kind
        assert isinstance(rule.effective_from, date), rule.kind
        assert rule.needs_expert_review, rule.kind
        assert rule.confidence in {"H", "M", "L"}, rule.kind


def test_a_national_id_reads_out_its_structure() -> None:
    result = validate_identifier("EG", "national_id", NATIONAL_ID)
    assert result.passed, result.reason
    assert result.normalised == NATIONAL_ID
    assert result.details["birth_date"] == "1985-03-15"
    assert result.details["region_code"] == "01"
    assert result.details["sex"] == "male"
    assert result.needs_expert_review
    assert result.checksum_verified is False


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("2850315012345", "length"),
        ("48503150123457", "century"),
        ("28513150123457", "birth_date"),
        ("28502300123457", "birth_date"),
        ("28503152023457", "region_code"),
        ("2850315012345X", "length"),
    ],
)
def test_a_broken_national_id_says_which_part_is_wrong(value: str, reason: str) -> None:
    result = validate_identifier("EG", "national_id", value)
    assert not result.passed
    assert result.reason == reason


def test_a_national_id_typed_on_an_arabic_keyboard_is_the_same_number() -> None:
    arabic = "٢٨٥٠٣١٥٠١٢٣٤٥٧"
    result = validate_identifier("EG", "national_id", arabic)
    assert result.passed
    assert result.normalised == NATIONAL_ID


def test_a_born_abroad_code_is_accepted() -> None:
    assert validate_identifier("EG", "national_id", "30101018812342").passed


def test_a_future_birth_date_is_refused() -> None:
    assert validate_identifier("EG", "national_id", "39912310112342").reason == "birth_date"


def test_the_tax_registration_number_is_nine_digits_however_printed() -> None:
    assert validate_identifier("EG", "tax_registration", "123-456-789").passed
    assert validate_identifier("EG", "tax_registration", "١٢٣٤٥٦٧٨٩").normalised == "123456789"
    assert validate_identifier("EG", "tax_registration", "12345678").reason == "format"


def test_the_commercial_register_number_has_no_national_shape_and_is_kept_lenient() -> None:
    assert validate_identifier("EG", "company_register", "54321").passed
    assert not validate_identifier("EG", "company_register", "ABC").passed
    assert rule_for("EG", "company_register").confidence == "L"


def test_a_country_or_kind_with_no_row_is_not_judged() -> None:
    result = validate_identifier("FR", "national_id", "whatever")
    assert result.passed
    assert result.rule is None


def test_the_subcontractor_tax_check_reads_the_same_row() -> None:
    result = validate_tax_id("EG", "123-456-789")
    assert result.format_valid
    assert result.standard == "EG RIN"
    assert not validate_tax_id("EG", "1234").format_valid
    assert canonical_tax_id("EG", "١٢٣-٤٥٦-٧٨٩") == canonical_tax_id("EG", "123456789")


def test_arabic_indic_digits_are_digits_for_every_tax_number() -> None:
    assert validate_tax_id("DE", "١٢٣٤٥٦٧٨٩").tax_id_normalised == "123456789"


@pytest.mark.parametrize(
    ("number", "e164"),
    [
        ("010 1234 5678", "+201012345678"),
        ("+20 11 2345 6789", "+201123456789"),
        ("0122 345 6789", "+201223456789"),
        ("015 1234 5678", "+201512345678"),
        ("02 2345 6789", "+20223456789"),
        ("03 456 7890", "+2034567890"),
        ("٠١٠١٢٣٤٥٦٧٨", "+201012345678"),
    ],
)
def test_egyptian_numbers_are_normalised(number: str, e164: str) -> None:
    result = validate_phone(number, "EG")
    assert result.passed, result.error_message
    assert result.e164 == e164
    assert result.jurisdiction.answered


def test_a_mobile_length_number_on_an_unknown_prefix_is_refused() -> None:
    assert not validate_phone("013 1234 5678", "EG").passed
    assert not validate_phone("+20 13 1234 5678", "EG").passed


@pytest.mark.parametrize("postcode", ["11511", "3759914"])
def test_both_postcode_lengths_in_use_are_accepted(postcode: str) -> None:
    result = validate_address({"street": "26 July St", "city": "Cairo", "postcode": postcode, "country": "EG"}, "EG")
    assert result.passed, result.errors


def test_a_six_digit_postcode_is_refused() -> None:
    result = validate_address({"street": "26 July St", "city": "Cairo", "postcode": "115111", "country": "EG"}, "EG")
    assert not result.passed
