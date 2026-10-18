# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release module.

From a supplier's invoice to the amount released for payment, with every step
shown: deductions, VAT, previous releases, retention, rounding, early payment
discount. Per contract it keeps the payment terms (cumulative or incremental
invoicing, interim and warranty retention and their release events, optional
early payment discount and rounding, due days), the invoice ledger per
contract and per project, and the retention register with the postings that
pay retention back. Cost control reads measured, invoiced and paid per cost
line from here (:func:`app.modules.payment_release.billing.line_billing`).

The invoice, its lines, VAT and payments stay in ``finance``; the contract and
its interim retention rate stay in ``contracts``. Rules V11 to V14 and V16 to
V18 are the ``payment_release`` rule set (V15 is in ``cost_chain``).
"""


async def on_startup() -> None:
    """Register the module's permissions and its rule set. Idempotent."""
    from app.modules.payment_release.permissions import register_payment_release_permissions
    from app.modules.payment_release.validators import register_payment_release_rules

    register_payment_release_permissions()
    register_payment_release_rules()
