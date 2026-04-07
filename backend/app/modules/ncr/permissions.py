"""NCR module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_ncr_permissions() -> None:
    """Register permissions for the NCR module."""
    permission_registry.register_module_permissions(
        "ncr",
        {
            "ncr.create": Role.EDITOR,
            "ncr.read": Role.VIEWER,
            "ncr.update": Role.EDITOR,
            "ncr.delete": Role.MANAGER,
        },
    )
