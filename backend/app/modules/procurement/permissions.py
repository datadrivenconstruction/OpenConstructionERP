# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_procurement_permissions() -> None:
    """Register permissions for the procurement module.

    R7 audit (2026-05-24):
        ``procurement.create_invoice`` is split off from the generic
        ``procurement.create`` permission and pinned to MANAGER. The
        PO → Invoice conversion crosses into the finance module and
        creates a payable that bypasses the normal invoice approval
        chain - EDITORs can still draft POs and goods receipts, but
        only MANAGER+ may turn one into a vendor invoice (which is a
        binding financial commitment downstream).
    """
    permission_registry.register_module_permissions(
        "procurement",
        {
            "procurement.read": Role.VIEWER,
            "procurement.create": Role.EDITOR,
            "procurement.update": Role.EDITOR,
            "procurement.delete": Role.MANAGER,
            # TOP-30 #10: approving a PO commits budget, so it is a
            # MANAGER-level gate, the same tier as issuing it.
            "procurement.approve": Role.MANAGER,
            "procurement.issue": Role.MANAGER,
            # Voiding a purchase order withdraws a commitment a supplier has
            # already been told about, so it sits at the same tier as making
            # that commitment in the first place. An EDITOR who may raise and
            # amend a PO may not take one back out of circulation.
            "procurement.cancel": Role.MANAGER,
            # Recording the supplier's order confirmation is entering a fact
            # someone received, the same tier as booking a delivery.
            "procurement.acknowledge": Role.EDITOR,
            "procurement.confirm_receipt": Role.EDITOR,
            # R7 (2026-05-24): PO → Invoice conversion is a financial
            # commitment, MANAGER-only.
            "procurement.create_invoice": Role.MANAGER,
        },
    )
