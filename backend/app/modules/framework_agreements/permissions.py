# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreements permission definitions."""

from app.core.permissions import Role, permission_registry


def register_framework_permissions() -> None:
    """Register permissions for the framework agreements module."""
    permission_registry.register_module_permissions(
        "framework",
        {
            "framework.read": Role.VIEWER,
            "framework.create": Role.EDITOR,
            "framework.edit_rates": Role.EDITOR,
            "framework.issue_order": Role.EDITOR,
            "framework.accept_order": Role.MANAGER,
            # Issuing an order past the cap needs a reason and is logged on the order.
            "framework.override_cap": Role.MANAGER,
            "framework.delete": Role.MANAGER,
        },
    )
