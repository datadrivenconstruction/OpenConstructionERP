"""Submittals module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_submittals_permissions() -> None:
    """Register permissions for the submittals module."""
    permission_registry.register_module_permissions(
        "submittals",
        {
            "submittals.create": Role.EDITOR,
            "submittals.read": Role.VIEWER,
            "submittals.update": Role.EDITOR,
            "submittals.delete": Role.MANAGER,
        },
    )
