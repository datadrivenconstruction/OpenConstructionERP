# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync event handlers.

Nothing is posted on an event: an approved invoice waits in the Sync tab until a
user reviews it and posts it (the platform suggests, a human confirms).

Published by the service: ``accounting_sync.sync.failed`` with the connection id,
provider and number of failed records (a notification goes to the connection owner).
"""

from __future__ import annotations


def register_accounting_sync_subscriptions() -> None:
    """Kept for the module loader; there are no automatic postings to subscribe."""
