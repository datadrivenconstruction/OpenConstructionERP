"""Tendering module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_tendering_permissions() -> None:
    """Register permissions for the tendering module."""
    permission_registry.register_module_permissions(
        "tendering",
        {
            "tendering.create": Role.EDITOR,
            "tendering.read": Role.VIEWER,
            "tendering.update": Role.EDITOR,
            "tendering.delete": Role.MANAGER,
            "tendering.bid.create": Role.EDITOR,
            "tendering.bid.update": Role.EDITOR,
            "tendering.comparison.read": Role.VIEWER,
        },
    )
