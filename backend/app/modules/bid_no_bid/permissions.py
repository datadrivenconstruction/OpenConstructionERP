# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid permission definitions."""

from app.core.permissions import Role, permission_registry

BID_NO_BID_PERMISSIONS: dict[str, Role] = {
    "bid_no_bid.read": Role.VIEWER,
    "bid_no_bid.write": Role.EDITOR,
    "bid_no_bid.decide": Role.MANAGER,
}


def register_bid_no_bid_permissions() -> None:
    """Register permissions for the bid / no-bid module."""
    permission_registry.register_module_permissions("bid_no_bid", BID_NO_BID_PERMISSIONS)
