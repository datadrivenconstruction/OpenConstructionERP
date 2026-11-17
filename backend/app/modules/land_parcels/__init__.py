# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels module (survey family).

Parcels with boundaries in the project CRS, areas by coordinates, parties and
rights as data, acquisition status and cost for linear projects, and the PAR
rules. National cadastre rules arrive from country packs through
:mod:`app.modules.land_parcels.profiles`.
"""


async def on_startup() -> None:
    """Module startup hook - register validation rules (permissions come from survey_core)."""
    from app.modules.land_parcels.validators import register_parcel_validation_rules

    register_parcel_validation_rules()
