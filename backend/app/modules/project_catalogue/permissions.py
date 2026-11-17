# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue permission definitions."""

from app.core.permissions import Role, permission_registry


def register_project_catalogue_permissions() -> None:
    """Register permissions for the project catalogue module."""
    permission_registry.register_module_permissions(
        "project_catalogue",
        {
            "project_catalogue.read": Role.VIEWER,
            "project_catalogue.write": Role.EDITOR,
        },
    )
