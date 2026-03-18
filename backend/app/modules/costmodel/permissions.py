"""5D Cost Model module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_costmodel_permissions() -> None:
    """Register permissions for the 5D Cost Model module."""
    permission_registry.register_module_permissions(
        "costmodel",
        {
            "costmodel.read": Role.VIEWER,
            "costmodel.write": Role.EDITOR,
            "costmodel.manage": Role.MANAGER,
        },
    )
