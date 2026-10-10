# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment taxes shared by the payment certificate, the tax ledger and the e-invoice.

One calculation, so the three documents cannot disagree about a number.
"""

from __future__ import annotations

from app.core.payment_taxes.calc import (
    FIGURE_KINDS,
    REASON_KEYS,
    Choice,
    Figure,
    Override,
    PaymentTaxInput,
    PaymentTaxResult,
    allocate,
    compute_payment_taxes,
)
from app.core.payment_taxes.tables import (
    OverlappingRowsError,
    RateRow,
    categories,
    find_overlaps,
    lookup,
    rows_for,
    validate_rows,
)

__all__ = [
    "FIGURE_KINDS",
    "REASON_KEYS",
    "Choice",
    "Figure",
    "OverlappingRowsError",
    "Override",
    "PaymentTaxInput",
    "PaymentTaxResult",
    "RateRow",
    "allocate",
    "categories",
    "compute_payment_taxes",
    "find_overlaps",
    "lookup",
    "rows_for",
    "validate_rows",
]
