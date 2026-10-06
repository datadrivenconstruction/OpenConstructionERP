# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost Database module.

Provides cost item management, rate databases (CWICR, regional cost indices),
search, and bulk import functionality.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and the price-list import jobs."""
    from app.modules.costs.permissions import register_cost_permissions
    from app.modules.costs.pricelist_jobs import register_pricelist_job_handlers

    register_cost_permissions()
    register_pricelist_job_handlers()
