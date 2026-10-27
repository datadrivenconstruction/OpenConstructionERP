# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ module: concrete maturity, environment and water sensors with alerts."""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.site_sensors.permissions import register_site_sensors_permissions

    register_site_sensors_permissions()
