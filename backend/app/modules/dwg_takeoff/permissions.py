"""DWG Takeoff module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_dwg_takeoff_permissions() -> None:
    """Register permissions for the dwg_takeoff module."""
    permission_registry.register_module_permissions(
        "dwg_takeoff",
        {
            "dwg_takeoff.create": Role.EDITOR,
            "dwg_takeoff.read": Role.VIEWER,
            "dwg_takeoff.update": Role.EDITOR,
            "dwg_takeoff.delete": Role.MANAGER,
        },
    )
