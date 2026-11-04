# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger permission definitions."""

from app.core.permissions import Role, permission_registry


def register_win_loss_permissions() -> None:
    """Register permissions for the win_loss module."""
    permission_registry.register_module_permissions(
        "win_loss",
        {
            "win_loss.read": Role.VIEWER,
            "win_loss.create": Role.EDITOR,
            "win_loss.update": Role.EDITOR,
            "win_loss.delete": Role.MANAGER,
        },
    )
