# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CDE (Common Data Environment) module - ISO 19650.

Document containers with revision management, CDE state transitions
(WIP -> Shared -> Published -> Archived), and suitability codes.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.cde.permissions import register_cde_permissions

    register_cde_permissions()

    from app.modules.cde.validators import register_cde_validation_rules

    register_cde_validation_rules()
