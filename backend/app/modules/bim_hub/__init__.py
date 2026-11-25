# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM Hub module.

BIM data management: models, elements, BOQ linking, quantity maps,
and model diffs. Elements can be ingested from Cad2Data (CSV/Excel) or
direct CAD uploads (IFC/RVT).
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.bim_hub.permissions import register_bim_hub_permissions
    from app.modules.bim_hub.validators import register_bim_link_validation_rules

    register_bim_hub_permissions()
    register_bim_link_validation_rules()
