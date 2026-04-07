"""Tasks module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_tasks_permissions() -> None:
    """Register permissions for the tasks module."""
    permission_registry.register_module_permissions(
        "tasks",
        {
            "tasks.create": Role.EDITOR,
            "tasks.read": Role.VIEWER,
            "tasks.update": Role.EDITOR,
            "tasks.delete": Role.MANAGER,
        },
    )
