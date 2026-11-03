# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan: which projects fit the money, and what if we delay one."""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.capital_plan.permissions import register_capital_plan_permissions
    from app.modules.capital_plan.validators import register_capital_plan_rules

    register_capital_plan_permissions()
    register_capital_plan_rules()
