# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Amounts written out in Turkish, the way an invoice prints its total.

A Turkish invoice repeats the amount to pay in words, by long standing
practice with the words run together and the line opened by "Yalnız", so that
nothing can be inserted in front of or between them::

    Yalnız BinİkiYüzOtuzDört Türk Lirası ElliAltı Kuruş

The layout is custom, not statute, and nothing in the official UBL-TR package
fixes it: the guides, the sample documents and the stylesheets GİB ships were
searched on 2026-10-10 and none of them contains a spelled amount. In an
e-Fatura the sentence travels as a free text ``cbc:Note``. So every part of the
layout is a parameter here (joined or spaced words, the opening word, whether a
zero subunit is printed, the currency names) and the defaults are the common
form above. The currency names in :data:`CURRENCY_WORDS` are the everyday
Turkish names, not a quotation from a legal text.

What is not a matter of taste is the spelling of the number, and that is
fixed here: "bin" and "yüz" stand alone where English says "one thousand" and
"one hundred" ("bir bin" is wrong), while a million, a milliard and upwards do
take "bir". Every word is stored already capitalised, because ``str.upper`` and
``str.capitalize`` turn a Turkish "i" into "I" where the language needs "İ".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.currency_registry import minor_units

_UNITS = ("", "Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi", "Sekiz", "Dokuz")
_TENS = ("", "On", "Yirmi", "Otuz", "Kırk", "Elli", "Altmış", "Yetmiş", "Seksen", "Doksan")
_HUNDRED = "Yüz"
_ZERO = "Sıfır"
_MINUS = "Eksi"
# Names of the powers of a thousand, lowest first. The empty first entry is
# the group of units. Five named scales reach 10**18 - 1.
_SCALES = ("", "Bin", "Milyon", "Milyar", "Trilyon", "Katrilyon")

#: One above the largest integer :func:`number_in_words` spells.
NUMBER_LIMIT = 10 ** (3 * len(_SCALES))


@dataclass(frozen=True)
class CurrencyWords:
    """The Turkish name of a currency and of its subunit.

    Attributes:
        major: name of the unit, e.g. ``"Türk Lirası"``.
        minor: name of the subunit, e.g. ``"Kuruş"``. Empty for a currency
            that has none.
    """

    major: str
    minor: str = ""


#: Names for the currencies a Turkish contractor invoices in, plus one currency
#: without a subunit and one with three subunit digits so that both shapes are
#: exercised. Anything else must be passed to :func:`amount_in_words` by the
#: caller: an invented name on a legal document is worse than a refusal.
CURRENCY_WORDS: Mapping[str, CurrencyWords] = {
    "TRY": CurrencyWords("Türk Lirası", "Kuruş"),
    "EUR": CurrencyWords("Euro", "Sent"),
    "USD": CurrencyWords("ABD Doları", "Sent"),
    "GBP": CurrencyWords("İngiliz Sterlini", "Peni"),
    "JPY": CurrencyWords("Japon Yeni"),
    "KWD": CurrencyWords("Kuveyt Dinarı", "Fils"),
}


def _group_words(value: int) -> list[str]:
    """Spell 1 to 999 as a list of words. "Yüz" stands alone for one hundred."""
    words: list[str] = []
    hundreds, rest = divmod(value, 100)
    if hundreds:
        if hundreds > 1:
            words.append(_UNITS[hundreds])
        words.append(_HUNDRED)
    tens, units = divmod(rest, 10)
    if tens:
        words.append(_TENS[tens])
    if units:
        words.append(_UNITS[units])
    return words


def number_words(value: int) -> list[str]:
    """Spell a non-negative integer as a list of capitalised Turkish words.

    Args:
        value: an integer from 0 up to, not including, :data:`NUMBER_LIMIT`.

    Returns:
        The words in reading order, e.g. ``["Bin", "İki", "Yüz"]`` for 1200.

    Raises:
        ValueError: when ``value`` is negative or too large to name.
    """
    if value < 0:
        raise ValueError("number_words spells non-negative integers; the sign belongs to the caller")
    if value >= NUMBER_LIMIT:
        raise ValueError(f"{value} is beyond the largest number this speller names")
    if value == 0:
        return [_ZERO]
    groups: list[int] = []
    while value:
        value, group = divmod(value, 1000)
        groups.append(group)
    words: list[str] = []
    for scale in range(len(groups) - 1, -1, -1):
        group = groups[scale]
        if not group:
            continue
        # One thousand is "Bin", never "Bir Bin". Every larger scale keeps its
        # "Bir": "Bir Milyon", "Bir Milyar".
        if not (scale == 1 and group == 1):
            words.extend(_group_words(group))
        if scale:
            words.append(_SCALES[scale])
    return words


def number_in_words(value: int, *, joined: bool = True) -> str:
    """Spell an integer in Turkish.

    Args:
        value: any integer whose magnitude is below :data:`NUMBER_LIMIT`.
        joined: run the words together (the invoice convention) or separate
            them with single spaces.

    Returns:
        ``"BinİkiYüzOtuzDört"`` or ``"Bin İki Yüz Otuz Dört"`` for 1234. A
        negative number is preceded by the separate word "Eksi".
    """
    text = ("" if joined else " ").join(number_words(abs(value)))
    return f"{_MINUS} {text}" if value < 0 else text


def amount_in_words(
    amount: Decimal,
    currency: str,
    *,
    joined: bool = True,
    prefix: str = "Yalnız",
    zero_minor: bool = False,
    names: CurrencyWords | None = None,
) -> str:
    """Write a money amount in Turkish words for the note line of an invoice.

    The amount is first rounded half up to the number of subunit digits the
    currency has (two for the lira, none for the yen, three for the dinar), so
    the words always agree with the figure printed beside them.

    Args:
        amount: the amount, positive, zero or negative.
        currency: ISO 4217 code. Decides the subunit digits and, unless
            ``names`` is given, the names.
        joined: run the words of each number together.
        prefix: the opening word. Pass an empty string to omit it.
        zero_minor: print a zero subunit ("Sıfır Kuruş") instead of leaving
            the subunit out when it is zero.
        names: currency names to use instead of :data:`CURRENCY_WORDS`.

    Returns:
        For ``Decimal("1234.56")`` in TRY:
        ``"Yalnız BinİkiYüzOtuzDört Türk Lirası ElliAltı Kuruş"``.

    Raises:
        ValueError: when the currency has no entry in :data:`CURRENCY_WORDS`
            and no ``names`` were given, when a subunit has to be printed and
            its name is empty, or when the amount is too large to name.
    """
    code = (currency or "").strip().upper()
    words = names or CURRENCY_WORDS.get(code)
    if words is None:
        raise ValueError(f"no Turkish currency name is known for {currency!r}; pass names=CurrencyWords(...)")
    places = minor_units(code)
    scaled = (abs(amount) * (Decimal(10) ** places)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    major, minor = divmod(int(scaled), 10**places)
    negative = amount < 0 and scaled != 0

    parts: list[str] = []
    if prefix:
        parts.append(prefix)
    if negative:
        parts.append(_MINUS)
    parts.append(number_in_words(major, joined=joined))
    parts.append(words.major)
    if places and (minor or zero_minor):
        if not words.minor:
            raise ValueError(f"the subunit of {code} has to be printed and no name for it was given")
        parts.append(number_in_words(minor, joined=joined))
        parts.append(words.minor)
    return " ".join(parts)
