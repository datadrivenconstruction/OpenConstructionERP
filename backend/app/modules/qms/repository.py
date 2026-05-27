"""‌⁠‍QMS data-access layer.

Thin wrapper around :class:`AsyncSession` providing CRUD helpers per
entity. All update writes use ``UPDATE ... WHERE id = :id`` to avoid
the SQLite single-writer lock that ``session.flush()`` on dirty
attributes would otherwise hold.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qms.models import (
    QMSNCR,
    ITPItem,
    ITPPlan,
    ITPTemplate,
    QMSAudit,
    QMSAuditFinding,
    QMSAuditLog,
    QMSCalibration,
    QMSInspection,
    QMSInspectionSignature,
    QMSNCRAction,
    QMSPunchItem,
)


class QMSRepository:
    """‌⁠‍Async CRUD for every QMS model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── ITPPlan ────────────────────────────────────────────────────────

    async def get_itp_plan(self, plan_id: uuid.UUID) -> ITPPlan | None:
        return await self.session.get(ITPPlan, plan_id)

    async def list_itp_plans(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ITPPlan], int]:
        base = select(ITPPlan).where(ITPPlan.project_id == project_id)
        if status:
            base = base.where(ITPPlan.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        result = await self.session.execute(base.order_by(ITPPlan.created_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def create_itp_plan(self, plan: ITPPlan) -> ITPPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def update_itp_plan_fields(self, plan_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(ITPPlan).where(ITPPlan.id == plan_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    # ── ITPItem ────────────────────────────────────────────────────────

    async def get_itp_item(self, item_id: uuid.UUID) -> ITPItem | None:
        return await self.session.get(ITPItem, item_id)

    async def list_itp_items(self, plan_id: uuid.UUID) -> list[ITPItem]:
        result = await self.session.execute(
            select(ITPItem).where(ITPItem.itp_plan_id == plan_id).order_by(ITPItem.sequence.asc())
        )
        return list(result.scalars().all())

    async def create_itp_item(self, item: ITPItem) -> ITPItem:
        self.session.add(item)
        await self.session.flush()
        return item

    # ── Inspection ─────────────────────────────────────────────────────

    async def get_inspection(self, inspection_id: uuid.UUID) -> QMSInspection | None:
        return await self.session.get(QMSInspection, inspection_id)

    async def list_inspections(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[QMSInspection], int]:
        base = select(QMSInspection).where(QMSInspection.project_id == project_id)
        if status:
            base = base.where(QMSInspection.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        result = await self.session.execute(base.order_by(QMSInspection.created_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def create_inspection(self, inspection: QMSInspection) -> QMSInspection:
        self.session.add(inspection)
        await self.session.flush()
        return inspection

    async def update_inspection_fields(
        self,
        inspection_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        stmt = update(QMSInspection).where(QMSInspection.id == inspection_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_signatures(
        self,
        inspection_id: uuid.UUID,
    ) -> list[QMSInspectionSignature]:
        result = await self.session.execute(
            select(QMSInspectionSignature)
            .where(QMSInspectionSignature.inspection_id == inspection_id)
            .order_by(QMSInspectionSignature.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_signature(
        self,
        sig: QMSInspectionSignature,
    ) -> QMSInspectionSignature:
        self.session.add(sig)
        await self.session.flush()
        return sig

    # ── NCR ────────────────────────────────────────────────────────────

    async def get_ncr(self, ncr_id: uuid.UUID) -> QMSNCR | None:
        return await self.session.get(QMSNCR, ncr_id)

    async def list_ncrs(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        severity: str | None = None,
    ) -> tuple[list[QMSNCR], int]:
        base = select(QMSNCR).where(QMSNCR.project_id == project_id)
        if status:
            base = base.where(QMSNCR.status == status)
        if severity:
            base = base.where(QMSNCR.severity == severity)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        result = await self.session.execute(base.order_by(QMSNCR.created_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def create_ncr(self, ncr: QMSNCR) -> QMSNCR:
        self.session.add(ncr)
        await self.session.flush()
        return ncr

    async def update_ncr_fields(self, ncr_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(QMSNCR).where(QMSNCR.id == ncr_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_ncr_actions(self, ncr_id: uuid.UUID) -> list[QMSNCRAction]:
        result = await self.session.execute(
            select(QMSNCRAction).where(QMSNCRAction.ncr_id == ncr_id).order_by(QMSNCRAction.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_ncr_action(self, action_id: uuid.UUID) -> QMSNCRAction | None:
        return await self.session.get(QMSNCRAction, action_id)

    async def create_ncr_action(self, action: QMSNCRAction) -> QMSNCRAction:
        self.session.add(action)
        await self.session.flush()
        return action

    async def update_ncr_action_fields(
        self,
        action_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        stmt = update(QMSNCRAction).where(QMSNCRAction.id == action_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    # ── PunchItem ──────────────────────────────────────────────────────

    async def get_punch(self, punch_id: uuid.UUID) -> QMSPunchItem | None:
        return await self.session.get(QMSPunchItem, punch_id)

    async def list_punch(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[QMSPunchItem], int]:
        base = select(QMSPunchItem).where(QMSPunchItem.project_id == project_id)
        if status:
            base = base.where(QMSPunchItem.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        result = await self.session.execute(base.order_by(QMSPunchItem.created_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def create_punch(self, punch: QMSPunchItem) -> QMSPunchItem:
        self.session.add(punch)
        await self.session.flush()
        return punch

    async def update_punch_fields(self, punch_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(QMSPunchItem).where(QMSPunchItem.id == punch_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def count_open_punch(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            QMSPunchItem.project_id == project_id,
            QMSPunchItem.status.notin_(("closed", "rejected")),
        )
        return (await self.session.execute(stmt)).scalar_one()

    # ── Audit ──────────────────────────────────────────────────────────

    async def get_audit(self, audit_id: uuid.UUID) -> QMSAudit | None:
        return await self.session.get(QMSAudit, audit_id)

    async def list_audits(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[QMSAudit], int]:
        base = select(QMSAudit).where(QMSAudit.project_id == project_id)
        if status:
            base = base.where(QMSAudit.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        result = await self.session.execute(base.order_by(QMSAudit.created_at.desc()).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def create_audit(self, audit: QMSAudit) -> QMSAudit:
        self.session.add(audit)
        await self.session.flush()
        return audit

    async def update_audit_fields(self, audit_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(QMSAudit).where(QMSAudit.id == audit_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_findings(self, audit_id: uuid.UUID) -> list[QMSAuditFinding]:
        result = await self.session.execute(
            select(QMSAuditFinding)
            .where(QMSAuditFinding.audit_id == audit_id)
            .order_by(QMSAuditFinding.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_finding(self, finding_id: uuid.UUID) -> QMSAuditFinding | None:
        return await self.session.get(QMSAuditFinding, finding_id)

    async def create_finding(self, finding: QMSAuditFinding) -> QMSAuditFinding:
        self.session.add(finding)
        await self.session.flush()
        return finding

    async def update_finding_fields(
        self,
        finding_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        stmt = update(QMSAuditFinding).where(QMSAuditFinding.id == finding_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    # ── Analytics helpers ──────────────────────────────────────────────

    async def sum_ncr_cost_impact(self, project_id: uuid.UUID) -> Any:
        """‌⁠‍Sum cost_impact_amount for non-cancelled NCRs in a project."""
        stmt = select(func.coalesce(func.sum(QMSNCR.cost_impact_amount), 0)).where(
            QMSNCR.project_id == project_id,
            QMSNCR.status != "cancelled",
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_inspections(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(QMSInspection.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one()

    async def count_inspections_passed(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            QMSInspection.project_id == project_id,
            QMSInspection.status == "passed",
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def list_inspections_in_period(
        self,
        project_id: uuid.UUID,
        *,
        period_start_iso: str,
        period_end_iso: str,
    ) -> list[QMSInspection]:
        """Inspections whose ``performed_at`` ISO string falls in the window.

        We rely on lexical ordering of ISO-8601 strings which preserves
        chronology for any non-mixed-timezone dataset.
        """
        stmt = (
            select(QMSInspection)
            .where(
                QMSInspection.project_id == project_id,
                QMSInspection.performed_at.is_not(None),
                QMSInspection.performed_at >= period_start_iso,
                QMSInspection.performed_at < period_end_iso,
            )
            .order_by(QMSInspection.performed_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_open_findings_in_period(
        self,
        project_id: uuid.UUID,
        *,
        date_from_iso: str,
        date_to_iso: str,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(QMSAuditFinding)
            .join(QMSAudit, QMSAuditFinding.audit_id == QMSAudit.id)
            .where(
                QMSAudit.project_id == project_id,
                QMSAuditFinding.status != "closed",
                QMSAuditFinding.created_at >= date_from_iso,
                QMSAuditFinding.created_at < date_to_iso,
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_closed_findings_in_period(
        self,
        project_id: uuid.UUID,
        *,
        date_from_iso: str,
        date_to_iso: str,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(QMSAuditFinding)
            .join(QMSAudit, QMSAuditFinding.audit_id == QMSAudit.id)
            .where(
                QMSAudit.project_id == project_id,
                QMSAuditFinding.status == "closed",
                QMSAuditFinding.closed_at >= date_from_iso,
                QMSAuditFinding.closed_at < date_to_iso,
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_audits_in_period(
        self,
        project_id: uuid.UUID,
        *,
        date_from_iso: str,
        date_to_iso: str,
    ) -> int:
        stmt = select(func.count()).where(
            QMSAudit.project_id == project_id,
            QMSAudit.status.in_(("completed", "closed")),
            QMSAudit.performed_at.is_not(None),
            QMSAudit.performed_at >= date_from_iso,
            QMSAudit.performed_at < date_to_iso,
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_ncrs_in_period(
        self,
        project_id: uuid.UUID,
        *,
        date_from_iso: str,
        date_to_iso: str,
        only_closed: bool = False,
    ) -> int:
        conditions = [
            QMSNCR.project_id == project_id,
            QMSNCR.raised_at.is_not(None),
            QMSNCR.raised_at >= date_from_iso,
            QMSNCR.raised_at < date_to_iso,
        ]
        if only_closed:
            conditions.append(QMSNCR.status == "closed")
        stmt = select(func.count()).where(and_(*conditions))
        return (await self.session.execute(stmt)).scalar_one()

    # ── ITPTemplate ────────────────────────────────────────────────────

    async def get_itp_template(self, tpl_id: uuid.UUID) -> ITPTemplate | None:
        return await self.session.get(ITPTemplate, tpl_id)

    async def list_itp_templates(
        self,
        *,
        csi_division: str | None = None,
        work_type: str | None = None,
        active_only: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[ITPTemplate], int]:
        base = select(ITPTemplate)
        if csi_division:
            base = base.where(ITPTemplate.csi_division == csi_division)
        if work_type:
            base = base.where(ITPTemplate.work_type == work_type)
        if active_only:
            base = base.where(ITPTemplate.is_active.is_(True))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = (
            base.order_by(
                ITPTemplate.csi_division.asc(),
                ITPTemplate.work_type.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def create_itp_template(self, tpl: ITPTemplate) -> ITPTemplate:
        self.session.add(tpl)
        await self.session.flush()
        return tpl

    async def update_itp_template_fields(
        self,
        tpl_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        stmt = update(ITPTemplate).where(ITPTemplate.id == tpl_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_itp_template(self, tpl_id: uuid.UUID) -> None:
        tpl = await self.get_itp_template(tpl_id)
        if tpl is not None:
            await self.session.delete(tpl)
            await self.session.flush()

    # ── Calibration ───────────────────────────────────────────────────

    async def get_calibration(self, cal_id: uuid.UUID) -> QMSCalibration | None:
        return await self.session.get(QMSCalibration, cal_id)

    async def list_calibrations(
        self,
        *,
        project_id: uuid.UUID | None = None,
        instrument_type: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[QMSCalibration], int]:
        base = select(QMSCalibration)
        if project_id is not None:
            base = base.where(QMSCalibration.project_id == project_id)
        if instrument_type:
            base = base.where(QMSCalibration.instrument_type == instrument_type)
        if status:
            base = base.where(QMSCalibration.status == status)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(QMSCalibration.valid_until.asc()).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def create_calibration(self, cal: QMSCalibration) -> QMSCalibration:
        self.session.add(cal)
        await self.session.flush()
        return cal

    async def update_calibration_fields(
        self,
        cal_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        stmt = update(QMSCalibration).where(QMSCalibration.id == cal_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_calibration(self, cal_id: uuid.UUID) -> None:
        cal = await self.get_calibration(cal_id)
        if cal is not None:
            await self.session.delete(cal)
            await self.session.flush()

    async def expiring_calibrations(
        self,
        *,
        before: date,
        project_id: uuid.UUID | None = None,
    ) -> list[QMSCalibration]:
        """Calibrations with status=valid and valid_until <= ``before``."""
        stmt = select(QMSCalibration).where(
            QMSCalibration.status == "valid",
            QMSCalibration.valid_until <= before,
        )
        if project_id is not None:
            stmt = stmt.where(QMSCalibration.project_id == project_id)
        stmt = stmt.order_by(QMSCalibration.valid_until.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    # ── Audit log (FSM transition trail) ───────────────────────────────

    async def append_audit(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        tenant_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        old_status: str | None = None,
        new_status: str | None = None,
        reason: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> QMSAuditLog:
        """Append a single audit-log row for an FSM transition.

        ``before_state`` / ``after_state`` are stored verbatim as JSON so
        the caller controls the schema. Empty dicts are fine and match
        the column ``server_default``.
        """
        entry = QMSAuditLog(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_user_id=actor_user_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            before_state=before_state or {},
            after_state=after_state or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_audit_log(
        self,
        entity_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[QMSAuditLog]:
        """Return audit-log rows for one ``entity_id`` in insertion order.

        ``entity_type`` filters by category (e.g. ``"ncr"``,
        ``"inspection"``) so callers don't get cross-category collisions
        if two entity classes ever share a UUID space.
        """
        stmt = select(QMSAuditLog).where(QMSAuditLog.entity_id == entity_id)
        if entity_type is not None:
            stmt = stmt.where(QMSAuditLog.entity_type == entity_type)
        stmt = stmt.order_by(QMSAuditLog.created_at.asc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_audit_for_entity(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> list[QMSAuditLog]:
        """Alias kept for symmetry with the other QMS repositories.

        Same behaviour as :meth:`list_audit_log` with the parameters in
        the order most callers prefer (``type, id``).
        """
        return await self.list_audit_log(
            entity_id,
            entity_type=entity_type,
            offset=offset,
            limit=limit,
        )

    async def purge_audit_for_tenant(self, tenant_id: uuid.UUID) -> int:
        """Delete every audit-log row for ``tenant_id`` (GDPR forget).

        Returns the number of rows removed so the caller can log it.
        """
        stmt = delete(QMSAuditLog).where(QMSAuditLog.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    # Alias matching the brief's naming.
    purge_for_tenant = purge_audit_for_tenant
