"""Schedule event handlers — bridge field reports into the 4D progress log.

Subscribes to ``fieldreports.report.submitted`` and converts each
``schedule_progress`` payload entry into a :class:`ScheduleProgressEntry`
via :class:`ScheduleProgressService`. Closes the workflow gap where a
foreman would mark "Activity 12 → 70%" on a field report and the
schedule module showed it stuck at 0% because nothing copied the value
across.

Module is auto-imported by the module loader when ``oe_schedule`` is
loaded (see ``module_loader._load_module`` → ``events.py``).

Idempotency
-----------
``ScheduleProgressEntry`` is append-only — re-firing the event WILL
record additional history rows. We de-duplicate at the application
boundary by stamping each accepted entry's ``metadata.report_id`` on
the activity itself; subsequent fires for the same (report, task) pair
short-circuit. This keeps the audit log honest without losing real
duplicate-submit incidents.

Failure mode
------------
Errors are logged and swallowed — the field-report submission must not
fail because the schedule integration choked. Foreman → progress is
already best-effort once it leaves the truck.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.schedule.models import Activity
from app.modules.schedule.service_4d import ScheduleProgressService

logger = logging.getLogger(__name__)


def _coerce_percent(value: object) -> float | None:
    """Coerce a JSON-loaded numeric/string into a 0..100 float, or None."""
    if value is None:
        return None
    try:
        pct = float(str(value))
    except (TypeError, ValueError):
        return None
    if pct < 0.0 or pct > 100.0:
        return None
    return pct


async def _on_field_report_submitted(event: Event) -> None:
    """Schedule progress-rollup work as a detached task.

    See ``procurement/events.py`` for the same SQLite-deadlock-avoidance
    rationale: the publisher is still inside its request transaction
    when ``event_bus.publish`` returns, so a synchronous handler that
    opens a second writer would block on the single-writer lock.
    """
    asyncio.create_task(_record_schedule_progress(event))


async def _record_schedule_progress(event: Event) -> None:
    data = event.data or {}
    report_id_raw = data.get("report_id")
    progress = data.get("schedule_progress")
    submitted_by_raw = data.get("submitted_by")

    if not report_id_raw or not isinstance(progress, list) or not progress:
        return

    submitted_by: uuid.UUID | None
    try:
        submitted_by = uuid.UUID(str(submitted_by_raw)) if submitted_by_raw else None
    except (ValueError, AttributeError):
        submitted_by = None

    try:
        async with async_session_factory() as session:
            service = ScheduleProgressService(session)
            recorded = 0
            skipped_idempotent = 0
            for raw in progress:
                if not isinstance(raw, dict):
                    continue
                task_id_raw = raw.get("task_id")
                if not task_id_raw:
                    continue
                try:
                    task_id = uuid.UUID(str(task_id_raw))
                except (ValueError, AttributeError):
                    logger.warning(
                        "fieldreports.report.submitted: invalid task_id %r — skipped",
                        task_id_raw,
                    )
                    continue

                pct = _coerce_percent(raw.get("progress_percent"))
                if pct is None:
                    logger.warning(
                        "fieldreports.report.submitted: bad progress_percent %r for task=%s — skipped",
                        raw.get("progress_percent"),
                        task_id,
                    )
                    continue

                # Idempotency: stamp the activity with the (report_id, task_id)
                # pair we've already accepted. Re-firing the event for the
                # same report skips the duplicate roll-forward.
                activity = await session.get(Activity, task_id)
                if activity is None:
                    logger.warning(
                        "fieldreports.report.submitted: activity %s not found — skipped",
                        task_id,
                    )
                    continue

                act_md: dict[str, Any] = (
                    activity.metadata_ if isinstance(activity.metadata_, dict) else {}
                )
                accepted_reports = act_md.get("field_report_progress") or []
                if not isinstance(accepted_reports, list):
                    accepted_reports = []
                if str(report_id_raw) in accepted_reports:
                    skipped_idempotent += 1
                    continue

                try:
                    await service.record(
                        task_id=task_id,
                        progress_percent=pct,
                        notes=str(raw.get("notes") or "") or None,
                        device="api",
                        recorded_by_user_id=submitted_by,
                        actual_start_date=raw.get("actual_start_date"),
                        actual_finish_date=raw.get("actual_finish_date"),
                    )
                except (LookupError, ValueError) as exc:
                    logger.warning(
                        "fieldreports.report.submitted: record() rejected task=%s pct=%s: %s",
                        task_id, pct, exc,
                    )
                    continue

                # Re-fetch metadata after .record() in case it expired the
                # JSON column. Append the report_id and re-flush.
                accepted_reports = list(accepted_reports) + [str(report_id_raw)]
                activity.metadata_ = {**act_md, "field_report_progress": accepted_reports}
                recorded += 1

            await session.commit()
            logger.info(
                "Field report progress applied: report=%s recorded=%d skipped_idempotent=%d",
                report_id_raw, recorded, skipped_idempotent,
            )
    except Exception:
        logger.exception(
            "fieldreports.report.submitted handler failed for report=%s "
            "— field report submission itself was unaffected",
            report_id_raw,
        )


event_bus.subscribe("fieldreports.report.submitted", _on_field_report_submitted)
