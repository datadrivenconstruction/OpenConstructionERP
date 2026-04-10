"""RFQ Bidding module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_rfq_permissions() -> None:
    """Register permissions for the RFQ & Bidding module."""
    permission_registry.register_module_permissions(
        "rfq",
        {
            "rfq.read": Role.VIEWER,
            "rfq.create": Role.EDITOR,
            "rfq.update": Role.EDITOR,
            "rfq.delete": Role.EDITOR,
        },
    )
