# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor module permission definitions.

Round 5 hardening (v4.3.0): ``rate`` and ``block`` carved out into their
own permissions because conflating them with the generic ``update`` gate
let any EDITOR forge a subcontractor's rating roll-up or block a rival
firm from bidding. Both actions are MANAGER-only.
"""

from app.core.permissions import Role, permission_registry


def register_subcontractors_permissions() -> None:
    """Register permissions for the subcontractors module."""
    permission_registry.register_module_permissions(
        "subcontractors",
        {
            "subcontractors.create": Role.EDITOR,
            "subcontractors.read": Role.VIEWER,
            "subcontractors.update": Role.EDITOR,
            "subcontractors.delete": Role.MANAGER,
            "subcontractors.approve_prequalification": Role.MANAGER,
            "subcontractors.approve_payment_foreman": Role.EDITOR,
            "subcontractors.approve_payment_finance": Role.MANAGER,
            "subcontractors.release_retention": Role.MANAGER,
            # ── R5 - dedicated gates for tamper-sensitive actions ──
            "subcontractors.rate": Role.MANAGER,
            "subcontractors.block": Role.MANAGER,
            # Paying despite lapsed mandatory insurance, with a recorded reason.
            "subcontractors.override_insurance": Role.MANAGER,
        },
    )
