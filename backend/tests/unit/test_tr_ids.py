"""Unit tests for the Turkish identifier checks (VKN, TCKN, document ID, UUID).

No number in this file belongs to a taxpayer that was looked up anywhere.
The valid ones are built from made-up stems by the implementation's own check
digit functions, and those functions are held to account three ways: by
vectors worked out by hand below, by an independent second implementation
written differently inside this file, and (outside the repository, on
2026-10-10) by the identifiers in GİB's official sample documents, of which
10 distinct VKN values and 2 TCKN values pass. Those sample values are not
repeated here because some of them are real registrations.
"""

from __future__ import annotations

import itertools
import random

import pytest

from app.modules.einvoice.tr_ids import (
    CHECK_DIGIT_REVIEW_STATUS,
    classify_tax_number,
    is_valid_document_id,
    is_valid_tax_number,
    is_valid_tckn,
    is_valid_uuid,
    is_valid_vkn,
    tckn_check_digits,
    vkn_check_digit,
)

# ── VKN ──────────────────────────────────────────────────────────────────────


def test_vkn_check_digit_worked_by_hand() -> None:
    """Stem 111222333, each step written out.

    position  digit  + (10 - pos)  last digit  x 2**(10 - pos)  mod 9 (0 reads 9)
        1       1        10            0             -                 0
        2       1         9            9         9 * 256 = 2304        9
        3       1         8            8         8 * 128 = 1024        7
        4       2         8            8         8 * 64  = 512         8
        5       2         7            7         7 * 32  = 224         8
        6       2         6            6         6 * 16  = 96          6
        7       3         6            6         6 * 8   = 48          3
        8       3         5            5         5 * 4   = 20          2
        9       3         4            4         4 * 2   = 8           8

    The results add up to 51, and 9 brings that to a multiple of ten.
    """
    assert sum((0, 9, 7, 8, 8, 6, 3, 2, 8)) == 51
    assert vkn_check_digit("111222333") == 9
    assert is_valid_vkn("1112223339")


def test_vkn_all_zero_stem() -> None:
    # Every step: 0 + (10 - pos) gives 9, 8, ... 1, never zero, so each
    # contributes (d * 2**d) mod 9: 9*512->9, 8*256->5, 7*128->5, 6*64->6,
    # 5*32->7, 4*16->1, 3*8->6, 2*4->8, 1*2->2. Sum 49, check digit 1.
    assert sum((9, 5, 5, 6, 7, 1, 6, 8, 2)) == 49
    assert vkn_check_digit("000000000") == 1


def _vkn_reference(first_nine: str) -> int:
    """A second implementation, written right to left with a running power of two."""
    total = 0
    power = 1
    for offset, char in enumerate(reversed(first_nine), start=1):
        power *= 2
        shifted = (int(char) + offset) % 10
        if shifted == 0:
            continue
        remainder = (shifted * power) % 9
        total += 9 if remainder == 0 else remainder
    return (10 - total) % 10


def test_vkn_agrees_with_an_independent_implementation() -> None:
    rng = random.Random(20261010)
    stems = [f"{rng.randrange(10**9):09d}" for _ in range(5000)]
    stems += ["000000000", "999999999", "123456789", "987654321", "100000000", "000000001"]
    for stem in stems:
        assert vkn_check_digit(stem) == _vkn_reference(stem), stem


def test_exactly_one_check_digit_validates_each_stem() -> None:
    for stem in ("111222333", "987654321", "500600700", "000000000"):
        valid = [d for d in range(10) if is_valid_vkn(f"{stem}{d}")]
        assert valid == [vkn_check_digit(stem)]


@pytest.mark.parametrize("value", ["1112223339", "9876543217", "5006007005", "1357924685"])
def test_synthetic_vkn_values_are_valid(value: str) -> None:
    assert is_valid_vkn(value)
    assert is_valid_tax_number(value)
    assert classify_tax_number(value) == "VKN"


@pytest.mark.parametrize(
    "value",
    [
        "1112223338",  # last digit off by one
        "1111111111",  # a filler GİB's own samples use; it fails the check
        "9999999999",
        "111222333",  # nine digits
        "11122233390",  # eleven digits is a TCKN shape, and not a valid one
        "111222333A",
        " 1112223339",
        "1112 223339",
        "TR1112223339",
        "",
        None,
    ],
)
def test_invalid_vkn_values(value: str | None) -> None:
    assert not is_valid_vkn(value)


def test_vkn_check_digit_needs_nine_digits() -> None:
    for bad in ("", "12345678", "1234567890", "12345678x"):
        with pytest.raises(ValueError, match="nine digits"):
            vkn_check_digit(bad)


# ── TCKN ─────────────────────────────────────────────────────────────────────


def test_tckn_check_digits_worked_by_hand() -> None:
    # Stem 100000001: odd positions 1+0+0+0+1 = 2, even positions 0.
    # Tenth: (7*2 - 0) mod 10 = 4. Eleventh: (1+1+4) mod 10 = 6.
    assert tckn_check_digits("100000001") == (4, 6)
    assert is_valid_tckn("10000000146")
    # Stem 123456789: odd 1+3+5+7+9 = 25, even 2+4+6+8 = 20.
    # Tenth: (175 - 20) mod 10 = 5. Eleventh: (45 + 5) mod 10 = 0.
    assert tckn_check_digits("123456789") == (5, 0)
    assert is_valid_tckn("12345678950")


