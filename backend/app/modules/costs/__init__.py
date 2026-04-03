"""Cost Database module.

Provides cost item management, rate databases (CWICR, RSMeans, BKI),
search, and bulk import functionality.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.costs.permissions import register_cost_permissions

    register_cost_permissions()
