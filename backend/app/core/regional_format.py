# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How a country writes a number and a date on a generated document.

The question this answers
-------------------------
A PDF is printed for the market the project is in, not for whoever pressed the
button, so its separators and its date order belong to the project's country.
The BOQ generator used to decide them from the currency alone, and a currency
is a weak proxy for a country: the euro is written ``1.234,56`` in Germany,
``1 234,56`` in France and ``1,234.56`` in Ireland, so every Irish bill came
out in German style. A hryvnia had no entry at all and came out American.

So the country decides first, read from :data:`app.core.i18n_data.COUNTRY_DEFAULTS`,
which carries a display pattern and a date order per country. The currency is
the fallback for a project with no country, and that fallback is exactly the
table the BOQ generator used before, so a document with no country prints
byte for byte as it did.

Decimals are not decided here. How many digits an amount carries is a property
of the currency (a yen has none), and how many a quantity carries is the
caller's choice; this module only says which characters separate them.

Two characters worth naming
---------------------------
* The space a spaced style groups with is U+00A0, a no-break space, so a
  right-aligned amount in a narrow table cell is never broken between its
  thousands. Both bundled faces and the PDF base fonts carry the glyph.
* The Swiss group separator is U+0027, the ASCII apostrophe. That is what
  CLDR 48 gives ``de-CH``, ``fr-CH`` and ``it-CH`` alike (measured on ICU
  78.3, where ``Intl.NumberFormat("de-CH")`` writes ``1'234'567.89``), so the
  PDF agrees with the amount the browser shows on screen. The typographic
  U+2019 that older CLDR releases printed is still read as a Swiss pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

from app.core.i18n_data import COUNTRY_DEFAULTS

NBSP: Final = " "
SWISS_APOSTROPHE: Final = "'"
TYPOGRAPHIC_APOSTROPHE: Final = "\u2019"


@dataclass(frozen=True)
class NumberStyle:
    """The two separators a market writes a number with.

    Attributes:
        group: Between groups of thousands.
        decimal: Between the whole part and the fraction.
        indian_grouping: Group the whole part as lakh and crore
            (``12,34,567``) rather than by threes.
    """

    group: str
    decimal: str
    indian_grouping: bool = False


ANGLO: Final = NumberStyle(group=",", decimal=".")
CONTINENTAL: Final = NumberStyle(group=".", decimal=",")
SPACED: Final = NumberStyle(group=NBSP, decimal=",")
SWISS: Final = NumberStyle(group=SWISS_APOSTROPHE, decimal=".")
INDIAN: Final = NumberStyle(group=",", decimal=".", indian_grouping=True)

#: The display patterns ``COUNTRY_DEFAULTS`` and the account settings write,
#: read as styles. Both Swiss spellings are accepted: the ASCII one is what
#: CLDR prints today, the typographic one what older releases printed.
PATTERN_STYLES: Final[dict[str, NumberStyle]] = {
    "1,234.56": ANGLO,
    "1.234,56": CONTINENTAL,
    "1 234,56": SPACED,
    f"1{NBSP}234,56": SPACED,
    "1'234.56": SWISS,
    f"1{TYPOGRAPHIC_APOSTROPHE}234.56": SWISS,
    "12,34,567.89": INDIAN,
}

#: The currency fallback, used only when no country is known. This is the
#: table ``boq/pdf_export.py`` carried before the country decided, kept as it
#: was so a document without a country does not change.
_COMMA_DECIMAL_CURRENCIES: Final = frozenset(
    {
        "EUR",
        "RUB",
        "BRL",
        "TRY",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "BGN",
        "HRK",
        "SEK",
        "NOK",
        "DKK",
        "IDR",
        "VND",
        "ARS",
        "CLP",
        "COP",
        "PEN",
        "UYU",
    }
)
#: Currencies whose only home writes them spaced. Not in the old table: a
#: hryvnia or a tenge amount fell through to the American default.
_SPACED_CURRENCIES: Final = frozenset({"UAH", "KZT", "BYN"})


