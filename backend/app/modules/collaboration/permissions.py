"""Collaboration module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_collaboration_permissions() -> None:
    """Register permissions for the collaboration module."""
    permission_registry.register_module_permissions(
        "collaboration",
        {
            "collaboration.read": Role.VIEWER,
            "collaboration.create": Role.EDITOR,
            "collaboration.update": Role.EDITOR,
            "collaboration.delete": Role.EDITOR,
        },
    )
