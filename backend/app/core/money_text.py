# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Reading a money amount out of text a human typed or a supplier sent.

Distinct from :mod:`app.core.money`, which is the strict money TYPE for
stored values: its ``parse_money`` raises on anything that is not already
a clean numeric string, which is right for a database column and wrong
for a form box a site manager typed "approx 50k" into.

This module is the lenient reader. It sits in ``core`` rather than in
either module because both need the same answer and neither should depend
on the other: the register's raise form feeds the quote gate's tier, and
the inbound scanner feeds the compare panel. Two parsers meant two
answers to "what is this package worth".

The failures this exists to stop, all found by fuzzing the raise form:

* ``"50k"``, ``"$50k"``, ``"approx 50,000"``, ``"50,000 AUD"`` and
  ``"$50,000 + GST"`` every one parsed as **0**. Zero is not a harmless
  default here - it is below the $3,000 tier, so the quote gate stopped
  asking for competitive prices on a fifty-thousand-dollar package.
* ``"50.000,00"`` (European grouping) parsed as **$50.00**.

So: parse what a person plausibly wrote, and when it genuinely cannot be
read say so with ``None`` instead of returning a number nobody meant.
``Decimal`` throughout - binary floats do not add cents up correctly, and
these figures end up on a purchase order.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["parse_amount", "amount_or_zero", "format_amount"]

#: Words that surround a figure without changing it. Stripped so
#: "approx 50,000 AUD ex GST" reads as 50000.
_NOISE_RX = re.compile(
    r"\b(?:approx(?:imately)?|about|circa|ca|est(?:imated)?|around|say|budget|allow(?:ance)?"
    r"|aud|usd|nzd|eur|gbp|sgd|cad|dollars?|excl?(?:uding)?|incl?(?:uding)?|plus|ex|inc|gst|vat|tax"
    r"|each|total|nett?|only)\b",
    re.I,
)

#: "$50k" / "1.2m". Applied AFTER the digits are isolated.
_SCALE = {"k": 1000, "m": 1_000_000, "b": 1_000_000_000}

#: 1.234.567,89 and 1 234 567,89 - European grouping. Detected rather than
#: guessed at: taking the last separator as the decimal point would turn
#: an AU "1,234" into 1.234, so the two formats are told apart by shape.
_EU_RX = re.compile(r"^\d{1,3}(?:[. ]\d{3})+,\d{1,2}$")
_EU_PLAIN_RX = re.compile(r"^\d{1,3}(?: \d{3})+$")
#: en-AU: 1,234,567.89 / 1234567.89 / 1234567
_AU_RX = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:\.\d+)?$")


def parse_amount(value: object) -> Decimal | None:
    """The amount, or ``None`` when the text does not contain one.

    ``None`` means "unreadable" and callers must treat it as unknown, not
    as zero - that distinction is the whole point of the function.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    text = str(value).strip()
    if not text:
        return None

    negative = bool(re.match(r"^\(.*\)$", text)) or text.lstrip().startswith("-")
    text = _NOISE_RX.sub(" ", text)
    text = text.replace("$", " ").replace("€", " ").replace("£", " ")
    text = re.sub(r"[()]", " ", text)

    # A trailing k/m multiplier, taken before the digits are cleaned so
    # "50 k" and "50k" behave the same.
    scale = 1
    m_scale = re.search(r"(\d)\s*([kmb])\b", text, re.I)
    if m_scale:
        scale = _SCALE[m_scale.group(2).lower()]
        text = text[: m_scale.end(1)] + text[m_scale.end(2) :]

    # The first number-shaped run. "+ GST" and stray words are already
    # gone, so anything else trailing is not part of the figure.
    m = re.search(r"\d[\d,. ]*\d|\d", text)
    if not m:
        return None
    raw = m.group(0).strip()

    if _EU_RX.match(raw):
        raw = raw.replace(".", "").replace(" ", "").replace(",", ".")
    elif _EU_PLAIN_RX.match(raw):
        raw = raw.replace(" ", "")
    elif _AU_RX.match(raw):
        raw = raw.replace(",", "")
    else:
        # Ambiguous shape ("1.234.567" - no decimal part to disambiguate,
        # "12,34"). Refusing beats inventing: the caller shows the raw
        # text back to the user rather than acting on a guess.
        return None

    try:
        amount = Decimal(raw) * scale
    except InvalidOperation:
        return None
    return -amount if negative else amount


def amount_or_zero(value: object) -> Decimal:
    """``parse_amount`` for the places a Decimal is structurally required.

    Use only where zero is genuinely safe. It is NOT safe for the quote
    gate's tier input, which must treat unreadable as "ask me".
    """
    parsed = parse_amount(value)
    return Decimal("0") if parsed is None else parsed


def format_amount(amount: Decimal | None) -> str:
    """``"36468.60"`` - exact, no float artefacts, no thousands separator."""
    if amount is None:
        return ""
    return f"{amount:.2f}"
