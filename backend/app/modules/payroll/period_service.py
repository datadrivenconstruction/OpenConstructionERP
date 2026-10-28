# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ export periods: approved timesheets to pay lines, lock, export, cost posting.

A period reads the approved field timesheets of one project in a date range (reversed
originals and their reversals cancel out, so both are left out), drops plant lines and
subcontractor labour, prices each line at the employee's pay rate and splits the hours
into pay types with :mod:`app.modules.payroll.pay_rules`.

Lifecycle: ``open`` (rebuild allowed) -> ``locked`` (timesheet edits in the range are
refused by field_time) -> ``exported``. Reopening needs a reason and is audited.
Posting sends gross plus employer burden to the cost spine under ``labor``, and takes
the field estimate for the covered days off, the same way an approved batch does.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll import pay_rules, period_exports
from app.modules.payroll.events import safe_publish
from app.modules.payroll.models import PayrollPeriod, PayrollPeriodEvent, PayrollPeriodLine

logger = logging.getLogger(__name__)

OPEN, LOCKED, EXPORTED = "open", "locked", "exported"
SOURCE_KIND = "payroll_period"
EVENT_LOCKED = "payroll.period.locked"
EVENT_REOPENED = "payroll.period.reopened"
EVENT_EXPORTED = "payroll.period.exported"
EVENT_POSTED = "payroll.period.posted"
EXPORT_FORMATS = ("csv", "xlsx", "json", "lodas")


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def locking_period(session: AsyncSession, project_id: uuid.UUID, day: date) -> PayrollPeriod | None:
    """The locked or exported period of the project that covers ``day``, if any."""
    stmt = select(PayrollPeriod).where(
        and_(
            PayrollPeriod.project_id == project_id,
            PayrollPeriod.status.in_((LOCKED, EXPORTED)),
            PayrollPeriod.period_start <= day,
            PayrollPeriod.period_end >= day,
        )
    )
    return (await session.execute(stmt.limit(1))).scalars().first()


async def assert_day_open(session: AsyncSession, project_id: uuid.UUID, day: date) -> None:
    """Raise 409 when a locked payroll period covers this project day."""
    period = await locking_period(session, project_id, day)
    if period is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Payroll period '{period.label}' ({period.period_start} to {period.period_end}) is locked, "
                "so timesheets in it cannot change. Ask payroll to reopen the period with a reason."
            ),
        )


