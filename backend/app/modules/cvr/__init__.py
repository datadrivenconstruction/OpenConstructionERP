# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CVR (Cost-Value Reconciliation) & Cashflow module.

The commercial monthly CVR: reconcile cost-to-date against value earned per cost
head, forecast the final cost, value and margin, and forecast project cashflow
as a cumulative S-curve. Every monetary value is a ``decimal.Decimal`` end to
end and emitted as a string on the wire (never a float).
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.cvr.permissions import register_cvr_permissions

    register_cvr_permissions()
    from app.modules.cvr.validators import register_cvr_validation_rules

    register_cvr_validation_rules()
