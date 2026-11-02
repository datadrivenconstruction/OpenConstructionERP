# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule permission definitions."""

from app.core.permissions import Role, permission_registry

OWNER_SCHEDULE_PERMISSIONS: dict[str, Role] = {
    "owner_schedule.read": Role.VIEWER,
    "owner_schedule.write": Role.EDITOR,
}


def register_owner_schedule_permissions() -> None:
    """Register permissions for the owner schedule module."""
    permission_registry.register_module_permissions("owner_schedule", OWNER_SCHEDULE_PERMISSIONS)