class PayrollPeriodService:
    """Build, lock, reopen, export and post payroll periods."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads ---------------------------------------------------------------

    async def get(self, period_id: uuid.UUID) -> PayrollPeriod:
        row = await self.session.get(PayrollPeriod, period_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll period not found")
        return row

    async def list_for_project(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[PayrollPeriod], int]:
        base = select(PayrollPeriod).where(PayrollPeriod.project_id == project_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(PayrollPeriod.period_start.desc(), PayrollPeriod.id).offset(offset).limit(limit)
        return list((await self.session.execute(page)).scalars().all()), total

    async def lines(self, period_id: uuid.UUID) -> list[PayrollPeriodLine]:
        stmt = (
            select(PayrollPeriodLine)
            .where(PayrollPeriodLine.period_id == period_id)
            .order_by(PayrollPeriodLine.employee_name, PayrollPeriodLine.work_date, PayrollPeriodLine.pay_type)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def events(self, period_id: uuid.UUID) -> list[PayrollPeriodEvent]:
        stmt = (
            select(PayrollPeriodEvent)
            .where(PayrollPeriodEvent.period_id == period_id)
            .order_by(PayrollPeriodEvent.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # -- build ---------------------------------------------------------------

    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return project

    async def _work_lines(self, period: PayrollPeriod) -> tuple[list[pay_rules.WorkLine], dict[str, str]]:
        from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
        from app.modules.resources.models import Resource

        stmt = (
            select(FieldTimesheet, FieldTimesheetLine)
            .join(FieldTimesheetLine, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
            .where(
                FieldTimesheet.project_id == period.project_id,
                FieldTimesheet.status == "approved",
                FieldTimesheet.reverses_id.is_(None),
                FieldTimesheet.date >= period.period_start,
                FieldTimesheet.date <= period.period_end,
                FieldTimesheetLine.resource_id.is_not(None),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        rows = [(ts, ln) for ts, ln in rows if (ln.employer_kind or "").lower() != "subcontractor"]
        ids = {ln.resource_id for _, ln in rows}
        resources: dict[str, Any] = {}
        if ids:
            res = await self.session.execute(select(Resource).where(Resource.id.in_(ids)))
            resources = {str(r.id): r for r in res.scalars().all()}
        numbers: dict[str, str] = {}
        out: list[pay_rules.WorkLine] = []
        for ts, ln in rows:
            rid = str(ln.resource_id)
            res = resources.get(rid)
            meta = (res.metadata_ if res is not None and isinstance(res.metadata_, dict) else {}) or {}
            numbers[rid] = str(meta.get("personnel_number") or (res.code if res is not None else ""))
            ts_meta = ts.metadata_ if isinstance(ts.metadata_, dict) else {}
            out.append(
                pay_rules.WorkLine(
                    employee_id=rid,
                    employee_name=res.name if res is not None else rid,
                    work_date=ts.date,
                    hours=Decimal(str(ln.hours or 0)),
                    rate=Decimal(str(res.default_cost_rate or 0)) if res is not None else Decimal("0"),
                    cost_code=ln.cost_code or "",
                    project_id=str(ts.project_id),
                    started_at=ln.started_at,
                    ended_at=ln.ended_at,
                    overtime_approved=bool(ts_meta.get("overtime_approved")),
                    source_ref=str(ln.id),
                )
            )
        return out, numbers

    def _holidays(self, country: str, start: date, end: date) -> set[date]:
        if not country:
            return set()
        try:
            from app.core.calendar import resolve_holidays
        except ImportError:  # pragma: no cover
            return set()
        days: set[date] = set()
        for year in range(start.year, end.year + 1):
            days |= set(resolve_holidays(country, year).get("dates") or ())
        return days

    async def _rebuild_lines(self, period: PayrollPeriod) -> None:
        profile = pay_rules.profile_for(period.rule_profile, period.country)
        work, numbers = await self._work_lines(period)
        pay = pay_rules.classify(work, profile, self._holidays(period.country, period.period_start, period.period_end))
        await self.session.execute(delete(PayrollPeriodLine).where(PayrollPeriodLine.period_id == period.id))
        gross = Decimal("0")
        hours = Decimal("0")
        for p in pay:
            self.session.add(
                PayrollPeriodLine(
                    period_id=period.id,
                    employee_id=_uuid(p.employee_id),
                    employee_number=numbers.get(p.employee_id, ""),
                    employee_name=p.employee_name,
                    work_date=p.work_date,
                    cost_code=p.cost_code,
                    pay_type=p.pay_type,
                    hours=p.hours,
                    rate=p.rate,
                    multiplier=p.multiplier,
                    amount=p.amount,
                    overtime_approved=p.overtime_approved,
                    source_refs=p.source_refs,
                )
            )
            gross += p.amount
            if p.pay_type != "night_premium":
                hours += p.hours
        period.total_hours = hours
        period.total_gross = gross
        period.total_burden = pay_rules.burden(gross, profile)
        meta = dict(period.metadata_ or {})
        meta["max_hours_breaches"] = pay_rules.max_hours_breaches(work, profile)
        meta["totals_by_type"] = pay_rules.totals_by_type(pay)
        meta["flags"] = profile.get("flags") or {}
        period.metadata_ = meta
        await self.session.flush()

    async def create(
        self,
        project_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
        label: str = "",
        rule_profile: str | None = None,
        user_id: str | None = None,
    ) -> PayrollPeriod:
        if period_end < period_start:
            raise HTTPException(status_code=422, detail="The period ends before it starts.")
        project = await self._project(project_id)
        country = str(getattr(project, "country_code", "") or "").upper()[:2]
        profile = pay_rules.profile_for(rule_profile, country)
        period = PayrollPeriod(
            project_id=project_id,
            label=label or f"{period_start.isoformat()} to {period_end.isoformat()}",
            period_start=period_start,
            period_end=period_end,
            country=country,
            rule_profile=str(profile["profile"]),
            status=OPEN,
            currency=str(getattr(project, "currency", "") or ""),
            created_by=_uuid(user_id),
            metadata_={},
        )
        self.session.add(period)
        await self.session.flush()
        await self._rebuild_lines(period)
        await self._event(period, "built", user_id)
        return period

    async def rebuild(self, period_id: uuid.UUID, user_id: str | None = None) -> PayrollPeriod:
        period = await self.get(period_id)
        if period.status != OPEN:
            raise HTTPException(status_code=409, detail="Only an open period can be rebuilt. Reopen it first.")
        await self._rebuild_lines(period)
        await self._event(period, "rebuilt", user_id)
        return period

    # -- lifecycle -----------------------------------------------------------

    async def _event(self, period: PayrollPeriod, action: str, user_id: str | None, reason: str = "", **details: Any):
        self.session.add(
            PayrollPeriodEvent(
                period_id=period.id, action=action, reason=reason, actor_id=_uuid(user_id), details=details
            )
        )
        await self.session.flush()

    async def lock(self, period_id: uuid.UUID, user_id: str | None = None) -> PayrollPeriod:
        period = await self.get(period_id)
        if period.status != OPEN:
            return period
        await self._rebuild_lines(period)
        period.status = LOCKED
        period.locked_at = datetime.now(UTC)
        period.locked_by = _uuid(user_id)
        await self._event(period, "locked", user_id)
        await safe_publish(EVENT_LOCKED, self._payload(period))
        await self._notify(period, "notification.payroll_period_locked_title", user_id)
        return period

    async def reopen(self, period_id: uuid.UUID, reason: str, user_id: str | None = None) -> PayrollPeriod:
        period = await self.get(period_id)
        if not reason or not reason.strip():
            raise HTTPException(status_code=422, detail="Say why the period is reopened.")
        if period.status == OPEN:
            return period
        prior = period.status
        period.status = OPEN
        period.locked_at = None
        period.locked_by = None
        await self._event(period, "reopened", user_id, reason=reason.strip(), prior_status=prior)
        await safe_publish(EVENT_REOPENED, {**self._payload(period), "reason": reason.strip()})
        return period

    async def export(
        self,
        period_id: uuid.UUID,
        fmt: str,
        *,
        columns: list[str] | None = None,
        consultant_number: str = "",
        client_number: str = "",
        user_id: str | None = None,
    ) -> tuple[bytes, str, str]:
        """Render the export; returns ``(content, media_type, filename)``."""
        period = await self.get(period_id)
        if fmt not in EXPORT_FORMATS:
            raise HTTPException(status_code=422, detail=f"Unknown export format '{fmt}'.")
        from app.modules.payroll.validators import evaluate_period

        findings = await evaluate_period(await self.validation_snapshot(period, export_format=fmt))
        errors = [f for f in findings if str(getattr(f.severity, "value", f.severity)) == "error"]
        if errors:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Fix these before exporting.", "findings": [e.message for e in errors]},
            )
        rows = self.rows(period, await self.lines(period.id))
        stem = f"payroll_{period.period_start.isoformat()}_{period.period_end.isoformat()}"
        try:
            if fmt == "csv":
                content, media, name = (
                    period_exports.to_csv(rows, columns).encode("utf-8-sig"),
                    "text/csv",
                    f"{stem}.csv",
                )
            elif fmt == "xlsx":
                content = period_exports.to_xlsx(rows, columns)
                media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                name = f"{stem}.xlsx"
            elif fmt == "json":
                head = {**self.header(period), "certified_payroll_weeks": await self.certified_weeks(period)}
                content = period_exports.to_json(head, rows).encode("utf-8")
                media, name = "application/json", f"{stem}.json"
            else:
                profile = pay_rules.profile_for(period.rule_profile, period.country)
                lodas = profile.get("datev_lodas")
                if not lodas:
                    raise ValueError("This rule profile has no LODAS wage type mapping. Choose the DE profile.")
                content = period_exports.to_lodas(
                    rows,
                    period_start=period.period_start,
                    consultant_number=consultant_number,
                    client_number=client_number,
                    lodas=lodas,
                )
                media, name = "text/plain; charset=windows-1252", f"{stem}_lodas.txt"
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        period.status = EXPORTED
        period.exported_at = datetime.now(UTC)
        await self._event(period, "exported", user_id, format=fmt, lines=len(rows))
        await safe_publish(EVENT_EXPORTED, {**self._payload(period), "format": fmt})
        return content, media, name

    async def post_costs(self, period_id: uuid.UUID, user_id: str | None = None) -> PayrollPeriod:
        """Post gross plus burden to the project labour actuals (idempotent per period)."""
        period = await self.get(period_id)
        if period.status == OPEN:
            raise HTTPException(status_code=409, detail="Lock the period before posting labour cost.")
        total = (period.total_gross or Decimal("0")) + (period.total_burden or Decimal("0"))
        if total > 0:
            if not period.currency:
                raise HTTPException(status_code=400, detail="The project has no currency, so cost cannot post.")
            from app.modules.costmodel.service import CostSpineService, LabourActualsService

            await CostSpineService(self.session).post_actual_to_budget_line(
                project_id=period.project_id,
                cost_line_id=None,
                cost_category="labor",
                amount_base=str(total),
                currency=period.currency,
                source_kind=SOURCE_KIND,
                source_ref=str(period.id),
                idempotency_key=f"payroll_period:{period.id}",
            )
            lines = await self.lines(period.id)
            await LabourActualsService(self.session).supersede_with_payroll(
                project_id=period.project_id,
                batch_id=f"period:{period.id}",
                entries=[
                    {
                        "resource_id": str(ln.employee_id) if ln.employee_id else "",
                        "work_date": ln.work_date.isoformat(),
                        "hours": str(ln.hours),
                    }
                    for ln in lines
                    if ln.pay_type in ("regular", "overtime", "overtime_weekly", "saturday", "sunday", "holiday")
                ],
            )
        period.posted_ref = f"PAYROLL-PERIOD-{period.id}"
        await self._event(period, "posted", user_id, amount=str(total))
        await safe_publish(EVENT_POSTED, {**self._payload(period), "amount": str(total)})
        return period

    # -- shapes --------------------------------------------------------------

    def header(self, period: PayrollPeriod) -> dict[str, Any]:
        return {
            "id": str(period.id),
            "project_id": str(period.project_id),
            "label": period.label,
            "period_start": period.period_start.isoformat(),
            "period_end": period.period_end.isoformat(),
            "country": period.country,
            "rule_profile": period.rule_profile,
            "status": period.status,
            "currency": period.currency,
            "total_hours": str(period.total_hours),
            "total_gross": str(period.total_gross),
            "total_burden": str(period.total_burden),
            "flags": (period.metadata_ or {}).get("flags") or {},
        }

    @staticmethod
    def rows(period: PayrollPeriod, lines: list[PayrollPeriodLine]) -> list[dict[str, Any]]:
        return [
            {
                "employee_id": str(ln.employee_id) if ln.employee_id else "",
                "employee_number": ln.employee_number,
                "employee": ln.employee_name,
                "project": str(period.project_id),
                "project_id": str(period.project_id),
                "cost_code": ln.cost_code,
                "work_date": ln.work_date.isoformat(),
                "pay_type": ln.pay_type,
                "hours": str(ln.hours),
                "rate": str(ln.rate),
                "multiplier": str(ln.multiplier),
                "amount": str(ln.amount),
                "currency": period.currency,
                "overtime_approved": ln.overtime_approved,
                "period_start": period.period_start.isoformat(),
                "period_end": period.period_end.isoformat(),
            }
            for ln in lines
        ]

    def _payload(self, period: PayrollPeriod) -> dict[str, Any]:
        return {
            "project_id": str(period.project_id),
            "period_id": str(period.id),
            "status": period.status,
            "gross": str(period.total_gross),
            "burden": str(period.total_burden),
            "currency": period.currency,
        }

    async def validation_snapshot(self, period: PayrollPeriod, *, export_format: str | None = None) -> dict[str, Any]:
        lines = await self.lines(period.id)
        return {
            "period": self.header(period),
            "export_format": export_format,
            "lines": [
                {
                    "employee": ln.employee_name,
                    "work_date": ln.work_date.isoformat(),
                    "cost_code": ln.cost_code,
                    "pay_type": ln.pay_type,
                    "hours": str(ln.hours),
                    "rate": str(ln.rate),
                    "overtime_approved": ln.overtime_approved,
                }
                for ln in lines
            ],
            "max_hours_breaches": (period.metadata_ or {}).get("max_hours_breaches") or [],
        }

    async def dashboard(self, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        stmt = select(PayrollPeriod)
        if project_id is not None:
            stmt = stmt.where(PayrollPeriod.project_id == project_id)
        periods = list((await self.session.execute(stmt.order_by(PayrollPeriod.period_start.desc()))).scalars())
        by_status: dict[str, int] = {}
        for p in periods:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        latest = periods[0] if periods else None
        return {
            "periods": len(periods),
            "by_status": by_status,
            "latest": self.header(latest) if latest is not None else None,
            "latest_totals_by_type": ((latest.metadata_ or {}).get("totals_by_type") if latest else None) or {},
        }

    async def certified_weeks(self, period: PayrollPeriod) -> list[dict[str, str]]:
        """Certified payroll weeks of a prevailing wage project that end inside the period."""
        if not ((period.metadata_ or {}).get("flags") or {}).get("prevailing_wage"):
            return []
        try:
            from app.modules.certified_payroll.models import CertifiedPayrollWeek
        except ImportError:  # pragma: no cover
            return []
        stmt = select(CertifiedPayrollWeek).where(
            CertifiedPayrollWeek.project_id == period.project_id,
            CertifiedPayrollWeek.week_ending >= period.period_start.isoformat(),
            CertifiedPayrollWeek.week_ending <= period.period_end.isoformat(),
        )
        return [
            {"id": str(w.id), "week_ending": w.week_ending, "payroll_number": w.payroll_number}
            for w in (await self.session.execute(stmt)).scalars().all()
        ]

    async def _notify(self, period: PayrollPeriod, title_key: str, user_id: str | None) -> None:
        try:
            from app.modules.notifications.service import NotificationService
            from app.modules.projects.models import Project
        except ImportError:  # pragma: no cover
            return
        project = await self.session.get(Project, period.project_id)
        recipients = {str(project.owner_id)} if project is not None and getattr(project, "owner_id", None) else set()
        if not recipients:
            return
        try:
            await NotificationService(self.session).notify_users(
                list(recipients),
                "info",
                title_key,
                entity_type="payroll_period",
                entity_id=str(period.id),
                body_key="notification.payroll_period_locked_body",
                body_context={"label": period.label},
                action_url=f"/projects/{period.project_id}/payroll",
            )
        except Exception:  # noqa: BLE001 - a notification never breaks a lock
            logger.warning("payroll period notification failed for %s", period.id, exc_info=True)
