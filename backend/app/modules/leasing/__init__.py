# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing module - leases of units, rent schedules, rent roll and arrears.

Neutral: country limits such as a deposit cap come from country data with a
source, and absent data means no limit. Tenants are contacts, landlords legal
entities, units property development plots or asset register entries, rent
invoices finance invoices.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.leasing.permissions import register_leasing_permissions
    from app.modules.leasing.validators import register_leasing_validation_rules

    register_leasing_permissions()
    register_leasing_validation_rules()
