# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate feedback: actual unit rates and man-hour outturn of closed projects, proposed back to the cost database."""


async def on_startup() -> None:
    """Register permissions and validation rules (idempotent)."""
    from app.modules.rate_feedback.permissions import register_rate_feedback_permissions
    from app.modules.rate_feedback.validators import register_rate_feedback_rules

    register_rate_feedback_permissions()
    register_rate_feedback_rules()
