# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges permission definitions."""

from app.core.permissions import Role, permission_registry


def register_service_charges_permissions() -> None:
    """Register service charges permissions.

    Approving a budget, raising demands and posting a reconciliation commit money, so they sit at MANAGER.
    """
    permission_registry.register_module_permissions(
        "service_charges",
        {
            "service_charges.read": Role.VIEWER,
            "service_charges.create": Role.EDITOR,
            "service_charges.update": Role.EDITOR,
            "service_charges.delete": Role.MANAGER,
            "service_charges.approve": Role.MANAGER,
            "service_charges.bill": Role.MANAGER,
        },
    )
