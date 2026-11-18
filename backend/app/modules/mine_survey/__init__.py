# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey and reconciliation (sixth module of the survey family).

A period holds one line per mining unit: the plan, the actual from a confirmed
Volumes calculation, survey tonnes from a density, and the truck-count tonnes
for a cross-check. Only a confirmed actual can be added to a progress claim.
"""


async def on_startup() -> None:
    """Module startup hook - register the MIN validation rules."""
    from app.modules.mine_survey.validators import register_mine_validation_rules

    register_mine_validation_rules()
