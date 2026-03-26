"""Takeoff module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_takeoff_permissions() -> None:
    """Register permissions for the Takeoff module."""
    permission_registry.register_module_permissions(
        "takeoff",
        {
            "takeoff.create": Role.EDITOR,
            "takeoff.read": Role.VIEWER,
            "takeoff.update": Role.EDITOR,
            "takeoff.delete": Role.EDITOR,
        },
    )
