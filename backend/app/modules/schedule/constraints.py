# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Activity constraint vocabulary shared by the importers, the API and the CPM input.

One neutral set of names is stored on ``Activity.constraint_type``. XER carries
its own codes (``CS_MSO`` ...), the MSP importer already maps to the neutral
names; :func:`normalize_constraint` folds every spelling into that set.
"""

from __future__ import annotations

CONSTRAINT_TYPES: tuple[str, ...] = (
    "as_soon_as_possible",
    "as_late_as_possible",
    "must_start_on",
    "must_finish_on",
    "start_no_earlier",
    "start_no_later",
    "finish_no_earlier",
    "finish_no_later",
)

# Constraints that are anchored to a calendar date.
DATED_CONSTRAINT_TYPES: frozenset[str] = frozenset(CONSTRAINT_TYPES) - {"as_soon_as_possible", "as_late_as_possible"}

_XER_CODES: dict[str, str | None] = {
    "CS_MSO": "must_start_on",
    "CS_MEO": "must_finish_on",
    "CS_MANDSTART": "must_start_on",
    "CS_MANDFIN": "must_finish_on",
    "CS_MSOA": "start_no_earlier",
    "CS_MEOA": "finish_no_earlier",
    "CS_MSOB": "start_no_later",
    "CS_MEOB": "finish_no_later",
    "CS_ALAP": "as_late_as_possible",
    "CS_ASAP": None,
}


def normalize_constraint(value: object, *, strict: bool = False) -> str | None:
    """Fold any stored or imported constraint spelling into :data:`CONSTRAINT_TYPES`.

    Args:
        value: A neutral name, a P6 XER ``cstr_type`` code, or empty.
        strict: Raise on a value that is none of these instead of returning ``None``.

    Returns:
        The neutral name, or ``None`` for an empty value, ``CS_ASAP`` or (when
        not strict) an unrecognised value.

    Raises:
        ValueError: ``strict`` and the value is not a known constraint.
    """
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    lowered = text.lower()
    if lowered in CONSTRAINT_TYPES:
        return lowered
    code = text.upper()
    if code in _XER_CODES:
        return _XER_CODES[code]
    if strict:
        raise ValueError(f"unknown constraint type {text!r}; expected one of {', '.join(CONSTRAINT_TYPES)}")
    return None
