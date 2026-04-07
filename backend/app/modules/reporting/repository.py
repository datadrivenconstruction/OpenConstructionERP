"""Reporting data access layer."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reporting.models import GeneratedReport, KPISnapshot, ReportTemplate


class KPISnapshotRepository:
    """Data access for KPISnapshot models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_latest(self, project_id: uuid.UUID) -> KPISnapshot | None:
        """Get the most recent KPI snapshot for a project."""
        stmt = (
            select(KPISnapshot)
            .where(KPISnapshot.project_id == project_id)
            .order_by(KPISnapshot.snapshot_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_history(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[KPISnapshot], int]:
        """List KPI snapshots for a project ordered by date descending."""
        base = select(KPISnapshot).where(KPISnapshot.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(KPISnapshot.snapshot_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, snapshot: KPISnapshot) -> KPISnapshot:
        """Insert a new KPI snapshot."""
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot


class ReportTemplateRepository:
    """Data access for ReportTemplate models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, template_id: uuid.UUID) -> ReportTemplate | None:
        """Get template by ID."""
        return await self.session.get(ReportTemplate, template_id)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ReportTemplate], int]:
        """List all report templates."""
        base = select(ReportTemplate)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ReportTemplate.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, template: ReportTemplate) -> ReportTemplate:
        """Insert a new report template."""
        self.session.add(template)
        await self.session.flush()
        return template

    async def count_system(self) -> int:
        """Count system templates (for seed idempotency check)."""
        stmt = (
            select(func.count())
            .select_from(ReportTemplate)
            .where(ReportTemplate.is_system.is_(True))
        )
        return (await self.session.execute(stmt)).scalar_one()


class GeneratedReportRepository:
    """Data access for GeneratedReport models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, report_id: uuid.UUID) -> GeneratedReport | None:
        """Get generated report by ID."""
        return await self.session.get(GeneratedReport, report_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[GeneratedReport], int]:
        """List generated reports for a project."""
        base = select(GeneratedReport).where(GeneratedReport.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(GeneratedReport.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, report: GeneratedReport) -> GeneratedReport:
        """Insert a new generated report."""
        self.session.add(report)
        await self.session.flush()
        return report
