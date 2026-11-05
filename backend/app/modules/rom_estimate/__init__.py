# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Conceptual (ROM) estimate module.

Produces an instant order-of-magnitude estimate from minimal input (building
type, gross floor area, quality level and region) using an elemental cost per
m2 model, returning a total, a six-element breakdown and an honest accuracy
band. It is the day-one starting point that the detailed estimating flow later
refines.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.rom_estimate.permissions import register_rom_estimate_permissions

    register_rom_estimate_permissions()
    from app.modules.rom_estimate.validators import register_rom_estimate_validation_rules

    register_rom_estimate_validation_rules()
