"""Finance module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_finance_permissions() -> None:
    """Register permissions for the finance module."""
    permission_registry.register_module_permissions(
        "finance",
        {
            "finance.create": Role.EDITOR,
            "finance.read": Role.VIEWER,
            "finance.update": Role.EDITOR,
            "finance.delete": Role.MANAGER,
        },
    )
