"""Schedule module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_schedule_permissions() -> None:
    """Register permissions for the Schedule module."""
    permission_registry.register_module_permissions(
        "schedule",
        {
            "schedule.create": Role.EDITOR,
            "schedule.read": Role.VIEWER,
            "schedule.update": Role.EDITOR,
            "schedule.delete": Role.MANAGER,
            "schedule.work_orders.manage": Role.EDITOR,
        },
    )
