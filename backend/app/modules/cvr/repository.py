# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CVR data access layer.

All database queries for reports, lines, cashflow points and payment
applications live here. No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.cvr.models import (
    CashflowPoint,
    CvrLine,
    CvrReport,
    PaymentApplication,
)


class ReportRepository:
    """Data access for CvrReport."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, report_id: uuid.UUID) -> CvrReport | None:
        return await self.session.get(CvrReport, report_id)

    async def get_by_project_period(self, project_id: uuid.UUID, period: str) -> CvrReport | None:
        stmt = select(CvrReport).where(
            CvrReport.project_id == project_id,
            CvrReport.period == period,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[CvrReport], int]:
        base = select(CvrReport).where(CvrReport.project_id == project_id)
        if status is not None:
            base = base.where(CvrReport.status == status)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(CvrReport.period.desc()).offset(offset).limit(limit)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def line_count(self, report_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(CvrLine).where(CvrLine.report_id == report_id)
        return (await self.session.execute(stmt)).scalar_one()

    async def create(self, report: CvrReport) -> CvrReport:
        self.session.add(report)
        await self.session.flush()
        return report

    async def update_fields(self, report_id: uuid.UUID, **fields: object) -> None:
        stmt = update(CvrReport).where(CvrReport.id == report_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CvrReport, report_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, report: CvrReport) -> None:
        await self.session.delete(report)
        await self.session.flush()


class LineRepository:
    """Data access for CvrLine."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, line_id: uuid.UUID) -> CvrLine | None:
        return await self.session.get(CvrLine, line_id)

    async def list_for_report(self, report_id: uuid.UUID) -> list[CvrLine]:
        stmt = (
            select(CvrLine)
            .where(CvrLine.report_id == report_id)
            .order_by(CvrLine.sort_order.asc(), CvrLine.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, line: CvrLine) -> CvrLine:
        self.session.add(line)
        await self.session.flush()
        return line

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        stmt = update(CvrLine).where(CvrLine.id == line_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CvrLine, line_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, line: CvrLine) -> None:
        await self.session.delete(line)
        await self.session.flush()


class CashflowRepository:
    """Data access for CashflowPoint."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, point_id: uuid.UUID) -> CashflowPoint | None:
        return await self.session.get(CashflowPoint, point_id)

    async def get_by_project_period(self, project_id: uuid.UUID, period: str) -> CashflowPoint | None:
        stmt = select(CashflowPoint).where(
            CashflowPoint.project_id == project_id,
            CashflowPoint.period == period,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> list[CashflowPoint]:
        stmt = select(CashflowPoint).where(CashflowPoint.project_id == project_id).order_by(CashflowPoint.period.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, point: CashflowPoint) -> CashflowPoint:
        self.session.add(point)
        await self.session.flush()
        return point

    async def update_fields(self, point_id: uuid.UUID, **fields: object) -> None:
        stmt = update(CashflowPoint).where(CashflowPoint.id == point_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CashflowPoint, point_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, point: CashflowPoint) -> None:
        await self.session.delete(point)
        await self.session.flush()


class PaymentApplicationRepository:
    """Data access for PaymentApplication."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, app_id: uuid.UUID) -> PaymentApplication | None:
        return await self.session.get(PaymentApplication, app_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[PaymentApplication], int]:
        base = select(PaymentApplication).where(PaymentApplication.project_id == project_id)
        if status is not None:
            base = base.where(PaymentApplication.status == status)

        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = (
            base.order_by(PaymentApplication.period.desc(), PaymentApplication.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def create(self, application: PaymentApplication) -> PaymentApplication:
        self.session.add(application)
        await self.session.flush()
        return application

    async def update_fields(self, app_id: uuid.UUID, **fields: object) -> None:
        stmt = update(PaymentApplication).where(PaymentApplication.id == app_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(PaymentApplication, app_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, application: PaymentApplication) -> None:
        await self.session.delete(application)
        await self.session.flush()
