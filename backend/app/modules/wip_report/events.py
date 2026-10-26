# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report event handlers.

Subscribed:
    cvr.report.finalized -> close the WIP period of the same month, when it is not closed yet.

Published by the service (after commit): ``wip_report.period.closed`` and
``wip_report.fade.detected`` (projected gross profit fell more than the threshold).
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_cvr_finalized(event: Event) -> None:
    data = event.data or {}
    period = str(data.get("period") or "")
    try:
        project_id = uuid.UUID(str(data.get("project_id")))
    except (TypeError, ValueError):
        return
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.wip_report import logic
    from app.modules.wip_report.models import WipPeriod
    from app.modules.wip_report.service import WipReportService

    if not logic.valid_period(period):
        return
    try:
        async with async_session_factory() as session:
            exists = (
                await session.execute(
                    select(WipPeriod.id).where(WipPeriod.project_id == project_id, WipPeriod.period == period)
                )
            ).scalar_one_or_none()
            if exists is None:
                await WipReportService(session).close_period(project_id, period, notes="cvr.report.finalized")
                await session.commit()
    except Exception:  # noqa: BLE001 - a subscriber never breaks the cost report
        logger.warning("WIP close after CVR finalize failed for %s %s", project_id, period, exc_info=True)


def register_wip_report_subscriptions() -> None:
    """Subscribe the handlers once (idempotent across reloads)."""
    event_bus.subscribe_once("cvr.report.finalized", _on_cvr_finalized)
