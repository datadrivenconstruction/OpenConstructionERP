"""Validation data access layer.

All database queries for validation reports live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.validation.models import ValidationReport


class ValidationReportRepository:
    """Data access for ValidationReport model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        target_type: str | None = None,
        limit: int = 50,
    ) -> list[ValidationReport]:
        """List validation reports for a project, optionally filtered by target_type.

        Results are ordered by created_at descending (newest first).
        """
        stmt = (
            select(ValidationReport)
            .where(ValidationReport.project_id == project_id)
            .order_by(ValidationReport.created_at.desc())
            .limit(limit)
        )
        if target_type:
            stmt = stmt.where(ValidationReport.target_type == target_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, report_id: uuid.UUID) -> ValidationReport | None:
        """Get a single validation report by ID."""
        return await self.session.get(ValidationReport, report_id)

    async def get_latest_for_target(
        self,
        target_type: str,
        target_id: str,
    ) -> ValidationReport | None:
        """Get the most recent validation report for a specific target."""
        stmt = (
            select(ValidationReport)
            .where(
                ValidationReport.target_type == target_type,
                ValidationReport.target_id == target_id,
            )
            .order_by(ValidationReport.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, report: ValidationReport) -> ValidationReport:
        """Persist a new validation report."""
        self.session.add(report)
        await self.session.flush()
        return report

    async def delete(self, report_id: uuid.UUID) -> bool:
        """Delete a validation report. Returns True if found and deleted."""
        report = await self.session.get(ValidationReport, report_id)
        if report is None:
            return False
        await self.session.delete(report)
        await self.session.flush()
        return True
