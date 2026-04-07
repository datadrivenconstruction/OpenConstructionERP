"""Meetings module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_meetings_permissions() -> None:
    """Register permissions for the meetings module."""
    permission_registry.register_module_permissions(
        "meetings",
        {
            "meetings.create": Role.EDITOR,
            "meetings.read": Role.VIEWER,
            "meetings.update": Role.EDITOR,
            "meetings.delete": Role.MANAGER,
        },
    )
