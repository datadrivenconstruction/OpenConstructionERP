# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges module - owners associations, apportionment keys, charge budgets,
demands raised as finance receivables and year-end reconciliation.

Neutral: it serves UK service charges, German Hausgeld under the WEG, owners
associations in the Gulf and HOAs alike. Actual costs are read from finance
payables and service work orders by cost-category tag; nothing is ledgered here.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.service_charges.permissions import register_service_charges_permissions
    from app.modules.service_charges.validators import register_service_charges_validation_rules

    register_service_charges_permissions()
    register_service_charges_validation_rules()
