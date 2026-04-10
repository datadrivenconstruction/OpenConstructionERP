"""RFQ & Bidding module.

Request for Quotation management with bid submission, evaluation,
and award workflows.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.rfq_bidding.permissions import register_rfq_permissions

    register_rfq_permissions()
