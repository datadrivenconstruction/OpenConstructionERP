# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Payroll module.

Turns field-reported labour (SiteWorkforceLog + field-diary work hours)
into draft payroll batches: hours x cost_rate = amount, converted to the
project base currency. Manager-scoped, deterministic, human-confirmed -
generation produces a *draft* batch a manager reviews before any payout.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and the period validation rules."""
    from app.modules.payroll.permissions import register_payroll_permissions
    from app.modules.payroll.validators import register_payroll_rules

    register_payroll_permissions()
    register_payroll_rules()
