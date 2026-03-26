"""Product & Resource Catalog module.

Provides a curated catalog of materials, equipment, labor, and operators
extracted from CWICR cost item components. Supports search, filtering,
and manual resource creation.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.catalog.permissions import register_catalog_permissions

    register_catalog_permissions()
