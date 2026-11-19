# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing: one tender bundled over several projects, split into per-project commitments."""


async def on_startup() -> None:
    """Module startup hook: register permissions and the ``bundle`` rule set."""
    from app.modules.central_purchasing.permissions import register_central_purchasing_permissions
    from app.modules.central_purchasing.validators import register_bundle_rules

    register_central_purchasing_permissions()
    register_bundle_rules()
