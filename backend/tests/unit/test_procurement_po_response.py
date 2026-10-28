# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression: POResponse must validate an ORM PO whose retainage values are
*methods*, not attributes.

The procurement list endpoint 500'd for any project with at least one purchase
order because ``POResponse.model_validate(po, from_attributes=True)`` read the
bound methods ``po.retainage_amount`` / ``po.retainage_held`` and failed string
validation. The fix points those fields' ``validation_alias`` at a sentinel
that does not exist on the ORM, so model_validate falls back to the "0" default
and the router stamps the real computed values afterwards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.procurement.schemas import POResponse


class _FakePO:
    """Mimics the ORM PurchaseOrder: retainage values are callables (methods)."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.project_id = uuid.uuid4()
        self.vendor_contact_id = None
        self.po_number = "PO-0001"
        self.po_type = "standard"
        self.currency_code = "EUR"
        self.amount_subtotal = "100.00"
        self.tax_amount = "0"
        self.amount_total = "100.00"
        self.status = "draft"
        self.created_by = None
        self.metadata_ = {}
        self.retention_percent = Decimal("5.00")
        self.retain_on_receipt = False
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    # The crux: these are methods, exactly like the real ORM model.
    def retainage_amount(self) -> Decimal:
        return Decimal("5.00")

    def retainage_held(self) -> Decimal:
        return Decimal("0.00")


def test_po_response_validates_when_retainage_are_methods() -> None:
    po = _FakePO()
    # Must not raise (previously raised ValidationError: string_type).
    resp = POResponse.model_validate(po, from_attributes=True)
    # model_validate falls back to the "0" default (alias points at a sentinel).
    assert resp.retainage_amount == "0"
    assert resp.retainage_held == "0"
    # The router stamps the real computed values afterwards (mirrors _po_to_response).
    resp.retainage_amount = str(po.retainage_amount())
    resp.retainage_held = str(po.retainage_held())
    assert resp.retainage_amount == "5.00"
    assert resp.retainage_held == "0.00"
    # Sanity: other fields still come through from the ORM object.
    assert resp.po_number == "PO-0001"
    assert resp.currency_code == "EUR"
    assert resp.retention_percent == "5.00"
