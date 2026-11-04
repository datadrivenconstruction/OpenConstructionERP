# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid scorecard: five weighted criteria per tender, a score against a threshold, a logged decision.

The score is advice computed from the estimator's own 1-5 ratings; a person always decides, and overriding the
recommendation needs a reason. The decision and, later, the outcome feed the win-loss ledger. No AI is involved.
"""

from app.modules.bid_no_bid.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.bid_no_bid.permissions import register_bid_no_bid_permissions
    from app.modules.bid_no_bid.validators import register_bid_no_bid_rules

    register_bid_no_bid_permissions()
    register_bid_no_bid_rules()
