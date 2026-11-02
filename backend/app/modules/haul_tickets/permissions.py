# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets permission definitions."""

from app.core.permissions import Role, permission_registry

HAUL_TICKETS_PERMISSIONS: dict[str, Role] = {
    "haul_tickets.read": Role.VIEWER,
    "haul_tickets.write": Role.EDITOR,
    "haul_tickets.verify": Role.MANAGER,
}


def register_haul_tickets_permissions() -> None:
    """Register permissions for the haul tickets module."""
    permission_registry.register_module_permissions("haul_tickets", HAUL_TICKETS_PERMISSIONS)
