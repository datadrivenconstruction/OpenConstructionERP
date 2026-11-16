# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sealed estimate permissions.

``read_sealed`` is the estimating and management read of a seal's contents
without a formal opening (founder decision 16.11.2026); every such read is
logged. Counterparty and portal users never hold it and see contents only
inside an open session's scope.
"""

from app.core.permissions import Role, permission_registry


def register_estimate_archive_permissions() -> None:
    """Register permissions for the estimate_archive module."""
    permission_registry.register_module_permissions(
        "estimate_archive",
        {
            "estimate_archive.read": Role.VIEWER,
            "estimate_archive.read_sealed": Role.EDITOR,
            "estimate_archive.seal": Role.MANAGER,
            "estimate_archive.request_opening": Role.EDITOR,
            "estimate_archive.attend": Role.EDITOR,
            "estimate_archive.price": Role.EDITOR,
        },
    )