def style_for_country(country_code: str | None) -> NumberStyle | None:
    """The style a country's documents use, or ``None`` when it is not on file."""
    entry = COUNTRY_DEFAULTS.get((country_code or "").strip().upper())
    if entry is None:
        return None
    return PATTERN_STYLES.get(entry.get("number_format", ""))


def style_for_currency(currency: str | None) -> NumberStyle:
    """The fallback style for an amount whose country nobody recorded."""
    code = (currency or "").strip().upper()
    if code == "CHF":
        return SWISS
    if code == "INR":
        return INDIAN
    if code in _SPACED_CURRENCIES:
        return SPACED
    if code in _COMMA_DECIMAL_CURRENCIES:
        return CONTINENTAL
    return ANGLO


def number_style(country_code: str | None = None, currency: str | None = None) -> NumberStyle:
    """The style to print with: the country's when it has one, the currency's otherwise."""
    return style_for_country(country_code) or style_for_currency(currency)


def _group_indian(digits: str) -> list[str]:
    """``1234567`` as ``["12", "34", "567"]``: the last three, then pairs."""
    if len(digits) <= 3:
        return [digits]
    head, last3 = digits[:-3], digits[-3:]
    groups: list[str] = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return [*groups, last3]


def format_number(value: float | Decimal | int | str | None, decimals: int, style: NumberStyle) -> str:
    """Write ``value`` with ``decimals`` fraction digits in ``style``.

    Rounded half away from zero on the decimal value rather than through a
    float, so ``2.675`` prints ``2.68`` the way a person rounding it would.
    ``None`` and anything that is not a number print as zero, which is what
    the generators did before for a missing amount.
    """
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        amount = Decimal(0)
    if not amount.is_finite():
        amount = Decimal(0)
    places = max(int(decimals), 0)
    quantum = Decimal(1).scaleb(-places)
    rounded = amount.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    text = f"{abs(rounded):.{places}f}"
    whole, _, fraction = text.partition(".")
    if style.indian_grouping:
        groups = _group_indian(whole)
    else:
        groups = []
        while whole:
            groups.insert(0, whole[-3:])
            whole = whole[:-3]
    body = style.group.join(groups or ["0"])
    if places:
        body = f"{body}{style.decimal}{fraction}"
    # A negative zero after rounding is still zero on paper.
    if sign and set(body) <= set(f"0{style.group}{style.decimal}"):
        sign = ""
    return f"{sign}{body}"


#: The date order used when the country is not on file. It is the one the PDF
#: generators printed for everybody before the country decided.
DEFAULT_DATE_FORMAT: Final = "DD.MM.YYYY"


def date_format_for_country(country_code: str | None) -> str:
    """The date pattern a country's documents use, ``DD.MM.YYYY`` when unknown."""
    entry = COUNTRY_DEFAULTS.get((country_code or "").strip().upper())
    return (entry or {}).get("date_format") or DEFAULT_DATE_FORMAT


def format_date(value: date | datetime, country_code: str | None = None, pattern: str | None = None) -> str:
    """Write a date in the order and with the separators its country uses.

    Args:
        value: The date. A datetime is written by its date part.
        country_code: ISO 3166-1 alpha-2 of the project's country.
        pattern: An explicit pattern in the ``DD``/``MM``/``YYYY`` tokens of
            ``COUNTRY_DEFAULTS``; overrides the country when given.

    Returns:
        ``04/10/2026`` for Ireland, ``10/04/2026`` for the United States,
        ``2026-10-04`` for Canada, ``04.10.2026`` when the country is unknown.
    """
    day = value.date() if isinstance(value, datetime) else value
    chosen = pattern or date_format_for_country(country_code)
    return chosen.replace("YYYY", f"{day.year:04d}").replace("MM", f"{day.month:02d}").replace("DD", f"{day.day:02d}")


__all__ = [
    "ANGLO",
    "CONTINENTAL",
    "DEFAULT_DATE_FORMAT",
    "INDIAN",
    "NBSP",
    "PATTERN_STYLES",
    "SPACED",
    "SWISS",
    "SWISS_APOSTROPHE",
    "TYPOGRAPHIC_APOSTROPHE",
    "NumberStyle",
    "date_format_for_country",
    "format_date",
    "format_number",
    "number_style",
    "style_for_country",
    "style_for_currency",
]
