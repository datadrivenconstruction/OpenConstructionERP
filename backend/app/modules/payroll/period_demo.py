# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ payroll period: overtime and a night shift, locked, exported, posted, one blocked edit.

For the first demo project with a crew, a week twelve weeks back (clear of the field
time demo window) gets three approved timesheets: a normal day, a ten and a half hour
day with approved overtime and a night shift. The period is built under the project's
country profile, locked, exported as neutral JSON, posted to the labour actuals, and an
attempt to reverse one of its timesheets afterwards is refused and written to the audit.
Idempotent: a project that already has a period is left alone.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll.models import PayrollPeriod
from app.modules.payroll.period_service import PayrollPeriodService

logger = logging.getLogger(__name__)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


async def seed_payroll_period_demo(
    session: AsyncSession, project_ids: Iterable[uuid.UUID], today: date | None = None
) -> dict[str, int]:
    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
    from app.modules.field_time.schemas import ReverseTimesheetRequest
    from app.modules.field_time.service import FieldTimeService
    from app.modules.resources.models import Resource

    counts = {"periods": 0, "lines": 0, "blocked_edits": 0}
    monday = (today or date.today()) - timedelta(weeks=12)
    monday -= timedelta(days=monday.weekday())
    for pid in project_ids:
        if (await session.execute(select(PayrollPeriod.id).where(PayrollPeriod.project_id == pid))).first():
            return counts
        workers = (
            (
                await session.execute(
                    select(Resource)
                    .where(Resource.home_project_id == pid, Resource.resource_type.in_(("person", "crew", "labour")))
                    .order_by(Resource.code)
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        workers = [w for w in workers if (w.default_cost_rate or 0) > 0]
        if not workers:
            continue
        try:
            async with session.begin_nested():
                plan = (
                    (monday, [(7, 0, 15, 30)], False),
                    (monday + timedelta(days=1), [(6, 30, 17, 30)], True),
                    (monday + timedelta(days=2), [(22, 0, 30, 0)], False),
                )
                sheets = []
                for day, spans, overtime in plan:
                    ts = FieldTimesheet(
                        project_id=pid,
                        reference=f"PAY-DEMO-{day.isoformat()}",
                        date=day,
                        status="approved",
                        approved_at=_at(day, 18),
                        note="Payroll period demo",
                        metadata_={"overtime_approved": overtime, "demo": "payroll_period"},
                    )
                    session.add(ts)
                    await session.flush()
                    sheets.append(ts)
                    for w in workers:
                        for sh, sm, eh, em in spans:
                            start = _at(day, sh, sm)
                            end = _at(day, 0) + timedelta(hours=eh, minutes=em)
                            hours = Decimal((end - start).total_seconds() / 3600).quantize(Decimal("0.01"))
                            if hours > 6:
                                hours -= Decimal("0.5")
                            session.add(
                                FieldTimesheetLine(
                                    timesheet_id=ts.id,
                                    resource_id=w.id,
                                    hours=hours,
                                    cost_code="DEMO-LABOUR",
                                    started_at=start,
                                    ended_at=end,
                                    break_minutes=30 if hours > 6 else 0,
                                )
                            )
                await session.flush()
                svc = PayrollPeriodService(session)
                period = await svc.create(
                    pid,
                    period_start=monday,
                    period_end=monday + timedelta(days=6),
                    label=f"Week {monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}",
                )
                await svc.lock(period.id)
                try:
                    await svc.export(period.id, "json")
                except HTTPException:
                    logger.info("demo payroll export left blocked by findings for %s", pid)
                await svc.post_costs(period.id)
                try:
                    await FieldTimeService(session).reverse_timesheet(
                        sheets[0].id, ReverseTimesheetRequest(note="Late correction"), None
                    )
                except HTTPException as exc:
                    await svc._event(
                        period, "edit_blocked", None, reason=str(exc.detail), timesheet=sheets[0].reference
                    )
                    counts["blocked_edits"] += 1
                counts["periods"] += 1
                counts["lines"] += len(await svc.lines(period.id))
        except Exception:  # noqa: BLE001 - the demo never breaks a boot
            logger.warning("payroll period demo skipped for %s", pid, exc_info=True)
            continue
        return counts
    return counts
