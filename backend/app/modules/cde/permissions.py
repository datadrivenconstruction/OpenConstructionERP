"""CDE module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_cde_permissions() -> None:
    """Register permissions for the CDE module."""
    permission_registry.register_module_permissions(
        "cde",
        {
            "cde.create": Role.EDITOR,
            "cde.read": Role.VIEWER,
            "cde.update": Role.EDITOR,
            "cde.delete": Role.MANAGER,
            "cde.transition": Role.MANAGER,
        },
    )
