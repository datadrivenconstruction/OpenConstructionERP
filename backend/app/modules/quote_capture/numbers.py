# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Number​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ parsing for supplier quotes written in any locale.

A quote prints ``1.234,56`` in Germany, ``1 234,56`` in France, ``1,234.56`` in the
UK, ``1'234.56`` in Switzerland and ``١٬٢٣٤٫٥٦`` in Arabic. :func:`parse_number`
reads all of them into a :class:`~decimal.Decimal`. When a single separator is
followed by exactly three digits (``1.234``) the string is ambiguous; the locale
of the document (or of the project) decides, and without one it is read as a
thousands group, which is how price lists print whole amounts.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Languages whose decimal mark is a comma. Everything else uses a point.
_COMMA_DECIMAL = frozenset(
    {
        "de", "fr", "es", "it", "nl", "pt", "ru", "uk", "pl", "cs", "sk", "sl", "hr", "sr", "bg", "ro", "hu",
        "da", "sv", "nb", "no", "fi", "et", "lv", "lt", "el", "tr", "id", "vi", "az", "kk", "uz", "ka", "be",
        "bs", "mk", "sq", "is",
    }
)  # fmt: skip
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_GROUP_SPACES = re.compile(r"[\s   '’]")
_NUMBER_BODY = re.compile(r"^[-+(]?\d[\d.,\s  '’]*\)?-?$")
_CUR = r"(?:[A-Z]{3}|[€$£¥₹₽₺]|zł|Fr\.|ر\.س|د\.إ)"
_EDGE_JUNK = re.compile(rf"^{_CUR}\s*|\s*{_CUR}$|^\s+|\s+$")


def decimal_mark(locale: str | None) -> str | None:
    """Return the decimal mark of a locale (``","`` or ``"."``), or None when unknown."""
    if not locale:
        return None
    norm = locale.replace("_", "-")
    lang = norm.split("-")[0].lower()
    if lang == "de" and norm.upper().endswith("-CH"):
        return "."
    return "," if lang in _COMMA_DECIMAL else "."


def _clean(token: str) -> str:
    text = token.translate(_DIGITS).replace("٫", ".").replace("٬", ",")
    return _EDGE_JUNK.sub("", text.strip())


def looks_numeric(token: str) -> bool:
    """True when a token is a number in some locale (currency signs stripped)."""
    text = _clean(token)
    return bool(text) and bool(_NUMBER_BODY.match(text)) and parse_number(text) is not None


def parse_number(raw: object, locale: str | None = None) -> Decimal | None:
    """Parse a locale-formatted number; returns None for anything that is not one.

    Args:
        raw: The token as printed (``"1.234,56 €"``, ``"(120.00)"``, ``"١٢٣٫٥"``).
        locale: The document or project locale, used only to settle ``1.234``.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = _clean(str(raw))
    if not text:
        return None
    negative = text.startswith("-") or text.endswith("-") or (text.startswith("(") and text.endswith(")"))
    text = _GROUP_SPACES.sub("", text.strip("()+-"))
    if not text or not re.fullmatch(r"[\d.,]+", text):
        return None
    commas, points = text.count(","), text.count(".")
    dec: str | None
    if commas and points:
        dec = "," if text.rfind(",") > text.rfind(".") else "."
    elif commas or points:
        sep = "," if commas else "."
        tail = text.rsplit(sep, 1)[1]
        if (commas or points) > 1:
            dec = None
        elif len(tail) != 3:
            dec = sep
        else:
            dec = sep if decimal_mark(locale) == sep else None
    else:
        dec = None
    if dec is None:
        number = text.replace(",", "").replace(".", "")
    else:
        number = text.replace("." if dec == "," else ",", "").replace(dec, ".")
    try:
        value = Decimal(number)
    except InvalidOperation:
        return None
    return -value if negative else value


def plain(value: Decimal | None) -> str:
    """Canonical storage string: no grouping, point decimal, at least two decimals."""
    if value is None:
        return ""
    text = format(value.quantize(Decimal("0.0001")).normalize(), "f")
    whole, _, frac = text.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def to_decimal(value: object) -> Decimal | None:
    """Read a stored canonical value (``"12.125"`` is twelve and an eighth, never twelve thousand)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return parse_number(value)
