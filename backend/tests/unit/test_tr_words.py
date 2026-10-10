"""Unit tests for Turkish amounts in words.

Three kinds of evidence, because a speller can be wrong in three ways. The
vocabulary is pinned by literals written out by hand. The grammar ("bin" and
"yüz" without "bir", the larger scales with it) is pinned by literals too.
And the mechanics over the whole range are pinned by reading the words back
with a small parser written independently in this file: every number from 0
to 1999, the powers of ten, the boundaries of each scale and a few thousand
random values up to the limit.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.modules.einvoice.tr_words import (
    CURRENCY_WORDS,
    NUMBER_LIMIT,
    CurrencyWords,
    amount_in_words,
    number_in_words,
    number_words,
)

# ── vocabulary, by hand ──────────────────────────────────────────────────────

SPELLED = {
    0: "Sıfır",
    1: "Bir",
    2: "İki",
    3: "Üç",
    4: "Dört",
    5: "Beş",
    6: "Altı",
    7: "Yedi",
    8: "Sekiz",
    9: "Dokuz",
    10: "On",
    11: "On Bir",
    12: "On İki",
    19: "On Dokuz",
    20: "Yirmi",
    30: "Otuz",
    40: "Kırk",
    50: "Elli",
    60: "Altmış",
    70: "Yetmiş",
    80: "Seksen",
    90: "Doksan",
    99: "Doksan Dokuz",
    100: "Yüz",
    101: "Yüz Bir",
    110: "Yüz On",
    111: "Yüz On Bir",
    200: "İki Yüz",
    999: "Dokuz Yüz Doksan Dokuz",
    1000: "Bin",
    1001: "Bin Bir",
    1100: "Bin Yüz",
    1234: "Bin İki Yüz Otuz Dört",
    2000: "İki Bin",
    10000: "On Bin",
    11000: "On Bir Bin",
    21000: "Yirmi Bir Bin",
    100000: "Yüz Bin",
    101000: "Yüz Bir Bin",
    1000000: "Bir Milyon",
    1001000: "Bir Milyon Bin",
    1001001: "Bir Milyon Bin Bir",
    2000000: "İki Milyon",
    1000000000: "Bir Milyar",
    1000000000000: "Bir Trilyon",
    1000000000000000: "Bir Katrilyon",
    1234567890123456: (
        "Bir Katrilyon İki Yüz Otuz Dört Trilyon Beş Yüz Altmış Yedi Milyar Sekiz Yüz Doksan Milyon "
        "Yüz Yirmi Üç Bin Dört Yüz Elli Altı"
    ),
}


@pytest.mark.parametrize(("value", "words"), sorted(SPELLED.items()))
def test_spelling_by_hand(value: int, words: str) -> None:
    assert number_in_words(value, joined=False) == words
    assert number_in_words(value) == words.replace(" ", "")


def test_one_thousand_is_bin_and_one_million_is_bir_milyon() -> None:
    assert number_in_words(1000, joined=False) == "Bin"
    assert number_in_words(1000000, joined=False) == "Bir Milyon"
    assert number_in_words(1000000000, joined=False) == "Bir Milyar"
    # "Bir" is dropped only when the thousands group is exactly one.
    assert number_in_words(1001000, joined=False) == "Bir Milyon Bin"
    assert number_in_words(101000, joined=False) == "Yüz Bir Bin"
    assert number_in_words(1000100, joined=False) == "Bir Milyon Yüz"


def test_turkish_dotted_capital_is_written_and_never_derived() -> None:
    # ``"iki".capitalize()`` gives "Iki" in Python. The word list is stored
    # capitalised so that this cannot happen.
    for value in (2, 12, 20, 22, 2000, 2002, 222222):
        text = number_in_words(value, joined=False)
        assert "İki" in text or "Yirmi" in text
        assert "Iki" not in text
    assert "İki" in number_in_words(2)


# ── an independent reader ────────────────────────────────────────────────────

_READ_UNITS = {"Bir": 1, "İki": 2, "Üç": 3, "Dört": 4, "Beş": 5, "Altı": 6, "Yedi": 7, "Sekiz": 8, "Dokuz": 9}
_READ_TENS = {
    "On": 10,
    "Yirmi": 20,
    "Otuz": 30,
    "Kırk": 40,
    "Elli": 50,
    "Altmış": 60,
    "Yetmiş": 70,
    "Seksen": 80,
    "Doksan": 90,
}
_READ_SCALES = {"Bin": 10**3, "Milyon": 10**6, "Milyar": 10**9, "Trilyon": 10**12, "Katrilyon": 10**15}


def read_back(words: str) -> int:
    """Turn spaced Turkish number words back into an integer, strictly.

    Rejects anything a correct speller would not write: a unit after a unit,
    "Bir Yüz", "Bir Bin" at the head of the thousands group, scales out of
    descending order.
    """
    if words == "Sıfır":
        return 0
    total = 0
    group = 0
    group_tokens: list[str] = []
    last_scale = 10**18
    for token in words.split(" "):
        if token in _READ_UNITS:
            assert group % 10 == 0, words
            group += _READ_UNITS[token]
        elif token in _READ_TENS:
            assert group % 100 == 0, words
            group += _READ_TENS[token]
        elif token == "Yüz":
            assert group < 10, words
            assert group_tokens != ["Bir"], f"'Bir Yüz' in {words!r}"
            group = (group or 1) * 100
        elif token in _READ_SCALES:
            scale = _READ_SCALES[token]
            assert scale < last_scale, words
            last_scale = scale
            if scale == 1000:
                assert group_tokens != ["Bir"], f"'Bir Bin' in {words!r}"
                group = group or 1
            else:
                assert group > 0, words
            total += group * scale
            group = 0
            group_tokens = []
            continue
        else:
            raise AssertionError(f"unknown word {token!r} in {words!r}")
        group_tokens.append(token)
    return total + group


def test_reader_rejects_the_classic_mistakes() -> None:
    """The control: the reader is strict enough to be worth trusting."""
    for wrong in ("Bir Bin", "Bir Yüz", "Bin Milyon Bir Bin", "İki Üç", "Yüz Bin Milyon", "Milyon"):
        with pytest.raises(AssertionError):
            read_back(wrong)


def test_every_number_up_to_1999_reads_back() -> None:
    for value in range(2000):
        spaced = number_in_words(value, joined=False)
        assert read_back(spaced) == value, spaced
        assert number_in_words(value) == spaced.replace(" ", "")


def test_powers_of_ten_and_scale_boundaries_read_back() -> None:
    values = set()
    for exponent in range(18):
        power = 10**exponent
        values |= {power - 1, power, power + 1, 2 * power, 9 * power, 11 * power}
    values |= {NUMBER_LIMIT - 1, 999999, 1000000, 999999999999, 10**15, 10**15 + 1, 123456789012345678}
    for value in sorted(v for v in values if 0 <= v < NUMBER_LIMIT):
        assert read_back(number_in_words(value, joined=False)) == value, value


def test_random_numbers_read_back() -> None:
    rng = random.Random(20261010)
    for _ in range(4000):
        value = rng.randrange(10 ** rng.randrange(1, 19))
        assert read_back(number_in_words(value, joined=False)) == value, value


def test_number_words_limits() -> None:
    assert number_words(NUMBER_LIMIT - 1)[0] == "Dokuz"
    with pytest.raises(ValueError, match="beyond"):
        number_words(NUMBER_LIMIT)
    with pytest.raises(ValueError, match="non-negative"):
        number_words(-1)
    assert number_in_words(-1234, joined=False) == "Eksi Bin İki Yüz Otuz Dört"
    assert number_in_words(-1234) == "Eksi BinİkiYüzOtuzDört"


# ── amounts ──────────────────────────────────────────────────────────────────


def test_the_invoice_form() -> None:
    assert amount_in_words(Decimal("1234.56"), "TRY") == "Yalnız BinİkiYüzOtuzDört Türk Lirası ElliAltı Kuruş"


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("112000.00", "TRY", "Yalnız YüzOnİkiBin Türk Lirası"),
        ("0.05", "TRY", "Yalnız Sıfır Türk Lirası Beş Kuruş"),
        ("0.50", "TRY", "Yalnız Sıfır Türk Lirası Elli Kuruş"),
        ("1.01", "TRY", "Yalnız Bir Türk Lirası Bir Kuruş"),
        ("1000000.99", "TRY", "Yalnız BirMilyon Türk Lirası DoksanDokuz Kuruş"),
        ("4441.20", "EUR", "Yalnız DörtBinDörtYüzKırkBir Euro Yirmi Sent"),
        ("250", "USD", "Yalnız İkiYüzElli ABD Doları"),
        ("19.99", "GBP", "Yalnız OnDokuz İngiliz Sterlini DoksanDokuz Peni"),
        ("1000000000000000", "TRY", "Yalnız BirKatrilyon Türk Lirası"),
    ],
)
def test_amounts_in_the_everyday_currencies(amount: str, currency: str, expected: str) -> None:
    assert amount_in_words(Decimal(amount), currency) == expected


def test_zero_and_zero_subunit() -> None:
    assert amount_in_words(Decimal("0"), "TRY") == "Yalnız Sıfır Türk Lirası"
    assert amount_in_words(Decimal("0.00"), "TRY", zero_minor=True) == "Yalnız Sıfır Türk Lirası Sıfır Kuruş"
    assert amount_in_words(Decimal("1000"), "TRY") == "Yalnız Bin Türk Lirası"
    assert amount_in_words(Decimal("1000"), "TRY", zero_minor=True) == "Yalnız Bin Türk Lirası Sıfır Kuruş"


def test_spaced_form_and_prefix_are_parameters() -> None:
    assert (
        amount_in_words(Decimal("1234.56"), "TRY", joined=False)
        == "Yalnız Bin İki Yüz Otuz Dört Türk Lirası Elli Altı Kuruş"
    )
    assert amount_in_words(Decimal("1234.56"), "TRY", prefix="") == "BinİkiYüzOtuzDört Türk Lirası ElliAltı Kuruş"


def test_currency_without_a_subunit() -> None:
    assert amount_in_words(Decimal("1999"), "JPY") == "Yalnız BinDokuzYüzDoksanDokuz Japon Yeni"
    # Rounded to the yen, half up, before it is spelled.
    assert amount_in_words(Decimal("1999.5"), "JPY") == "Yalnız İkiBin Japon Yeni"
    # ``zero_minor`` has nothing to print for a currency with no subunit.
    assert amount_in_words(Decimal("5"), "JPY", zero_minor=True) == "Yalnız Beş Japon Yeni"


def test_currency_with_three_subunit_digits() -> None:
    assert amount_in_words(Decimal("2.005"), "KWD") == "Yalnız İki Kuveyt Dinarı Beş Fils"
    assert amount_in_words(Decimal("1.250"), "KWD") == "Yalnız Bir Kuveyt Dinarı İkiYüzElli Fils"
    assert amount_in_words(Decimal("0.999"), "KWD") == "Yalnız Sıfır Kuveyt Dinarı DokuzYüzDoksanDokuz Fils"


def test_rounding_is_half_up_to_the_subunit() -> None:
    assert amount_in_words(Decimal("0.005"), "TRY") == "Yalnız Sıfır Türk Lirası Bir Kuruş"
    assert amount_in_words(Decimal("0.004"), "TRY") == "Yalnız Sıfır Türk Lirası"
    assert amount_in_words(Decimal("9.995"), "TRY") == "Yalnız On Türk Lirası"
    assert amount_in_words(Decimal("1234.555"), "TRY") == "Yalnız BinİkiYüzOtuzDört Türk Lirası ElliAltı Kuruş"


def test_negative_amounts() -> None:
    assert amount_in_words(Decimal("-12.50"), "USD") == "Yalnız Eksi Onİki ABD Doları Elli Sent"
    assert amount_in_words(Decimal("-0.01"), "TRY") == "Yalnız Eksi Sıfır Türk Lirası Bir Kuruş"
    # An amount that rounds to nothing is not "minus zero".
    assert amount_in_words(Decimal("-0.004"), "TRY") == "Yalnız Sıfır Türk Lirası"


def test_unknown_currency_is_refused_rather_than_invented() -> None:
    with pytest.raises(ValueError, match="no Turkish currency name"):
        amount_in_words(Decimal("10"), "SEK")
    names = CurrencyWords("İsveç Kronu", "Öre")
    assert amount_in_words(Decimal("10.25"), "SEK", names=names) == "Yalnız On İsveç Kronu YirmiBeş Öre"
    # A subunit that has to be printed needs a name.
    with pytest.raises(ValueError, match="subunit"):
        amount_in_words(Decimal("10.25"), "SEK", names=CurrencyWords("İsveç Kronu"))


def test_currency_code_is_normalised() -> None:
    assert amount_in_words(Decimal("1"), " try ") == "Yalnız Bir Türk Lirası"
    assert set(CURRENCY_WORDS) >= {"TRY", "EUR", "USD", "GBP"}


def test_amount_too_large_is_refused() -> None:
    with pytest.raises(ValueError, match="beyond"):
        amount_in_words(Decimal(NUMBER_LIMIT), "TRY")
    assert amount_in_words(Decimal(NUMBER_LIMIT - 1), "TRY").endswith("Türk Lirası")


def test_amount_words_agree_with_the_figure_over_a_sample() -> None:
    """Split the sentence back into lira and kuruş with the independent reader."""
    rng = random.Random(7)
    for _ in range(1500):
        kurus = rng.randrange(10 ** rng.randrange(1, 15))
        amount = Decimal(kurus) / 100
        sentence = amount_in_words(amount, "TRY", joined=False, zero_minor=True)
        assert sentence.startswith("Yalnız ")
        assert sentence.endswith(" Kuruş")
        major_words, minor_words = sentence[len("Yalnız ") : -len(" Kuruş")].split(" Türk Lirası ")
        assert read_back(major_words) * 100 + read_back(minor_words) == kurus
