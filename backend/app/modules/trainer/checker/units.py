# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What unit each probed ERP field holds, and how values are put in that unit.

Every ``(probe type, field)`` pair has exactly one :data:`FieldKind`:

* ``percent`` - a rate stored on the ERP's 0-100 scale
  (``Contract.retention_percent``, ``metadata.einvoice.vat_rate``,
  ``BOQMarkup.percentage``). A course value or answer written as a fraction
  (``unit: "fraction"``) is multiplied by 100 before it is compared, and so is
  its tolerance, because the tolerance is written in the answer's own unit.
* ``money`` - an amount in the course currency. Both sides are quantised to the
  currency's minor unit (``currency_registry.money_quantum``, half up) and then
  compared within tolerance.
* ``number`` - a plain count or quantity, compared raw.
* ``text`` / ``date`` - compared exactly, case-folded.
* ``bool`` - compared as a boolean.

The percent and text sets are not restated here: they are read from
``spec.PERCENT_PROBE_FIELDS`` and ``spec.TEXT_PROBE_FIELDS`` so the loader and
the checker can never disagree about a field's unit. A unit test walks every
frozen args model and fails when a field has no kind.

Pure: no database, no I/O.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.core.currency_registry import money_quantum
from app.modules.trainer.spec import PERCENT_PROBE_FIELDS, TEXT_PROBE_FIELDS, to_decimal, to_percent

FieldKind = Literal["money", "percent", "number", "text", "date", "bool"]

#: ``schemas.ValueKind`` for each field kind. A boolean is shown as text.
SCHEMA_KIND: dict[str, Literal["money", "percent", "number", "date", "text"]] = {
    "money": "money",
    "percent": "percent",
    "number": "number",
    "text": "text",
    "date": "date",
    "bool": "text",
}

#: Fields that are neither percent, text nor money. Everything a probe reads
#: that is not listed here or in the two spec sets is money.
_OTHER_KINDS: dict[tuple[str, str], FieldKind] = {
    ("boq.position", "quantity"): "number",
    ("boq.markup", "sort_order"): "number",
    ("bid.leveling", "rank"): "number",
    ("bid.submission", "is_valid"): "bool",
    ("claim.lien_waiver", "through_date"): "date",
    ("panel.option", ""): "number",
    ("panel.answer", ""): "number",
}

NUMERIC_KINDS: frozenset[str] = frozenset({"money", "percent", "number"})


def probe_field_kind(probe_type: str, field: str | None) -> FieldKind:
    """The kind of the value one probe field holds.

    Args:
        probe_type: A name from ``probe_types.PROBE_TYPES``.
        field: The probe's ``args.field``; ``None`` or ``""`` for the probe
            types that read one value only (``boq.section_total``,
            ``panel.*``).

    Returns:
        The field kind. ``boq.section_total`` is money.
    """
    key = (probe_type, field or "")
    if key in _OTHER_KINDS:
        return _OTHER_KINDS[key]
    if key in PERCENT_PROBE_FIELDS:
        return "percent"
    if key in TEXT_PROBE_FIELDS:
        return "text"
    return "money"


def rate_to_percent(value: Decimal, unit: str | None) -> Decimal:
    """A rate in the ERP's percent unit: a fraction is multiplied by 100 (exact)."""
    return to_percent(value, unit)


def quantize_money(value: Decimal, currency: str | None) -> Decimal:
    """``value`` rounded half up to the minor unit of ``currency``."""
    return value.quantize(money_quantum(currency), rounding=ROUND_HALF_UP)


def to_kind_decimal(value: object, kind: str, currency: str | None) -> Decimal | None:
    """A numeric value as Decimal in the kind's comparison form.

    Money is quantised to the currency; percent and number are returned raw.
    Strings are parsed (a stored spec carries its numbers as strings).

    Returns:
        The Decimal, or None when ``value`` is not a number.
    """
    parsed = to_decimal(value)
    if parsed is None:
        return None
    return quantize_money(parsed, currency) if kind == "money" else parsed


def parse_panel_number(text: str | None) -> Decimal | None:
    """Parse what a learner typed into a number field.

    The UI already normalises locale separators to a plain decimal string. A
    trailing ``%`` is accepted for percent fields ("3", "3%" and "3.00" all
    read as 3). Nothing is rounded here.

    Returns:
        The Decimal, or None when the text is empty or not a number.
    """
    if text is None:
        return None
    cleaned = text.strip()
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1].strip()
    if not cleaned:
        return None
    return to_decimal(cleaned)


def format_decimal(value: Decimal) -> str:
    """A plain decimal string, never scientific notation (``0E-4`` -> ``0.0000``)."""
    # A negative zero would print as "-0.00", which reads as a sign error.
    return format(abs(value) if value == 0 else value, "f")


def format_value(value: object, kind: str, currency: str | None) -> str | None:
    """A value as the string the API carries.

    Money is quantised to the currency, other numbers are written plain,
    booleans as ``true`` / ``false`` and text as is.

    Returns:
        The string, or None for None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if kind in NUMERIC_KINDS:
        parsed = to_kind_decimal(value, kind, currency)
        if parsed is not None:
            return format_decimal(parsed)
    return str(value)
