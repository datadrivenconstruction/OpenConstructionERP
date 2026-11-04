# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff module - PDF upload and quantity extraction."""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.takeoff.permissions import register_takeoff_permissions

    register_takeoff_permissions()
    from app.modules.takeoff.validators import register_takeoff_validation_rules

    register_takeoff_validation_rules()
