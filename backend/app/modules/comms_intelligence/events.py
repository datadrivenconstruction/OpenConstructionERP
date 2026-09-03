# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence event subscribers.

Auto-imported by the module loader, so the ``event_bus.subscribe`` calls
below run at startup. On every ``correspondence.created`` the HEURISTIC
pipeline runs against the new record - free, instant, no AI key needed -
so the review queue populates itself the moment a message is captured.

The AI pass is never triggered from here: tokens are only spent on an
explicit authenticated request (POST .../analyze). An inbox burst must
not silently drain anyone's AI budget.

Handler discipline (platform convention): open our own short-lived
session, log-and-swallow every failure - enrichment is best-effort and
must never break the capture/CRUD path that emitted the event.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus
from app.database import async_session_factory

logger = logging.getLogger(__name__)


async def _on_correspondence_created(event: Event) -> None:
    correspondence_id = (event.data or {}).get("correspondence_id")
    if not correspondence_id:
        return
    try:
        # Local import: service pulls in the AI client; keep module import
        # time (and loader startup) free of that cost.
        import asyncio

        from app.modules.comms_intelligence import service

        # A detached publish can run BEFORE the publisher's request
        # transaction commits, so the row may not be visible to our own
        # session yet (observed with rfq_bidding's award confirmation).
        # Not-found is retried briefly; any other failure is final.
        for attempt in range(4):
            try:
                async with async_session_factory() as session:
                    await service.analyze_correspondence(
                        session,
                        str(correspondence_id),
                        use_ai=False,
                        user_id=None,
                    )
                    await session.commit()
                return
            except service.CorrespondenceNotFound:
                if attempt == 3:
                    raise
                await asyncio.sleep(1.5)
    except Exception:  # noqa: BLE001 - best-effort enrichment, never re-raise
        logger.debug(
            "Comms Intelligence auto-analysis failed for %s",
            correspondence_id,
            exc_info=True,
        )


event_bus.subscribe("correspondence.created", _on_correspondence_created)
