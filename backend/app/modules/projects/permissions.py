"""Project module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_project_permissions() -> None:
    """Register permissions for the projects module."""
    permission_registry.register_module_permissions(
        "projects",
        {
            "projects.create": Role.EDITOR,
            "projects.read": Role.VIEWER,
            "projects.update": Role.EDITOR,
            "projects.delete": Role.MANAGER,
        },
    )
