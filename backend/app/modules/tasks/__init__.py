# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tasks module.

Project task management - tasks, topics, information requests, decisions,
and personal items with checklists, assignments, and due dates.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.tasks.permissions import register_tasks_permissions

    register_tasks_permissions()
    from app.modules.tasks.validators import register_tasks_validation_rules

    register_tasks_validation_rules()
