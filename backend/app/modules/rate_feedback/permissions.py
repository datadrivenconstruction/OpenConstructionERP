# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Rate-feedback permissions."""

from app.core.permissions import Role, permission_registry


def register_rate_feedback_permissions() -> None:
    """Reading and refreshing are editor work; changing the company rates is a manager's call."""
    permission_registry.register_module_permissions(
        "rate_feedback",
        {
            "rate_feedback.read": Role.VIEWER,
            "rate_feedback.refresh": Role.EDITOR,
            "rate_feedback.confirm": Role.MANAGER,
        },
    )
