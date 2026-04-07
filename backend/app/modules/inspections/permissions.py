"""Inspections module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_inspections_permissions() -> None:
    """Register permissions for the inspections module."""
    permission_registry.register_module_permissions(
        "inspections",
        {
            "inspections.create": Role.EDITOR,
            "inspections.read": Role.VIEWER,
            "inspections.update": Role.EDITOR,
            "inspections.delete": Role.MANAGER,
        },
    )
