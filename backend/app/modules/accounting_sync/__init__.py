# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync module: Xero, QuickBooks Online, DATEV EXTF, journal and SAF-T.

One neutral provider-adapter interface over the finance document register. The
platform is master for projects, cost codes, contracts and documents; the
accounting system is master for the posted ledger and payment status.
"""

from app.modules.accounting_sync.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions, validation rules and event subscriptions."""
    from app.modules.accounting_sync.events import register_accounting_sync_subscriptions
    from app.modules.accounting_sync.permissions import register_accounting_sync_permissions
    from app.modules.accounting_sync.validators import register_accounting_sync_rules

    register_accounting_sync_permissions()
    register_accounting_sync_rules()
    register_accounting_sync_subscriptions()
