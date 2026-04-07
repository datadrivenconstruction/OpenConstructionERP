"""Safety module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_safety_permissions() -> None:
    """Register permissions for the safety module."""
    permission_registry.register_module_permissions(
        "safety",
        {
            "safety.create": Role.EDITOR,
            "safety.read": Role.VIEWER,
            "safety.update": Role.EDITOR,
            "safety.delete": Role.MANAGER,
        },
    )
