"""Procurement module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_procurement_permissions() -> None:
    """Register permissions for the procurement module."""
    permission_registry.register_module_permissions(
        "procurement",
        {
            "procurement.read": Role.VIEWER,
            "procurement.create": Role.EDITOR,
            "procurement.update": Role.EDITOR,
            "procurement.delete": Role.MANAGER,
            "procurement.issue": Role.MANAGER,
            "procurement.confirm_receipt": Role.EDITOR,
        },
    )
