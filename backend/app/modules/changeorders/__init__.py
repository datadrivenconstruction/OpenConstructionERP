# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change Orders module.

Tracks scope changes during project execution with cost/schedule impact
and approval workflows (draft -> submitted -> approved/rejected).
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and event subscribers."""
    from app.modules.changeorders.events import register_changeorder_event_subscribers
    from app.modules.changeorders.permissions import register_changeorder_permissions

    register_changeorder_permissions()
    register_changeorder_event_subscribers()
