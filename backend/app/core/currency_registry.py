# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The currency table, the decimals each currency keeps, and how an amount is written.

This is the dependency-free half of :mod:`app.core.money`. It exists as its own
module for one reason: two validator modules in this platform declare themselves
standard-library-only in their docstrings and mean it, and :mod:`app.core.money`
imports pydantic and SQLAlchemy at module level. Before this split those modules
could not ask how many decimals a currency has, so they wrote amounts with a
hardcoded two, which is wrong for every currency that has no subunit and for the
Gulf dinars that have three. The alternative -- letting them spell the format out
locally -- is how two findings on one screen end up disagreeing about what an
amount looks like.

So the rule is: **nothing here may import anything outside the standard library**,
and a test asserts that in a fresh interpreter rather than trusting this
paragraph. A contract that lives only in a docstring is one careless import away
from being untrue.

:mod:`app.core.money` re-exports everything below, so ``from app.core.money import
minor_units`` keeps working and no caller had to change.

Do not confuse :func:`sentence_amount` with :func:`app.core.money.format_money`.
They format money for different readers and are not interchangeable:

====================  ==========================  =============================
                      :func:`sentence_amount`     ``money.format_money``
====================  ==========================  =============================
Output                ``1,234.50 EUR``            ``€ 1,234.56``
Names the currency    ISO code, after the digits  symbol, and locale-placed
Locale                none, one spelling          ``en`` and ``de`` variants
For                   a sentence a rule writes    a field on a screen or document
====================  ==========================  =============================
"""

# Copyright 2024-2026 OpenEstimate Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from decimal import Decimal
from typing import Any

__all__ = [
    "CURRENCIES",
    "minor_units",
    "money_quantum",
    "sentence_amount",
]

# ── Currency registry ─────────────────────────────────────────────────────────

CURRENCIES: dict[str, dict[str, Any]] = {
    # Europe
    "EUR": {"symbol": "€", "name": "Euro", "decimals": 2},
    "GBP": {"symbol": "£", "name": "British Pound", "decimals": 2},
    "CHF": {"symbol": "CHF", "name": "Swiss Franc", "decimals": 2},
    "SEK": {"symbol": "kr", "name": "Swedish Krona", "decimals": 2},
    "NOK": {"symbol": "kr", "name": "Norwegian Krone", "decimals": 2},
    "DKK": {"symbol": "kr", "name": "Danish Krone", "decimals": 2},
    "PLN": {"symbol": "zł", "name": "Polish Zloty", "decimals": 2},
    "CZK": {"symbol": "Kč", "name": "Czech Koruna", "decimals": 2},
    "HUF": {"symbol": "Ft", "name": "Hungarian Forint", "decimals": 0},
    "RON": {"symbol": "lei", "name": "Romanian Leu", "decimals": 2},
    "BGN": {"symbol": "лв", "name": "Bulgarian Lev", "decimals": 2},
    "HRK": {"symbol": "kn", "name": "Croatian Kuna", "decimals": 2},
    "TRY": {"symbol": "₺", "name": "Turkish Lira", "decimals": 2},
    "RUB": {"symbol": "₽", "name": "Russian Ruble", "decimals": 2},
    "UAH": {"symbol": "₴", "name": "Ukrainian Hryvnia", "decimals": 2},
    # Americas
    "USD": {"symbol": "$", "name": "US Dollar", "decimals": 2},
    "CAD": {"symbol": "C$", "name": "Canadian Dollar", "decimals": 2},
    "MXN": {"symbol": "MX$", "name": "Mexican Peso", "decimals": 2},
    "BRL": {"symbol": "R$", "name": "Brazilian Real", "decimals": 2},
    "ARS": {"symbol": "$", "name": "Argentine Peso", "decimals": 2},
    "CLP": {"symbol": "$", "name": "Chilean Peso", "decimals": 0},
    "COP": {"symbol": "$", "name": "Colombian Peso", "decimals": 2},
    "PEN": {"symbol": "S/.", "name": "Peruvian Sol", "decimals": 2},
    "UYU": {"symbol": "$U", "name": "Uruguayan Peso", "decimals": 2},
    "BOB": {"symbol": "Bs.", "name": "Bolivian Boliviano", "decimals": 2},
    "PYG": {"symbol": "₲", "name": "Paraguayan Guaraní", "decimals": 0},
    "VES": {"symbol": "Bs.S", "name": "Venezuelan Bolívar", "decimals": 2},
    "DOP": {"symbol": "RD$", "name": "Dominican Peso", "decimals": 2},
    "GTQ": {"symbol": "Q", "name": "Guatemalan Quetzal", "decimals": 2},
    "CRC": {"symbol": "₡", "name": "Costa Rican Colón", "decimals": 2},
    # Middle East & Africa
    "AED": {"symbol": "د.إ", "name": "UAE Dirham", "decimals": 2},
    "SAR": {"symbol": "﷼", "name": "Saudi Riyal", "decimals": 2},
    "QAR": {"symbol": "﷼", "name": "Qatari Riyal", "decimals": 2},
    # Audit I1 - three-decimal Gulf/oil-trading currencies. Adding them
    # explicitly means ``format_money`` and ``MoneyValue.convert`` quantise
    # to the correct fils/dirhams instead of rounding to 2 decimals.
    "KWD": {"symbol": "د.ك", "name": "Kuwaiti Dinar", "decimals": 3},
    "BHD": {"symbol": "ب.د", "name": "Bahraini Dinar", "decimals": 3},
    "OMR": {"symbol": "ر.ع.", "name": "Omani Rial", "decimals": 3},
    "JOD": {"symbol": "د.أ", "name": "Jordanian Dinar", "decimals": 3},
    "IQD": {"symbol": "ع.د", "name": "Iraqi Dinar", "decimals": 3},
    "LYD": {"symbol": "ل.د", "name": "Libyan Dinar", "decimals": 3},
    "VND": {"symbol": "₫", "name": "Vietnamese Đồng", "decimals": 0},
    "ISK": {"symbol": "kr", "name": "Icelandic Króna", "decimals": 0},
    "BIF": {"symbol": "FBu", "name": "Burundian Franc", "decimals": 0},
    "DJF": {"symbol": "Fdj", "name": "Djiboutian Franc", "decimals": 0},
    "GNF": {"symbol": "FG", "name": "Guinean Franc", "decimals": 0},
    "KMF": {"symbol": "CF", "name": "Comorian Franc", "decimals": 0},
    "VUV": {"symbol": "VT", "name": "Vanuatu Vatu", "decimals": 0},
    "XPF": {"symbol": "₣", "name": "CFP Franc", "decimals": 0},
    "ZAR": {"symbol": "R", "name": "South African Rand", "decimals": 2},
    "EGP": {"symbol": "E£", "name": "Egyptian Pound", "decimals": 2},
    "NGN": {"symbol": "₦", "name": "Nigerian Naira", "decimals": 2},
    "KES": {"symbol": "KSh", "name": "Kenyan Shilling", "decimals": 2},
    "GHS": {"symbol": "₵", "name": "Ghanaian Cedi", "decimals": 2},
    "MAD": {"symbol": "DH", "name": "Moroccan Dirham", "decimals": 2},
    "TND": {"symbol": "د.ت", "name": "Tunisian Dinar", "decimals": 3},
    "DZD": {"symbol": "DA", "name": "Algerian Dinar", "decimals": 2},
    "ETB": {"symbol": "Br", "name": "Ethiopian Birr", "decimals": 2},
    "UGX": {"symbol": "USh", "name": "Ugandan Shilling", "decimals": 0},
    "TZS": {"symbol": "TSh", "name": "Tanzanian Shilling", "decimals": 2},
    "RWF": {"symbol": "FRw", "name": "Rwandan Franc", "decimals": 0},
    "XOF": {"symbol": "CFA", "name": "West African CFA Franc", "decimals": 0},
    "XAF": {"symbol": "FCFA", "name": "Central African CFA Franc", "decimals": 0},
    "AOA": {"symbol": "Kz", "name": "Angolan Kwanza", "decimals": 2},
    "MZN": {"symbol": "MT", "name": "Mozambique Metical", "decimals": 2},
    "BWP": {"symbol": "P", "name": "Botswana Pula", "decimals": 2},
    "ZMW": {"symbol": "ZK", "name": "Zambian Kwacha", "decimals": 2},
    "NAD": {"symbol": "N$", "name": "Namibia Dollar", "decimals": 2},
    "MGA": {"symbol": "Ar", "name": "Malagasy Ariary", "decimals": 2},
    # Asia-Pacific
    "JPY": {"symbol": "¥", "name": "Japanese Yen", "decimals": 0},
    "CNY": {"symbol": "¥", "name": "Chinese Yuan", "decimals": 2},
    "KRW": {"symbol": "₩", "name": "South Korean Won", "decimals": 0},
    "INR": {"symbol": "₹", "name": "Indian Rupee", "decimals": 2},
    "AUD": {"symbol": "A$", "name": "Australian Dollar", "decimals": 2},
    "NZD": {"symbol": "NZ$", "name": "New Zealand Dollar", "decimals": 2},
    "SGD": {"symbol": "S$", "name": "Singapore Dollar", "decimals": 2},
    "HKD": {"symbol": "HK$", "name": "Hong Kong Dollar", "decimals": 2},
    "MYR": {"symbol": "RM", "name": "Malaysian Ringgit", "decimals": 2},
    "THB": {"symbol": "฿", "name": "Thai Baht", "decimals": 2},
    "IDR": {"symbol": "Rp", "name": "Indonesian Rupiah", "decimals": 0},
    "PHP": {"symbol": "₱", "name": "Philippine Peso", "decimals": 2},
}

#: What an unknown code is worth. Two is the commonest subdivision by a wide
#: margin, so it is the least wrong guess for a code nobody has entered yet.
_DEFAULT_MINOR_UNITS = 2


# ── Minor units: three layers, one source ─────────────────────────────────────
#
# How many decimal places a monetary amount carries is asked three times in this
# platform, by three layers that want three different answers. They are listed
# here because the whole subject collapses into a display bug the moment a
# reader forgets that the layers are not interchangeable.
#
#   value     THIS module. The amount itself, as it is computed, converted,
#             stored and put on the wire. Rounding here does not change how a
#             number looks, it changes what the number IS: a quantum coarser
#             than the currency's own subdivision destroys precision that no
#             later layer can recover, and totals summed from components
#             rounded here stop matching totals summed from unrounded ones.
#             So this layer follows the currency's real subdivision and nothing
#             else. Everything that rounds a value asks :func:`money_quantum`,
#             and no rounding step in this platform is allowed to be a literal
#             that ignores its currency.
#
#   document  ``app.modules.einvoice.rules.money_decimals``. What an invoice
#             declares to a bank and a tax authority. It starts from the value
#             layer's answer and caps it at the two decimals the EN 16931
#             BR-DEC family permits for document amounts, which is why a Kuwaiti
#             dinar is written with three digits in our own records and two on
#             an invoice.
#
#   screen    ``frontend/src/shared/lib/money.ts``. What a person reads. It
#             asks the running engine's CLDR data, because a screen follows the
#             conventions of whoever is looking at it. It never reads this
#             table and this table never reads it.
#
# The registry above is ISO 4217. ISO states how a currency is subdivided; CLDR
# states how a person in a locale writes it, and the two part company on
# fourteen codes (enumerated, with their ISO values and the reasoning, in
# ``app.modules.einvoice.rules``). Where they disagree the value layer keeps
# ISO's count, because a subunit that exists can appear in a payment whatever
# local habit does with it.
#
# There are exactly two exceptions, HUF and IDR, and they are exceptions to the
# rule rather than to the reasoning. ISO still lists a minor unit for both, but
# the fillér left circulation in 1999 and the sen with it, so there is no
# subunit for a second digit to mean and no payment that could carry one. Two
# decimals there would not be a finer forint, only a pair of digits nothing can
# settle. That is a decision, recorded here and beside the same two codes in the
# einvoice rules, not a copy of CLDR that happens to agree.
#
# If you arrived here because a currency looked wrong on a screen: the screen is
# the layer that does not read this file. Changing a count here to fix how
# something renders moves a stored amount and an invoice total with it.


def minor_units(currency_code: str | None) -> int:
    """How many decimal places an amount in ``currency_code`` genuinely has.

    The value-layer answer, and the one every rounding step in the platform is
    derived from. This is the currency's own subdivision, uncapped: a Kuwaiti
    dinar returns 3 here even though a document may only write 2.

    Args:
        currency_code: ISO 4217 code. Case and surrounding space are ignored;
            blank, ``None`` and codes absent from the registry yield the
            two-decimal default.

    Returns:
        The number of minor-unit digits, ``0`` for a currency with no subunit.
    """
    entry = CURRENCIES.get((currency_code or "").strip().upper())
    if entry is None:
        return _DEFAULT_MINOR_UNITS
    return int(entry.get("decimals", _DEFAULT_MINOR_UNITS))


def money_quantum(currency_code: str | None) -> Decimal:
    """The rounding step for one amount in ``currency_code``.

    ``Decimal("0.01")`` for a two-decimal currency, ``Decimal("1")`` for one
    with no subunit, ``Decimal("0.001")`` for the Gulf dinars. Pass this to
    :meth:`decimal.Decimal.quantize` instead of writing a literal: a literal
    cannot know its currency, and that is how a yen acquires sub-yen precision
    it cannot express and a dinar loses a fils it can.

    Args:
        currency_code: ISO 4217 code, normalised as in :func:`minor_units`.

    Returns:
        The quantum, exact and free of scientific notation.
    """
    return Decimal(1).scaleb(-minor_units(currency_code))


# ── Writing an amount into a sentence ─────────────────────────────────────────


def sentence_amount(value: float | Decimal, currency: str, decimals: int | None = None) -> str:
    """Render ``value`` the way a message shown to a person should carry it.

    One spelling, used by every rule in the platform that puts an amount into a
    sentence, so that two findings on one screen cannot disagree about what an
    amount looks like. It does three things a bare interpolation does not:
    thousands separators, so a seven-digit figure can be read at a glance; the
    decimals the currency genuinely has, asked of :func:`minor_units` rather than
    assumed to be two; and the currency code, so the number is an amount of
    something.

    The code is taken from the caller, never defaulted. Callers pass the code off
    the record in hand and pass ``""`` when the record states none: a guessed code
    reads as authoritative and is worse than no code at all, because a reader who
    trusts it reconciles the wrong ledger.

    Args:
        value: The amount. ``float`` is accepted alongside ``Decimal`` because
            some callers hold a computed ratio rather than a stored amount;
            a Decimal *string* is not accepted and must be parsed by the caller,
            since silently formatting text would hide a payload that lost its
            type.
        currency: ISO 4217 code, or ``""`` for an amount whose currency is not
            known. Blank yields grouped digits and no code.
        decimals: How many decimals to write, when the caller is on a layer that
            does not use the value count. Left ``None`` by almost everything, and
            passed only where the message describes a figure some other layer
            already fixed the precision of -- an invoice amount, which EN 16931
            caps at two even for a currency with three. The einvoice rules pass
            their own ``money_decimals`` for exactly that reason: the comparison
            that produced the finding was made at the document count, so writing
            the figures at the value count could show a reader two numbers that
            look equal under a sentence saying they differ. It is a parameter
            rather than a second function so that the grouping and the placement
            of the code stay in one place.

    Returns:
        ``"1,234.50 EUR"``, or ``"1,234.50"`` when ``currency`` is blank. A
        zero-decimal currency keeps no decimals at all: ``"1,234 JPY"``.
    """
    places = minor_units(currency) if decimals is None else decimals
    return f"{value:,.{places}f} {currency}".rstrip()
