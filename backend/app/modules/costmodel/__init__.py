"""5D Cost Model module.

Provides 5D cost management — S-curves, cash flow projections,
earned value analysis (EVM), and budget tracking integrated with
BOQ positions and project schedules.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.costmodel.permissions import register_costmodel_permissions

    register_costmodel_permissions()
