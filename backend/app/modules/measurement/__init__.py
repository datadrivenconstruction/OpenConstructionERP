# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement (quantity determination) library.

Transparent, formula-based take-off: every quantity keeps the formula that
produced it, so the number can be checked and audited. The model is
country-neutral; REB 23.003 (DA11/DA12) and OENORM A 2063 are presets over it
(see ``presets.py``), and the same sheet works for a NRM or CESMM take-off or
an ad-hoc measurement anywhere.

Pure library (manifest and validation rules, no router or tables), Decimal-exact and ORM-free
like the ``price_breakdown`` and ``einvoice`` libraries.
"""

from app.modules.measurement.formula import (
    MeasurementError,
    list_variables,
    safe_eval,
)
from app.modules.measurement.model import (
    MeasurementLine,
    MeasurementSheet,
    build_line,
    build_sheet,
    reconcile,
)
from app.modules.measurement.presets import (
    PRESETS,
    get_preset,
    preset_for_country,
    render_csv,
    render_markdown,
)

__all__ = [
    "PRESETS",
    "MeasurementError",
    "MeasurementLine",
    "MeasurementSheet",
    "build_line",
    "build_sheet",
    "get_preset",
    "list_variables",
    "preset_for_country",
    "reconcile",
    "render_csv",
    "render_markdown",
    "safe_eval",
]
