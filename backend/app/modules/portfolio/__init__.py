# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Portfolio / multi-project module (T3.3).

An enterprise schedule-of-schedules: a portfolio / programme tree that places
projects for navigation, rollup and access-scoped browsing. The tree composes
with ``accessible_project_ids`` and never widens access.
"""


async def on_startup() -> None:
    """Module startup hook - register portfolio permissions."""
    from app.modules.portfolio.permissions import register_portfolio_permissions

    register_portfolio_permissions()
    from app.modules.portfolio.validators import register_portfolio_validation_rules

    register_portfolio_validation_rules()
