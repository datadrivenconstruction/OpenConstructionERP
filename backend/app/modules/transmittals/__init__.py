# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Transmittals module - document-issue tracking with recipients.

Stateful flow: ``draft → issued`` (locks editable fields) with per-recipient
``acknowledge`` and ``respond`` events. Audit-trail entries are emitted on
every state transition.
"""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.transmittals.permissions import register_transmittals_permissions

    register_transmittals_permissions()
    from app.modules.transmittals.validators import register_transmittals_validation_rules

    register_transmittals_validation_rules()
