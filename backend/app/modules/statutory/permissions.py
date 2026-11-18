# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks permission definitions."""

from app.core.permissions import Role, permission_registry


def register_statutory_permissions() -> None:
    """Register permissions for the statutory checks module."""
    permission_registry.register_module_permissions(
        "statutory",
        {
            # Read tables and run the checks; nothing is written.
            "statutory.read": Role.VIEWER,
        },
    )
