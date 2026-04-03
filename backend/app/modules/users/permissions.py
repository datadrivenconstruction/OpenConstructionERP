"""User module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_user_permissions() -> None:
    """Register permissions for the users module."""
    permission_registry.register_module_permissions(
        "users",
        {
            "users.list": Role.MANAGER,
            "users.read": Role.MANAGER,
            "users.create": Role.ADMIN,
            "users.update": Role.ADMIN,
            "users.delete": Role.ADMIN,
            "users.api_keys.manage": Role.EDITOR,
        },
    )
