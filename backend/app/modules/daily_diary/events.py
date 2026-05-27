"""‌⁠‍Daily Diary cross-module event subscribers (Wave M4 deep-pass).

Wires diary close-out + signature into:

* ``schedule_advanced.actuals_update`` — last-planner actuals tick.
* ``bi_dashboards.kpi_recompute`` — project performance dashboards
  pick up the new contemporaneous record bundle.

Both follow-on events are published with the same diary payload so
downstream consumers can choose what to fold in. The SCL Protocol's
contemporary-record requirement is honoured by the upstream
``daily_diary.signed`` event (the signed payload is sealed before the
event fires); these handlers do not modify diary contents.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


_SUBSCRIBED_FLAG = "_daily_diary_subscribers_registered"


async def _on_diary_closed(event: Event) -> None:
    """‌⁠‍``daily_diary.closed`` → schedule-actuals + BI projection ticks."""
    data = event.data or {}
    diary_id = data.get("diary_id")
    project_id = data.get("project_id")
    if not (diary_id and project_id):
        return
    diary_date = data.get("diary_date") or ""
    try:
        event_bus.publish_detached(
            "schedule_advanced.actuals_update",
            {
                "source_event": "daily_diary.closed",
                "diary_id": str(diary_id),
                "project_id": str(project_id),
                "diary_date": str(diary_date),
                # Schedule-side resolver looks up which tasks had
                # productivity records attached to this diary day.
                "scope": "all_tasks_for_date",
            },
            source_module="daily_diary",
        )
    except Exception:
        logger.debug("daily_diary: actuals_update emit failed", exc_info=True)

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "daily_diary",
                "source_event": "daily_diary.closed",
                "project_id": str(project_id),
                "kpi_codes": [
                    "labour_hours_actual",
                    "equipment_hours_actual",
                    "diary_completeness_rate",
                ],
                "reason": "diary_entry_submitted",
            },
            source_module="daily_diary",
        )
    except Exception:
        logger.debug("daily_diary: kpi_recompute emit failed", exc_info=True)


async def _on_diary_signed(event: Event) -> None:
    """‌⁠‍``daily_diary.signed`` → BI projection on contemporaneous-record rate."""
    data = event.data or {}
    project_id = data.get("project_id")
    if not project_id:
        return
    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "daily_diary",
                "source_event": "daily_diary.signed",
                "project_id": str(project_id),
                "kpi_codes": [
                    "diary_signed_rate",
                    "scl_protocol_compliance",
                ],
                "reason": "diary_signed",
            },
            source_module="daily_diary",
        )
    except Exception:
        logger.debug(
            "daily_diary: kpi_recompute on signed failed",
            exc_info=True,
        )


def register_subscribers() -> None:
    """Idempotently subscribe daily-diary cross-module handlers."""
    if getattr(event_bus, _SUBSCRIBED_FLAG, False):
        return
    event_bus.subscribe("daily_diary.closed", _on_diary_closed)
    event_bus.subscribe("daily_diary.signed", _on_diary_signed)
    setattr(event_bus, _SUBSCRIBED_FLAG, True)
    logger.info("Daily Diary: 2 cross-module subscriber(s) registered")
