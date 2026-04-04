"""Punch List module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_punchlist_permissions() -> None:
    """Register permissions for the punch list module."""
    permission_registry.register_module_permissions(
        "punchlist",
        {
            "punchlist.create": Role.EDITOR,
            "punchlist.read": Role.VIEWER,
            "punchlist.update": Role.EDITOR,
            "punchlist.delete": Role.MANAGER,
            "punchlist.verify": Role.MANAGER,
        },
    )
