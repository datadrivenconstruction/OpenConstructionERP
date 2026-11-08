# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inspections cross-module subscribers, auto-imported by the module loader.

``site_sensors.strip.struck`` opens a formwork strike release inspection.
Fail-soft: the strike itself never depends on this.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_strip_struck(event: Event) -> None:
    from app.database import async_session_factory
    from app.modules.inspections.sensor_links import create_strike_inspection

    try:
        async with async_session_factory() as session:
            if await create_strike_inspection(session, event.data or {}) is not None:
                await session.commit()
    except Exception:
        logger.exception(
            "inspections: strike release inspection failed for strip=%s", (event.data or {}).get("strip_id")
        )


event_bus.subscribe_once("site_sensors.strip.struck", _on_strip_struck)
