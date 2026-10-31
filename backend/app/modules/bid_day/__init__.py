# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day module: a live board for the last hours before a tender submission.

The board reads the quotes already received in bid management and tendering,
lets estimators adjust and add to them, and freezes what was submitted as an
immutable snapshot. Suggestions carry a confidence; a person always chooses.
"""

from app.modules.bid_day.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.bid_day.permissions import register_bid_day_permissions
    from app.modules.bid_day.validators import register_bid_day_rules

    register_bid_day_permissions()
    register_bid_day_rules()
