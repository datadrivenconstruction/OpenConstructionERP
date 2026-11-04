# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRM Sales Pipeline module.

Accounts, leads, opportunities, activities, pipeline kanban, forecasting,
and win/loss analytics. Emits events that other modules (e.g. Projects)
can subscribe to (most notably ``crm.opportunity.won`` for auto-creating
Project records from a closed-won opportunity payload).
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.crm.permissions import register_crm_permissions

    register_crm_permissions()
    from app.modules.crm.validators import register_crm_validation_rules

    register_crm_validation_rules()
