"""4D Schedule module.

Provides construction scheduling with WBS hierarchy, BOQ position linking,
Gantt chart data, and work order management.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.schedule.permissions import register_schedule_permissions

    register_schedule_permissions()
