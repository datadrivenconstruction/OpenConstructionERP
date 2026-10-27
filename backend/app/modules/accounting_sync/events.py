# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync event handlers.

Subscribed:
    invoice.approved -> push the invoice to every live connection whose
                        ``settings.auto_push`` is on and whose scope holds the project.

Published by the service: ``accounting_sync.sync.failed`` with the connection id,
provider and number of failed records (a notification goes to the connection owner).
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_invoice_approved(event: Event) -> None:
    data = event.data or {}
    invoice_id = str(data.get("invoice_id") or "")
    try:
        project_id = uuid.UUID(str(data.get("project_id")))
    except (TypeError, ValueError):
        return
    if not invoice_id:
        return
    from app.database import async_session_factory
    from app.modules.accounting_sync.providers import API_PROVIDERS
    from app.modules.accounting_sync.service import AccountingSyncService

    try:
        async with async_session_factory() as session:
            svc = AccountingSyncService(session)
            for conn in await svc.list_connections():
                if conn.provider not in API_PROVIDERS or conn.status != "connected":
                    continue
                if not (conn.settings_ or {}).get("auto_push"):
                    continue
                await svc.push(conn, project_id=project_id, record_ids={invoice_id})
            await session.commit()
    except Exception:  # noqa: BLE001 - a subscriber never breaks the approval
        logger.warning("accounting auto push failed for invoice %s", invoice_id, exc_info=True)


def register_accounting_sync_subscriptions() -> None:
    """Subscribe the handlers once (idempotent across reloads)."""
    event_bus.subscribe_once("invoice.approved", _on_invoice_approved)
