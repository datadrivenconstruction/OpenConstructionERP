# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field Reports module.

Daily field reports for construction sites - weather, workforce,
delays, safety incidents, approvals, and PDF export.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.fieldreports.permissions import register_fieldreports_permissions

    register_fieldreports_permissions()
    from app.modules.fieldreports.validators import register_fieldreports_validation_rules

    register_fieldreports_validation_rules()
