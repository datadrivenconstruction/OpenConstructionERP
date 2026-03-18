"""Cost module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_cost_permissions() -> None:
    """Register permissions for the costs module."""
    permission_registry.register_module_permissions(
        "costs",
        {
            "costs.list": Role.VIEWER,
            "costs.read": Role.VIEWER,
            "costs.create": Role.EDITOR,
            "costs.update": Role.EDITOR,
            "costs.delete": Role.MANAGER,
            "costs.bulk_import": Role.EDITOR,
        },
    )
