# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the payroll hours export."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.field_time.payroll_export import HourLine, Key
from app.modules.field_time.payroll_models import PayrollExportProfile, PayrollExportRun, PayrollExportRunLine
from app.modules.projects.models import Project
from app.modules.resources.models import Resource


class PayrollRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # profiles
    async def list_profiles(self) -> list[PayrollExportProfile]:
        stmt = select(PayrollExportProfile).order_by(PayrollExportProfile.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_profile(self, profile_id: uuid.UUID) -> PayrollExportProfile | None:
        return await self.session.get(PayrollExportProfile, profile_id)

    async def get_profile_by_name(self, name: str) -> PayrollExportProfile | None:
        stmt = select(PayrollExportProfile).where(PayrollExportProfile.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_profile(self, profile: PayrollExportProfile) -> PayrollExportProfile:
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def delete_profile(self, profile: PayrollExportProfile) -> None:
        await self.session.delete(profile)
        await self.session.flush()

    # runs
    async def list_runs(self, limit: int = 50) -> list[PayrollExportRun]:
        stmt = select(PayrollExportRun).order_by(PayrollExportRun.number.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_run(self, run_id: uuid.UUID) -> PayrollExportRun | None:
        return await self.session.get(PayrollExportRun, run_id)

    async def next_number(self) -> int:
        top = (await self.session.execute(select(func.max(PayrollExportRun.number)))).scalar()
        return int(top or 0) + 1

    async def overlapping(self, period_from: date, period_to: date) -> list[PayrollExportRun]:
        stmt = select(PayrollExportRun).where(
            PayrollExportRun.period_from <= period_to, PayrollExportRun.period_to >= period_from
        )
        return list((await self.session.execute(stmt.order_by(PayrollExportRun.number))).scalars().all())

    async def add_run(self, run: PayrollExportRun, lines: list[PayrollExportRunLine]) -> PayrollExportRun:
        self.session.add(run)
        await self.session.flush()
        for line in lines:
            line.run_id = run.id
            self.session.add(line)
        await self.session.flush()
        return run

    async def exported_baseline(self) -> dict[Key, Decimal]:
        """Sum of everything earlier runs handed over, per key."""
        stmt = select(
            PayrollExportRunLine.resource_id,
            PayrollExportRunLine.work_date,
            PayrollExportRunLine.project_id,
            PayrollExportRunLine.cost_code,
            PayrollExportRunLine.hour_type,
            func.sum(PayrollExportRunLine.hours),
        ).group_by(
            PayrollExportRunLine.resource_id,
            PayrollExportRunLine.work_date,
            PayrollExportRunLine.project_id,
            PayrollExportRunLine.cost_code,
            PayrollExportRunLine.hour_type,
        )
        out: dict[Key, Decimal] = defaultdict(lambda: Decimal("0"))
        for rid, day, pid, cost, htype, total in (await self.session.execute(stmt)).all():
            out[(str(rid), day, str(pid), cost or "", htype or "regular")] += Decimal(total or 0)
        return dict(out)

    # hours
    async def labour_lines(
        self, date_from: date, date_to: date, project_ids: set[uuid.UUID] | None
    ) -> tuple[list[HourLine], list[str]]:
        """Approved (and reversed, so reversals net) labour lines plus refs of sheets not yet approved."""
        stmt = (
            select(FieldTimesheetLine, FieldTimesheet, Resource, Project)
            .join(FieldTimesheet, FieldTimesheet.id == FieldTimesheetLine.timesheet_id)
            .join(Resource, Resource.id == FieldTimesheetLine.resource_id)
            .join(Project, Project.id == FieldTimesheet.project_id)
            .where(
                FieldTimesheetLine.resource_id.is_not(None),
                FieldTimesheet.date >= date_from,
                FieldTimesheet.date <= date_to,
                FieldTimesheet.status.in_(("approved", "reversed")),
            )
        )
        if project_ids is not None:
            stmt = stmt.where(FieldTimesheet.project_id.in_(project_ids))
        lines: list[HourLine] = []
        for line, sheet, resource, project in (await self.session.execute(stmt)).all():
            lines.append(
                HourLine(
                    resource_id=str(resource.id),
                    worker_name=resource.name,
                    payroll_ref=resource.payroll_ref or "",
                    resource_code=resource.code,
                    work_date=sheet.date,
                    project_id=str(project.id),
                    project_code=project.project_code or project.name,
                    cost_code=line.cost_code or "",
                    hour_type=line.hour_type or "regular",
                    hours=Decimal(line.hours or 0),
                    sign=-1 if sheet.reverses_id is not None else 1,
                    is_daywork=bool(line.is_daywork),
                )
            )
        pending = select(FieldTimesheet.reference).where(
            FieldTimesheet.date >= date_from,
            FieldTimesheet.date <= date_to,
            FieldTimesheet.status.in_(("draft", "submitted")),
        )
        if project_ids is not None:
            pending = pending.where(FieldTimesheet.project_id.in_(project_ids))
        refs = [r for (r,) in (await self.session.execute(pending.order_by(FieldTimesheet.date))).all() if r]
        return lines, refs

    async def project_names(self, ids: set[uuid.UUID]) -> dict[str, Any]:
        if not ids:
            return {}
        rows = (await self.session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()
        return {str(pid): name for pid, name in rows}
