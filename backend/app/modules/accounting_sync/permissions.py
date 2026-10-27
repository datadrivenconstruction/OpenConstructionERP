# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync permission definitions."""

from app.core.permissions import Role, permission_registry

# The ledger link carries company money and OAuth secrets: managers read and run
# syncs, only an admin edits the connection, its secrets and its mappings.
ACCOUNTING_SYNC_PERMISSIONS: dict[str, Role] = {
    "accounting_sync.read": Role.MANAGER,
    "accounting_sync.write": Role.MANAGER,
    "accounting_sync.admin": Role.ADMIN,
}


def register_accounting_sync_permissions() -> None:
    """Register permissions for the accounting sync module."""
    permission_registry.register_module_permissions("accounting_sync", ACCOUNTING_SYNC_PERMISSIONS)
