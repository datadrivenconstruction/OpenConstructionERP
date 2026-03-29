"""Risk Register module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_risk_permissions() -> None:
    """Register permissions for the risk register module."""
    permission_registry.register_module_permissions(
        "risk",
        {
            "risk.create": Role.EDITOR,
            "risk.read": Role.VIEWER,
            "risk.update": Role.EDITOR,
            "risk.delete": Role.MANAGER,
        },
    )
