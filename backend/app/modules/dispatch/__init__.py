# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board - who and what goes where, day by day.

Composes existing modules: people and certificates from resources, units, work orders and
rentals from equipment, timesheets from field time. The board stores only placements.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.dispatch.permissions import register_dispatch_permissions
    from app.modules.dispatch.validators import register_dispatch_validation_rules

    register_dispatch_permissions()
    register_dispatch_validation_rules()
