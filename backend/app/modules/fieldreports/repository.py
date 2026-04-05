"""Field Reports data access layer.

All database queries for field reports live here.
No business logic — pure data access.
"""

import uuid
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldreports.models import FieldReport


class FieldReportRepository:
    """Data access for FieldReport models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, report_id: uuid.UUID) -> FieldReport | None:
        """Get field report by ID."""
        return await self.session.get(FieldReport, report_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        date_from: date | None = None,
        date_to: date | None = None,
        report_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[FieldReport], int]:
        """List field reports for a project with pagination and filters."""
        base = select(FieldReport).where(FieldReport.project_id == project_id)
        if date_from is not None:
            base = base.where(FieldReport.report_date >= date_from)
        if date_to is not None:
            base = base.where(FieldReport.report_date <= date_to)
        if report_type is not None:
            base = base.where(FieldReport.report_type == report_type)
        if status is not None:
            base = base.where(FieldReport.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(FieldReport.report_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_by_date(
        self, project_id: uuid.UUID, report_date: date
    ) -> FieldReport | None:
        """Get a field report for a specific project and date."""
        stmt = select(FieldReport).where(
            FieldReport.project_id == project_id,
            FieldReport.report_date == report_date,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_month(
        self, project_id: uuid.UUID, year: int, month: int
    ) -> list[FieldReport]:
        """Get all reports for a project within a given month (calendar view)."""
        from datetime import date as date_cls

        first_day = date_cls(year, month, 1)
        if month == 12:
            last_day = date_cls(year + 1, 1, 1)
        else:
            last_day = date_cls(year, month + 1, 1)

        stmt = (
            select(FieldReport)
            .where(
                FieldReport.project_id == project_id,
                FieldReport.report_date >= first_day,
                FieldReport.report_date < last_day,
            )
            .order_by(FieldReport.report_date.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, report: FieldReport) -> FieldReport:
        """Insert a new field report."""
        self.session.add(report)
        await self.session.flush()
        return report

    async def update_fields(self, report_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a field report."""
        stmt = update(FieldReport).where(FieldReport.id == report_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, report_id: uuid.UUID) -> None:
        """Hard delete a field report."""
        report = await self.get_by_id(report_id)
        if report is not None:
            await self.session.delete(report)
            await self.session.flush()

    async def all_for_project(self, project_id: uuid.UUID) -> list[FieldReport]:
        """Return all field reports for a project (used for summary)."""
        stmt = select(FieldReport).where(FieldReport.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
