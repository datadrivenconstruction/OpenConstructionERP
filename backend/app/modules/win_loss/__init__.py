# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger: what happened to the bids we submitted."""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.win_loss.permissions import register_win_loss_permissions

    register_win_loss_permissions()
