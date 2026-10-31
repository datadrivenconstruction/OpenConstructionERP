# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day permission definitions."""

from app.core.permissions import Role, permission_registry

BID_DAY_PERMISSIONS: dict[str, Role] = {
    "bid_day.read": Role.VIEWER,
    "bid_day.write": Role.EDITOR,
    "bid_day.submit": Role.MANAGER,
}


def register_bid_day_permissions() -> None:
    """Register permissions for the bid day module."""
    permission_registry.register_module_permissions("bid_day", BID_DAY_PERMISSIONS)
