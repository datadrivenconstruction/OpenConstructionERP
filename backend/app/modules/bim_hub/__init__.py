"""BIM Hub module.

BIM data management: models, elements, BOQ linking, quantity maps,
and model diffs. Elements can be ingested from Cad2Data (CSV/Excel) or
direct CAD uploads (IFC/RVT).
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.bim_hub.permissions import register_bim_hub_permissions

    register_bim_hub_permissions()
