"""Change Orders module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_changeorder_permissions() -> None:
    """Register permissions for the change orders module."""
    permission_registry.register_module_permissions(
        "changeorders",
        {
            "changeorders.create": Role.EDITOR,
            "changeorders.read": Role.VIEWER,
            "changeorders.update": Role.EDITOR,
            "changeorders.delete": Role.MANAGER,
            "changeorders.approve": Role.MANAGER,
        },
    )
