# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Labor & Crew Rates module.

Builds a fully loaded hourly labor rate from a productive base wage plus
configurable on-costs (statutory charges, insurance, leave provision, overtime
uplift, supervision, small tools), and blends several trades into a composite
crew rate. The resulting defensible hourly rate feeds unit-rate build-ups.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.labor_rates.permissions import register_labor_rates_permissions

    register_labor_rates_permissions()
    from app.modules.labor_rates.validators import register_labor_rates_validation_rules

    register_labor_rates_validation_rules()
