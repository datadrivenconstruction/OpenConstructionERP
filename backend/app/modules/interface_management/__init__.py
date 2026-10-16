# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-management module (multi-package coordination register).

On multi-package and multi-contractor jobs the real coordination risk lives
between the work packages: the handshakes where one party's work meets another's.
This module tracks those interfaces per project - each with an owning side, an
accepting side, a type, a priority, the date it must be agreed by, a status
running from identified to closed (with disputed and on_hold as side states), and
the actions needed to close it. The register numbers are never stored - the
per-status, per-priority and per-type counts, the overdue and disputed lists, the
agreed percentage, the open action load, the per-work-package health and the
single overall health score are all derived from the interfaces and their actions
by the pure functions in :mod:`app.modules.interface_management.register`.
"""

from app.modules.interface_management.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Module startup hook - permissions, validation rules and approval-route subscribers."""
    from app.modules.interface_management.events import register_interface_management_subscribers
    from app.modules.interface_management.permissions import (
        register_interface_management_permissions,
    )
    from app.modules.interface_management.validators import register_interface_management_validation_rules

    register_interface_management_permissions()
    register_interface_management_validation_rules()
    register_interface_management_subscribers()
