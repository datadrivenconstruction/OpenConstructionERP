# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes (second module of the survey family).

Surfaces from points or LandXML, cut and fill between two of them, a Confirm
step, and the trail from a confirmed volume to a BOQ quantity.
"""


async def on_startup() -> None:
    """Module startup hook - register the VOL validation rules."""
    from app.modules.surfaces_volumes.pad_validators import register_pad_validation_rules
    from app.modules.surfaces_volumes.surface_validators import register_surface_validation_rules
    from app.modules.surfaces_volumes.validators import register_volume_validation_rules

    register_volume_validation_rules()
    register_surface_validation_rules()
    register_pad_validation_rules()
