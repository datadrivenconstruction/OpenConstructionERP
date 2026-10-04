# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk Register module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_risk_permissions() -> None:
    """Register permissions for the risk register module."""
    permission_registry.register_module_permissions(
        "risk",
        {
            "risk.create": Role.EDITOR,
            "risk.read": Role.VIEWER,
            "risk.update": Role.EDITOR,
            "risk.delete": Role.MANAGER,
            # Auto-escalation control (TOP-30 #24): manually trigger a
            # project escalation sweep / set per-risk escalation config.
            # Gated at MANAGER - escalation drives notifications and action
            # items, so it is a supervisory action, not a routine edit.
            "risk.escalate": Role.MANAGER,
            # Confirming (or reversing) the money an occurred risk draws from
            # the finance contingency line. Spending contingency is a
            # financial commitment, so it sits at MANAGER like finance.approve.
            "risk.contingency": Role.MANAGER,
        },
    )
