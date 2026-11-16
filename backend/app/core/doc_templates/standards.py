# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mandatory document content from open standards, the same in every market.

Country law adds to this through pack ``document_requirements.json`` files
(:mod:`app.core.doc_templates.legal`); nothing here names a country.
"""

from __future__ import annotations

from app.core.doc_templates.registry import MandatoryField

__all__ = ["EN16931_INVOICE_MINIMUM"]

_SRC = "EN 16931"
_PROFILE = "company profile"

#: The core invoice content of EN 16931-1 a human-readable invoice must carry
#: (BT-1, BT-2, BT-5, BT-27, BT-35, BT-31/32, BT-44, BT-50, BT-109, BT-110, BT-112).
EN16931_INVOICE_MINIMUM: tuple[MandatoryField, ...] = (
    MandatoryField(("doc.number",), "Invoice number", _SRC, "invoice"),
    MandatoryField(("doc.date",), "Invoice date", _SRC, "invoice"),
    MandatoryField(("doc.currency",), "Invoice currency", _SRC, "invoice"),
    MandatoryField(("entity.legal_name",), "Seller name", _SRC, _PROFILE),
    MandatoryField(("entity.address",), "Seller address", _SRC, _PROFILE),
    MandatoryField(("entity.vat_id", "entity.tax_number"), "Seller VAT id or tax number", _SRC, _PROFILE),
    MandatoryField(("recipient.name",), "Buyer name", _SRC, "invoice"),
    MandatoryField(("recipient.address",), "Buyer address", _SRC, "contact"),
    MandatoryField(("doc.total_net",), "Total without VAT", _SRC, "invoice"),
    MandatoryField(("doc.total_vat",), "Total VAT", _SRC, "invoice"),
    MandatoryField(("doc.total_gross",), "Total with VAT", _SRC, "invoice"),
)
