# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Punch List module.

Tracks construction deficiencies and quality issues with location pinning,
photo attachments, status transitions, and verification workflows.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions + event subscribers."""
    from app.modules.punchlist.events import register_punchlist_event_subscribers
    from app.modules.punchlist.permissions import register_punchlist_permissions
    from app.modules.punchlist.validators import register_punchlist_validation_rules

    register_punchlist_permissions()
    register_punchlist_event_subscribers()
    register_punchlist_validation_rules()
