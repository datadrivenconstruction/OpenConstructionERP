# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Asset Operations module.

Operational-phase intelligence layered on the BIM-sourced asset register.
The BIM Hub owns the data (``oe_bim_element``); this module owns the
computed *meaning* of that data: warranty / maintenance / lifecycle
health, portfolio roll-ups, candidate discovery, and warranty-expiry
alerting through the notifications module.

Design rule: this module persists nothing of its own. Every piece of
state (manufacturer, warranty date, service-log entries) lives inside the
existing ``BIMElement.asset_info`` JSON and is written through the BIM Hub
PATCH endpoint, so no Alembic migration is required to ship it.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions.

    The module loader auto-calls this when the package is discovered.
    """
    from app.modules.assets.permissions import register_assets_permissions

    register_assets_permissions()

    from app.modules.assets.validators import register_assets_validation_rules

    register_assets_validation_rules()
