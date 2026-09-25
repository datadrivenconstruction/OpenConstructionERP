# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The core invoice.paid handler must stay unsubscribed.

``_handle_invoice_paid`` wrote the total of every paid invoice onto EACH project
budget line, so a project with three lines showed three times its actual cost.
``FinanceService.pay_invoice`` buckets actual per budget line itself; the core
handler only ever overwrote that result.
"""

from __future__ import annotations

from app.core import event_handlers
from app.core.events import event_bus


def test_invoice_paid_has_no_core_budget_rewriter() -> None:
    event_handlers.register_event_handlers()

    handlers = event_bus._handlers.get("invoice.paid", [])

    assert event_handlers._handle_invoice_paid not in handlers
