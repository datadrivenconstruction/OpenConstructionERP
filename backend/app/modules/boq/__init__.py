"""Bill of Quantities module.

Provides BOQ management with hierarchical positions, cost calculations,
and integration with project and validation modules.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.boq.permissions import register_boq_permissions

    register_boq_permissions()
