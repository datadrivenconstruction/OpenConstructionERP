# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Where a stored record came from, kept in the record's own metadata.

One shape for every module that writes a record on behalf of another (a bill position
from a design rule, a request-for-quotation line from a take-off, a budget line from a
bill position): ``metadata["provenance"] = {"kind", "module", ...fields}``. Readers ask
:func:`read`, which answers ``None`` for anything that is not this shape, so another
module's plain ``source`` string is never mistaken for a provenance record.

This is distinct from :mod:`app.core.provenance`, which says how a resolved *jurisdiction
value* was arrived at.
"""

from __future__ import annotations

from typing import Any

KEY = "provenance"


def make(kind: str, module: str, **fields: Any) -> dict[str, Any]:
    """Build a provenance record.

    Args:
        kind: What produced the record, e.g. ``model_rule``, ``derived_rule``, ``takeoff``.
        module: The module that wrote it, e.g. ``oe_design``.
        **fields: Further JSON-serialisable facts (revision, rule, quantity, ...). Money
            and quantities are passed as strings so no float touches them.

    Returns:
        A new dict ready to store under :data:`KEY`.
    """
    return {"kind": kind, "module": module, **fields}


def read(meta: Any) -> dict[str, Any] | None:
    """Return the provenance record stored in ``meta``, or ``None`` when there is none."""
    if not isinstance(meta, dict):
        return None
    value = meta.get(KEY)
    if isinstance(value, dict) and value.get("module"):
        return value
    return None
