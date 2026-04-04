"""Markups & Annotations module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_markups_permissions() -> None:
    """Register permissions for the markups module."""
    permission_registry.register_module_permissions(
        "markups",
        {
            "markups.create": Role.EDITOR,
            "markups.read": Role.VIEWER,
            "markups.update": Role.EDITOR,
            "markups.delete": Role.MANAGER,
        },
    )
