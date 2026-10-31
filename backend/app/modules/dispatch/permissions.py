# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board permission definitions."""

from app.core.permissions import Role, permission_registry


def register_dispatch_permissions() -> None:
    """Register dispatch permissions; setting up locations and crews sits at MANAGER."""
    permission_registry.register_module_permissions(
        "dispatch",
        {
            "dispatch.read": Role.VIEWER,
            "dispatch.update": Role.EDITOR,
            "dispatch.manage": Role.MANAGER,
        },
    )
