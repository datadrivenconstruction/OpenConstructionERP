"""BOQ module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_boq_permissions() -> None:
    """Register permissions for the BOQ module."""
    permission_registry.register_module_permissions(
        "boq",
        {
            "boq.create": Role.EDITOR,
            "boq.read": Role.VIEWER,
            "boq.update": Role.EDITOR,
            "boq.delete": Role.MANAGER,
            "boq.export": Role.VIEWER,
            "boq.import": Role.EDITOR,
        },
    )
