# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily Diary cross-module event subscribers (Wave M4 deep-pass).

Wires diary close-out + signature into:

* ``schedule_advanced.actuals_update`` - last-planner actuals tick.
* ``bi_dashboards.kpi_recompute`` - project performance dashboards
  pick up the new contemporaneous record bundle.

Both follow-on events are published with the same diary payload so
downstream consumers can choose what to fold in. The SCL Protocol's
contemporary-record requirement is honoured by the upstream
``daily_diary.signed`` event (the signed payload is sealed before the
event fires); these handlers do not modify diary contents.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_diary_closed(event: Event) -> None:
    """``daily_diary.closed`` → schedule-actuals + BI projection ticks."""
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
    """``daily_diary.signed`` → BI projection on contemporaneous-record rate."""
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


# ── Last Planner -> diary ──────────────────────────────────────────────────
#
# A closed week, a cleared constraint and a missed commitment are site facts
# the diary of that day should carry. They go into the project's open diary
# for today; when nobody opened today's diary, nothing is created, since a
# diary is a signed record a person starts, not something a planner event writes.


async def _append_lps_entry(
    event: Event,
    *,
    entry_type: str,
    title: str,
    title_key: str,
    params: dict[str, Any],
    source_ref: str | None,
) -> None:
    data = event.data or {}
    project_id = data.get("project_id")
    if not project_id:
        return
    from datetime import UTC, datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.database import async_session_factory  # noqa: PLC0415
    from app.modules.daily_diary.models import DailyDiary, DiaryEntry  # noqa: PLC0415

    today = datetime.now(UTC).date().isoformat()
    try:
        pid = uuid.UUID(str(project_id))
        ref = uuid.UUID(str(source_ref)) if source_ref else None
    except ValueError:
        return
    try:
        async with async_session_factory() as session:
            diary = (
                (
                    await session.execute(
                        select(DailyDiary).where(
                            DailyDiary.project_id == pid,
                            DailyDiary.diary_date == today,
                            DailyDiary.status == "open",
                        )
                    )
                )
                .scalars()
                .first()
            )
            if diary is None:
                return
            session.add(
                DiaryEntry(
                    diary_id=diary.id,
                    entry_type=entry_type,
                    entry_time=datetime.now(UTC),
                    title=title[:500],
                    source_module="schedule_advanced",
                    source_ref=ref,
                    metadata_={"title_key": title_key, "params": params, "source_event": event.name},
                )
            )
            await session.commit()
    except Exception:
        logger.debug("daily_diary: LPS entry for %s failed", event.name, exc_info=True)


async def _on_lps_week_closed(event: Event) -> None:
    data = event.data or {}
    ppc = data.get("ppc_percent")
    week = data.get("week_start_date") or ""
    await _append_lps_entry(
        event,
        entry_type="event",
        title=f"Weekly work plan for {week} closed, PPC {ppc}%",
        title_key="daily_diary.lps.week_closed",
        params={"week": week, "ppc": ppc},
        source_ref=data.get("week_plan_id"),
    )


async def _on_lps_constraint_cleared(event: Event) -> None:
    data = event.data or {}
    desc = data.get("description") or ""
    await _append_lps_entry(
        event,
        entry_type="event",
        title=f"Constraint cleared: {desc}",
        title_key="daily_diary.lps.constraint_cleared",
        params={"description": desc, "type": data.get("constraint_type")},
        source_ref=data.get("constraint_id"),
    )


async def _on_lps_commitment_missed(event: Event) -> None:
    data = event.data or {}
    crew = data.get("worker_or_crew") or ""
    await _append_lps_entry(
        event,
        entry_type="event",
        title=f"Commitment missed by {crew}: {data.get('category') or ''}",
        title_key="daily_diary.lps.commitment_missed",
        params={"crew": crew, "category": data.get("category"), "description": data.get("description")},
        source_ref=data.get("commitment_id"),
    )


async def _on_lps_commitment_completed(event: Event) -> None:
    data = event.data or {}
    crew = data.get("worker_or_crew") or ""
    await _append_lps_entry(
        event,
        entry_type="completion",
        title=f"Commitment completed by {crew}",
        title_key="daily_diary.lps.commitment_completed",
        params={"crew": crew},
        source_ref=data.get("commitment_id"),
    )


def register_subscribers() -> None:
    """Idempotently subscribe daily-diary cross-module handlers."""
    event_bus.subscribe_once("daily_diary.closed", _on_diary_closed)
    event_bus.subscribe_once("daily_diary.signed", _on_diary_signed)
    event_bus.subscribe_once("schedule_advanced.weekly_plan.closed", _on_lps_week_closed)
    event_bus.subscribe_once("schedule_advanced.constraint.cleared", _on_lps_constraint_cleared)
    event_bus.subscribe_once("schedule_advanced.commitment.missed", _on_lps_commitment_missed)
    event_bus.subscribe_once("schedule_advanced.commitment.completed", _on_lps_commitment_completed)
    logger.info("Daily Diary: 6 cross-module subscriber(s) registered")
