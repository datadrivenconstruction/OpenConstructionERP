"""Assemblies module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_assemblies_permissions() -> None:
    """Register permissions for the Assemblies module."""
    permission_registry.register_module_permissions(
        "assemblies",
        {
            "assemblies.create": Role.EDITOR,
            "assemblies.read": Role.VIEWER,
            "assemblies.update": Role.EDITOR,
            "assemblies.delete": Role.MANAGER,
        },
    )
