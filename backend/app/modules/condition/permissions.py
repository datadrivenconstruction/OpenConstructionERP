# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_condition_permissions() -> None:
    """Register permissions for condition ratings and the maintenance plan.

    Approving or rejecting a proposed action, and writing plan figures into the
    asset register, commit money to the plan, so they sit at MANAGER.
    """
    permission_registry.register_module_permissions(
        "condition",
        {
            "condition.read": Role.VIEWER,
            "condition.create": Role.EDITOR,
            "condition.update": Role.EDITOR,
            "condition.delete": Role.MANAGER,
            "condition.approve": Role.MANAGER,
        },
    )
