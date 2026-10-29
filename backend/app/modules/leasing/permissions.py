# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_leasing_permissions() -> None:
    """Register leasing permissions.

    Activating, terminating and raising rent invoices commit money, so they sit at MANAGER.
    """
    permission_registry.register_module_permissions(
        "leasing",
        {
            "leasing.read": Role.VIEWER,
            "leasing.create": Role.EDITOR,
            "leasing.update": Role.EDITOR,
            "leasing.delete": Role.MANAGER,
            "leasing.manage": Role.MANAGER,
            "leasing.bill": Role.MANAGER,
        },
    )