def test_tckn_tenth_digit_is_not_negative_when_even_sum_dominates() -> None:
    # Stem 190909090: odd positions 1+0+0+0+0 = 1, even positions 9+9+9+9 = 36,
    # so 7 - 36 = -29 and the tenth digit is 1, never -9.
    assert tckn_check_digits("190909090") == (1, (1 + 36 + 1) % 10)


def _tckn_reference(first_nine: str) -> tuple[int, int]:
    """A second implementation: the equivalent "seven and nine" form.

    Subtracting the even sum is the same, modulo ten, as adding nine times it.
    """
    odd = sum(int(first_nine[i]) for i in (0, 2, 4, 6, 8))
    even = sum(int(first_nine[i]) for i in (1, 3, 5, 7))
    tenth = (odd * 7 + even * 9) % 10
    eleventh = (odd + even + tenth) % 10
    return tenth, eleventh


def test_tckn_agrees_with_an_independent_implementation() -> None:
    rng = random.Random(20261010)
    stems = [f"{rng.randrange(10**8, 10**9):09d}" for _ in range(5000)]
    stems += ["100000000", "999999999", "190909090", "909090909"]
    for stem in stems:
        assert tckn_check_digits(stem) == _tckn_reference(stem), stem


def test_exactly_one_pair_of_check_digits_validates_each_stem() -> None:
    for stem in ("100000001", "246813579"):
        valid = [(a, b) for a, b in itertools.product(range(10), repeat=2) if is_valid_tckn(f"{stem}{a}{b}")]
        assert valid == [tckn_check_digits(stem)]


@pytest.mark.parametrize("value", ["10000000146", "12345678950", "24681357994", "98765432150"])
def test_synthetic_tckn_values_are_valid(value: str) -> None:
    assert is_valid_tckn(value)
    assert is_valid_tax_number(value)
    assert classify_tax_number(value) == "TCKN"


@pytest.mark.parametrize(
    "value",
    [
        "10000000147",  # eleventh digit wrong
        "10000000156",  # tenth digit wrong
        "99999999999",  # a filler GİB's own samples use; it fails the check
        "1000000014",  # ten digits
        "100000001460",
        "1000000014x",
        "",
        None,
    ],
)
def test_invalid_tckn_values(value: str | None) -> None:
    assert not is_valid_tckn(value)


def test_tckn_cannot_start_with_zero() -> None:
    stem = "012345678"
    tenth, eleventh = tckn_check_digits(stem)
    assert not is_valid_tckn(f"{stem}{tenth}{eleventh}")


# ── classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("0000000000", "VKN"),  # shape only: the check digit is a separate question
        ("00000000000", "TCKN"),
        ("123456789", None),
        ("123456789012", None),
        ("12345 6789", None),
        ("١٢٣٤٥٦٧٨٩٠", None),  # ten digits in another script are not a VKN
        ("", None),
        (None, None),
    ],
)
def test_classify_tax_number_by_shape(value: str | None, kind: str | None) -> None:
    assert classify_tax_number(value) == kind


def test_check_digit_algorithms_are_flagged_as_unconfirmed() -> None:
    """No official text describes them; the flag must not be upgraded without one."""
    assert CHECK_DIGIT_REVIEW_STATUS == "unconfirmed"


# ── document ID and UUID ─────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["ABC2026000000001", "OMT2099123456789", "A1B2009000000000", "0002026000000001"])
def test_valid_document_ids(value: str) -> None:
    assert is_valid_document_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "abc2026000000001",  # lower case series
        "ABC1999000000001",  # the year must start with 20
        "ABC202600000001",  # fifteen characters
        "ABC20260000000011",  # seventeen
        "AB-2026000000001",
        "ABC2026 00000001",
        "ÖMT2026000000001",  # the series is ASCII letters and digits only
        "ABC2026000000001\n",
        "INV-2026-0042",
        "",
        None,
    ],
)
def test_invalid_document_ids(value: str | None) -> None:
    assert not is_valid_document_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "6f1c2d3e-4a5b-4c6d-8e7f-001122334455",
        "D8D9AE94-1069-4CC6-BDCF-AABA312FD299",
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_valid_uuids(value: str) -> None:
    assert is_valid_uuid(value)


@pytest.mark.parametrize(
    "value",
    [
        "6f1c2d3e4a5b4c6d8e7f001122334455",  # no hyphens
        "{6f1c2d3e-4a5b-4c6d-8e7f-001122334455}",
        "6f1c2d3e-4a5b-4c6d-8e7f-00112233445",
        "6f1c2d3e-4a5b-4c6d-8e7f-00112233445g",
        "urn:uuid:6f1c2d3e-4a5b-4c6d-8e7f-001122334455",
        "",
        None,
    ],
)
def test_invalid_uuids(value: str | None) -> None:
    assert not is_valid_uuid(value)
