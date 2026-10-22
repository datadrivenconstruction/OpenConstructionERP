# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering module - bid package management and comparison."""


async def on_startup() -> None:
    """Module startup hook - register permissions.

    Mirrors every sibling module: without this hook
    ``register_tendering_permissions()`` is never invoked and the seven
    declared tendering permissions are absent from the registry (any
    future ``RequirePermission("tendering.*")`` gate or RBAC admin UI
    would treat the module as undefined).
    """
    from app.modules.tendering.permissions import register_tendering_permissions
    from app.modules.tendering.recipient_import import register_recipient_import_rules

    register_tendering_permissions()
    register_recipient_import_rules()
