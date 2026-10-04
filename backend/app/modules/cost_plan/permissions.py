# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Elemental cost plan permission definitions.

One read permission. The plan regroups figures a viewer of the bill can already
read in the bill editor, so reading it, and exporting it, is open to viewers.

* ``cost_plan.read`` - read or export a bill's NRM 1 cost plan (VIEWER).
"""

from app.core.permissions import Role, permission_registry


def register_cost_plan_permissions() -> None:
    """Register permissions for the cost plan module."""
    permission_registry.register_module_permissions(
        "cost_plan",
        {
            "cost_plan.read": Role.VIEWER,
        },
    )
