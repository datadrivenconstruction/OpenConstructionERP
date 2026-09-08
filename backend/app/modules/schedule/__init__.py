# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""4D Schedule module.

Provides construction scheduling with WBS hierarchy, BOQ position linking,
Gantt chart data, and work order management.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions, the validation rules and the queryable entity."""
    from app.modules.saved_views.registry import entity_registry
    from app.modules.schedule.permissions import register_schedule_permissions
    from app.modules.schedule.realtime_router import register_schedule_realtime_subscribers
    from app.modules.schedule.saved_view_entity import ENTITY_TYPE as ACTIVITY_ENTITY_TYPE
    from app.modules.schedule.saved_view_entity import register as register_activity_entity
    from app.modules.schedule.validators import register_schedule_rules

    register_schedule_permissions()
    # The validators register themselves at import time too. Both routes are
    # kept because the platform has two ways of bringing a module up and a rule
    # that only takes one of them is dormant in the other deployment.
    register_schedule_rules()
    # Register the schedule_activity saved-views entity so a layout's static
    # filter rides the audited whitelist. Idempotent across repeated startups.
    if entity_registry.get(ACTIVITY_ENTITY_TYPE) is None:
        register_activity_entity()
    # Wire the real-time (T3.4) event bridge that fans schedule activity events
    # out to the schedule presence room. Idempotent across repeated startups.
    register_schedule_realtime_subscribers()
