"""‌⁠‍HSE Advanced data access layer."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hse_advanced.models import (
    CorrectiveAction,
    HSEIncidentInvestigation,
    JobSafetyAnalysis,
    JSATemplate,
    PermitToWork,
    PPEIssue,
    SafetyAudit,
    SafetyAuditFinding,
    SafetyCertification,
    ToolboxAttendance,
    ToolboxTalk,
    ToolboxTopic,
)


class _BaseRepo:
    """‌⁠‍Common CRUD helpers — kept simple, not a generic ORM."""

    model = None  # type: ignore[assignment]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return await self.session.get(self.model, item_id)

    async def create(self, obj):  # type: ignore[no-untyped-def]
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        stmt = update(self.model).where(self.model.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, item_id: uuid.UUID) -> None:
        obj = await self.get_by_id(item_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


# ── Investigation ────────────────────────────────────────────────────────────


class InvestigationRepository(_BaseRepo):
    """‌⁠‍Data access for HSEIncidentInvestigation."""

    model = HSEIncidentInvestigation

    async def list_for_incident(
        self, incident_ref: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[HSEIncidentInvestigation], int]:
        base = select(HSEIncidentInvestigation).where(HSEIncidentInvestigation.incident_ref == incident_ref)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(HSEIncidentInvestigation.started_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[HSEIncidentInvestigation], int]:
        """List investigations whose incident belongs to the given project.

        Investigations are keyed by ``incident_ref`` rather than directly by
        project (so the column stays loosely coupled to the safety module);
        but a project-scoped HSE dashboard still needs to list "all
        investigations for this project". We resolve that via a sub-query
        on ``oe_safety_incident.project_id`` using core-SQL so this module
        does not need to import the safety SQLAlchemy model. If the safety
        table is not present (module disabled), the query returns no rows
        gracefully instead of raising.
        """
        from sqlalchemy import text

        try:
            incident_ids_stmt = text(
                "SELECT id FROM oe_safety_incident WHERE project_id = :pid",
            )
            result = await self.session.execute(
                incident_ids_stmt,
                {"pid": str(project_id)},
            )
            incident_ids = [row[0] for row in result.all()]
        except Exception:
            # Safety module not present / table missing — degrade to empty.
            return [], 0

        if not incident_ids:
            return [], 0

        base = select(HSEIncidentInvestigation).where(
            HSEIncidentInvestigation.incident_ref.in_(incident_ids),
        )
        if status is not None:
            base = base.where(HSEIncidentInvestigation.status == status)
        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        stmt = base.order_by(HSEIncidentInvestigation.started_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total


# ── JSA ──────────────────────────────────────────────────────────────────────


class JSARepository(_BaseRepo):
    """Data access for JobSafetyAnalysis."""

    model = JobSafetyAnalysis

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[JobSafetyAnalysis], int]:
        base = select(JobSafetyAnalysis).where(JobSafetyAnalysis.project_id == project_id)
        if status is not None:
            base = base.where(JobSafetyAnalysis.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(JobSafetyAnalysis.created_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total


# ── PTW ──────────────────────────────────────────────────────────────────────


class PermitRepository(_BaseRepo):
    """Data access for PermitToWork."""

    model = PermitToWork

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        permit_type: str | None = None,
    ) -> tuple[list[PermitToWork], int]:
        base = select(PermitToWork).where(PermitToWork.project_id == project_id)
        if status is not None:
            base = base.where(PermitToWork.status == status)
        if permit_type is not None:
            base = base.where(PermitToWork.permit_type == permit_type)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(PermitToWork.work_start.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def active_today(self, project_id: uuid.UUID) -> list[PermitToWork]:
        """Return all permits in `active` status whose window covers now."""
        now = datetime.now(UTC)
        stmt = select(PermitToWork).where(
            PermitToWork.project_id == project_id,
            PermitToWork.status == "active",
            PermitToWork.work_start <= now,
            PermitToWork.work_end >= now,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_status(self, project_id: uuid.UUID, status: str) -> int:
        stmt = select(func.count()).select_from(
            select(PermitToWork)
            .where(
                PermitToWork.project_id == project_id,
                PermitToWork.status == status,
            )
            .subquery()
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


# ── Toolbox ─────────────────────────────────────────────────────────────────


class ToolboxTalkRepository(_BaseRepo):
    """Data access for ToolboxTalk."""

    model = ToolboxTalk

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ToolboxTalk], int]:
        base = select(ToolboxTalk).where(ToolboxTalk.project_id == project_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ToolboxTalk.conducted_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def count_in_month(self, project_id: uuid.UUID, ref_date: date) -> int:
        first = datetime(ref_date.year, ref_date.month, 1, tzinfo=UTC)
        if ref_date.month == 12:
            last = datetime(ref_date.year + 1, 1, 1, tzinfo=UTC)
        else:
            last = datetime(ref_date.year, ref_date.month + 1, 1, tzinfo=UTC)
        base = select(ToolboxTalk).where(
            ToolboxTalk.project_id == project_id,
            ToolboxTalk.conducted_at >= first,
            ToolboxTalk.conducted_at < last,
        )
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        return int(total or 0)


class ToolboxAttendanceRepository(_BaseRepo):
    """Data access for ToolboxAttendance."""

    model = ToolboxAttendance

    async def list_for_talk(self, talk_id: uuid.UUID) -> list[ToolboxAttendance]:
        stmt = select(ToolboxAttendance).where(ToolboxAttendance.toolbox_talk_id == talk_id)
        return list((await self.session.execute(stmt)).scalars().all())


class ToolboxTopicRepository(_BaseRepo):
    """Data access for ToolboxTopic (library)."""

    model = ToolboxTopic

    async def list_topics(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        is_active: bool | None = True,
        language: str | None = None,
        # Legacy alias retained so older callers / test stubs don't break.
        active_only: bool | None = None,
    ) -> tuple[list[ToolboxTopic], int]:
        if active_only is not None:
            is_active = True if active_only else None
        base = select(ToolboxTopic)
        if is_active is True:
            base = base.where(ToolboxTopic.is_active.is_(True))
        elif is_active is False:
            base = base.where(ToolboxTopic.is_active.is_(False))
        if language:
            base = base.where(ToolboxTopic.language == language)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(ToolboxTopic.code).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def get_by_code(self, code: str) -> ToolboxTopic | None:
        stmt = select(ToolboxTopic).where(ToolboxTopic.code == code)
        return (await self.session.execute(stmt)).scalars().first()


# ── PPE ─────────────────────────────────────────────────────────────────────


class PPEIssueRepository(_BaseRepo):
    """Data access for PPEIssue."""

    model = PPEIssue

    async def list_issues(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        recipient_user_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[PPEIssue], int]:
        base = select(PPEIssue)
        if recipient_user_id is not None:
            base = base.where(PPEIssue.recipient_user_id == recipient_user_id)
        if status is not None:
            base = base.where(PPEIssue.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(PPEIssue.issued_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total


# ── Audit ───────────────────────────────────────────────────────────────────


class AuditRepository(_BaseRepo):
    """Data access for SafetyAudit."""

    model = SafetyAudit

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[SafetyAudit], int]:
        base = select(SafetyAudit).where(SafetyAudit.project_id == project_id)
        if status is not None:
            base = base.where(SafetyAudit.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(SafetyAudit.conducted_at.desc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total


class AuditFindingRepository(_BaseRepo):
    """Data access for SafetyAuditFinding."""

    model = SafetyAuditFinding

    async def list_for_audit(self, audit_id: uuid.UUID) -> list[SafetyAuditFinding]:
        stmt = select(SafetyAuditFinding).where(SafetyAuditFinding.audit_id == audit_id)
        return list((await self.session.execute(stmt)).scalars().all())


# ── CAPA ────────────────────────────────────────────────────────────────────


class CAPARepository(_BaseRepo):
    """Data access for CorrectiveAction."""

    model = CorrectiveAction

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[CorrectiveAction], int]:
        base = select(CorrectiveAction).where(CorrectiveAction.project_id == project_id)
        if status is not None:
            base = base.where(CorrectiveAction.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(CorrectiveAction.target_date.asc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def overdue(self, project_id: uuid.UUID, today: date) -> list[CorrectiveAction]:
        stmt = select(CorrectiveAction).where(
            CorrectiveAction.project_id == project_id,
            CorrectiveAction.target_date < today,
            CorrectiveAction.status.in_(["open", "in_progress", "overdue"]),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_status(self, project_id: uuid.UUID, status: str) -> int:
        stmt = select(func.count()).select_from(
            select(CorrectiveAction)
            .where(
                CorrectiveAction.project_id == project_id,
                CorrectiveAction.status == status,
            )
            .subquery()
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


# ── Certifications ─────────────────────────────────────────────────────────


class CertificationRepository(_BaseRepo):
    """Data access for SafetyCertification."""

    model = SafetyCertification

    async def list_certs(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        owner_user_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[SafetyCertification], int]:
        base = select(SafetyCertification)
        if owner_user_id is not None:
            base = base.where(SafetyCertification.owner_user_id == owner_user_id)
        if status is not None:
            base = base.where(SafetyCertification.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(SafetyCertification.valid_until.asc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def expiring_within(self, days: int, today: date) -> list[SafetyCertification]:
        limit_date = today + timedelta(days=days)
        stmt = select(SafetyCertification).where(
            SafetyCertification.status == "valid",
            SafetyCertification.valid_until <= limit_date,
            SafetyCertification.valid_until >= today,
        )
        return list((await self.session.execute(stmt)).scalars().all())


# ── JSA templates ──────────────────────────────────────────────────────────


class JSATemplateRepository(_BaseRepo):
    """Data access for tenant-level :class:`JSATemplate` rows."""

    model = JSATemplate

    async def list_templates(
        self,
        *,
        trade: str | None = None,
        region: str | None = None,
        is_active: bool | None = True,
        offset: int = 0,
        limit: int = 100,
        # Legacy alias retained so test stubs / older callers don't break.
        active_only: bool | None = None,
    ) -> tuple[list[JSATemplate], int]:
        if active_only is not None:
            is_active = True if active_only else None
        base = select(JSATemplate)
        if trade is not None:
            base = base.where(JSATemplate.trade == trade)
        if region is not None:
            base = base.where(JSATemplate.region == region)
        if is_active is True:
            base = base.where(JSATemplate.is_active.is_(True))
        elif is_active is False:
            base = base.where(JSATemplate.is_active.is_(False))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(JSATemplate.trade.asc(), JSATemplate.name.asc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total
