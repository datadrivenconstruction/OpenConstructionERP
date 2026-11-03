# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan permission definitions."""

from app.core.permissions import Role, permission_registry


def register_capital_plan_permissions() -> None:
    """Register capital_plan.read (viewer and up) and capital_plan.write (manager and up)."""
    permission_registry.register_module_permissions(
        "capital_plan",
        {
            "capital_plan.read": Role.VIEWER,
            "capital_plan.write": Role.MANAGER,
        },
    )
