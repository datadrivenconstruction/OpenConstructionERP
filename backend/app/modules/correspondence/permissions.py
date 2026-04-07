"""Correspondence module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_correspondence_permissions() -> None:
    """Register permissions for the correspondence module."""
    permission_registry.register_module_permissions(
        "correspondence",
        {
            "correspondence.create": Role.EDITOR,
            "correspondence.read": Role.VIEWER,
            "correspondence.update": Role.EDITOR,
            "correspondence.delete": Role.MANAGER,
        },
    )
