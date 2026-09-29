# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo seed data for the QMS module.

Creates an end-to-end sample for a single project:
    * 1 ITP plan with 5 control points
    * 3 inspections (1 passed / 1 failed / 1 conditional)
    * 2 NCRs (1 open, 1 escalated to a variation order)
    * 8 punch items spread across the lifecycle statuses
    * 1 completed audit with 3 findings

The helper is idempotent at the row level - re-running ``seed_qms``
re-inserts new rows. Wrap in a unique-project filter externally if you
need true idempotency.

The rows carry no seed marker, so :func:`seeded_row_ids` recognises them by
content instead. Both read the module constants below, which is what keeps the
recognition from drifting away from what the seeder writes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qms.models import (
    QMSNCR,
    ITPItem,
    ITPPlan,
    QMSAudit,
    QMSAuditFinding,
    QMSInspection,
    QMSPunchItem,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_PLAN = {"name": "Concrete pour - slab on grade", "work_type": "concrete", "wbs_ref": "WBS.03.30"}

# (control point, hold/witness kind, responsible role, signatories)
_ITP_ITEMS: tuple[tuple[str, str, str, int], ...] = (
    ("Formwork inspection", "hold", "GC", 2),
    ("Rebar inspection", "hold", "GC", 2),
    ("Pre-pour clean-up", "witness", "GC", 1),
    ("Slump test", "witness", "QC", 1),
    ("Cube sampling", "review", "lab", 1),
)
_ITP_ITEM_CRITERIA = "Per project specification"

_INSPECTION_LOCATION = "Grid A1-A4"
# (index into _ITP_ITEMS, status, notes, performed)
_INSPECTIONS: tuple[tuple[int, str, str, bool], ...] = (
    (0, "passed", "All formwork ties correctly torqued.", True),
    (1, "failed", "Cover blocks below 25mm in section.", True),
    (2, "conditional", "Awaiting re-cleanup of joint surface.", False),
)

# (title, description, severity)
_NCR_OPEN = ("Cover below spec", "Rebar cover < 25mm in slab section A2.", "major")
_NCR_VARIATION = (
    "Concrete strength below 28-day target",
    "Cube test 23MPa vs spec 30MPa - remediation required.",
    "critical",
)
_NCR_VARIATION_ROOT_CAUSE = "Supplier batch error"
_NCR_VARIATION_AMOUNT = Decimal("15000.00")

# (title, status, severity, category)
_PUNCH_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    ("Wall paint scuff in lobby", "open", "minor", "finishes"),
    ("Door latch sticks 03-12", "assigned", "minor", "architectural"),
    ("HVAC noise in 04-08", "in_progress", "major", "mechanical"),
    ("Outlet misalignment 02-04", "ready_for_inspection", "minor", "electrical"),
    ("Crack in slab corner", "rejected", "major", "structure"),
    ("Window seal gap 05-10", "open", "minor", "finishes"),
    ("Door hinge stiff 02-15", "open", "minor", "architectural"),
    ("Closeout: rework verified", "closed", "minor", "finishes"),
)

_AUDIT = {"audit_type": "internal", "audit_scope": "QMS process audit Q2", "standard_ref": "ISO 9001:2015"}
# (finding type, clause, description)
_AUDIT_FINDINGS: tuple[tuple[str, str, str], ...] = (
    ("observation", "8.5.1", "Record retention period inconsistent"),
    ("minor", "9.2", "Internal audit interval drifted"),
    ("major", "8.7", "Non-conforming output controls weak"),
)


async def seed_qms(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """Insert a complete demo dataset for QMS.

    Returns a small dict of created IDs the caller can use to verify
    or roll back.
    """
    project_id = project_id or uuid.uuid4()

    # 1) ITP plan + items
    plan = ITPPlan(
        project_id=project_id,
        name=_PLAN["name"],
        work_type=_PLAN["work_type"],
        wbs_ref=_PLAN["wbs_ref"],
        status="active",
        version=1,
        created_by=None,
    )
    session.add(plan)
    await session.flush()

    items: list[ITPItem] = []
    for seq, (name, kind, role, sigs) in enumerate(_ITP_ITEMS, start=10):
        item = ITPItem(
            itp_plan_id=plan.id,
            sequence=seq,
            control_point_name=name,
            criteria=_ITP_ITEM_CRITERIA,
            frequency="per pour",
            method="visual / measurement",
            acceptance_criteria="No defects observed",
            hold_witness_point=kind,
            responsible_role=role,
            signatories_required=sigs,
        )
        items.append(item)
    session.add_all(items)
    await session.flush()

    # 2) Inspections - 1 passed / 1 failed / 1 conditional
    inspections = [
        QMSInspection(
            itp_item_id=items[item_index].id,
            project_id=project_id,
            location_ref=_INSPECTION_LOCATION,
            inspector_user_id=None,
            scheduled_at=_now_iso(),
            performed_at=_now_iso() if performed else None,
            status=status,
            notes=notes,
            photos_json=[],
        )
        for item_index, status, notes, performed in _INSPECTIONS
    ]
    insp_passed, insp_failed, insp_cond = inspections
    session.add_all(inspections)
    await session.flush()

    # 3) NCRs - 1 open, 1 escalated to variation
    ncr_open = QMSNCR(
        project_id=project_id,
        raised_at=_now_iso(),
        title=_NCR_OPEN[0],
        description=_NCR_OPEN[1],
        severity=_NCR_OPEN[2],
        root_cause=None,
        status="open",
        cost_impact_currency="",
        cost_impact_amount=None,
        linked_inspection_id=insp_failed.id,
    )
    ncr_var = QMSNCR(
        project_id=project_id,
        raised_at=_now_iso(),
        title=_NCR_VARIATION[0],
        description=_NCR_VARIATION[1],
        severity=_NCR_VARIATION[2],
        root_cause=_NCR_VARIATION_ROOT_CAUSE,
        status="action_pending",
        cost_impact_currency="EUR",
        cost_impact_amount=_NCR_VARIATION_AMOUNT,
        linked_variation_id=uuid.uuid4(),
    )
    session.add_all([ncr_open, ncr_var])
    await session.flush()

    # 4) Punch items - eight across the lifecycle
    punches: list[QMSPunchItem] = []
    for title, st, sev, cat in _PUNCH_ITEMS:
        punches.append(
            QMSPunchItem(
                project_id=project_id,
                raised_at=_now_iso(),
                title=title,
                description=None,
                room_ref=None,
                drawing_ref=None,
                bim_element_ref=None,
                status=st,
                severity=sev,
                assigned_to=None,
                due_date=None,
                closed_at=_now_iso() if st == "closed" else None,
                photos_json=[],
                source="manual",
                category=cat,
            )
        )
    session.add_all(punches)
    await session.flush()

    # 5) Audit + 3 findings
    audit = QMSAudit(
        project_id=project_id,
        audit_type=_AUDIT["audit_type"],
        planned_date=_now_iso(),
        performed_at=_now_iso(),
        auditor_user_id=None,
        audit_scope=_AUDIT["audit_scope"],
        standard_ref=_AUDIT["standard_ref"],
        status="completed",
        overall_rating=4,
    )
    session.add(audit)
    await session.flush()

    findings: list[QMSAuditFinding] = []
    for ft, clause, desc in _AUDIT_FINDINGS:
        findings.append(
            QMSAuditFinding(
                audit_id=audit.id,
                finding_type=ft,
                description=desc,
                clause_ref=clause,
                corrective_action_required="See CAPA register",
                status="open",
                due_date=None,
            )
        )
    session.add_all(findings)
    await session.flush()

    return {
        "project_id": project_id,
        "itp_plan_id": plan.id,
        "itp_item_ids": [i.id for i in items],
        "inspection_ids": [insp_passed.id, insp_failed.id, insp_cond.id],
        "ncr_ids": [ncr_open.id, ncr_var.id],
        "punch_ids": [p.id for p in punches],
        "audit_id": audit.id,
        "finding_ids": [f.id for f in findings],
    }


async def seeded_row_ids(session: AsyncSession, project_ids: list[uuid.UUID]) -> list[tuple[type, list, str]]:
    """Rows in ``project_ids`` whose content is exactly what :func:`seed_qms` writes.

    Every match compares several fields against the constants the seeder
    writes from, never a title alone: a person's punch item that shares a
    title but differs in severity or category, or has been assigned to
    somebody, is not matched. A plan matches only with exactly the seeded five
    control points, an audit only with exactly the seeded three findings.

    Returned in an order PostgreSQL can delete: NCRs point at inspections
    without a foreign key, inspections at ITP items (SET NULL), items belong to
    their plan (CASCADE), findings to their audit (CASCADE).

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []

    item_names = sorted(name for name, _kind, _role, _sigs in _ITP_ITEMS)
    plan_ids: list[uuid.UUID] = []
    item_ids: set[uuid.UUID] = set()
    candidate_plans = (
        (
            await session.execute(
                select(ITPPlan.id).where(
                    ITPPlan.project_id.in_(project_ids),
                    ITPPlan.name == _PLAN["name"],
                    ITPPlan.work_type == _PLAN["work_type"],
                    ITPPlan.wbs_ref == _PLAN["wbs_ref"],
                    ITPPlan.created_by.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for plan_id in candidate_plans:
        rows = (
            await session.execute(
                select(ITPItem.id, ITPItem.control_point_name, ITPItem.criteria).where(ITPItem.itp_plan_id == plan_id)
            )
        ).all()
        if sorted(r.control_point_name for r in rows) == item_names and all(
            r.criteria == _ITP_ITEM_CRITERIA for r in rows
        ):
            plan_ids.append(plan_id)
            item_ids.update(r.id for r in rows)

    # Status is left out on purpose: a seeded inspection a person then moved
    # on is still the seed's row, and the plan it hangs off is removed too.
    inspection_specs = {(_INSPECTION_LOCATION, notes) for _i, _status, notes, _p in _INSPECTIONS}
    inspection_rows = (
        await session.execute(
            select(
                QMSInspection.id,
                QMSInspection.location_ref,
                QMSInspection.notes,
                QMSInspection.itp_item_id,
                QMSInspection.inspector_user_id,
            ).where(QMSInspection.project_id.in_(project_ids))
        )
    ).all()
    inspections = [
        r.id
        for r in inspection_rows
        if (r.location_ref, r.notes) in inspection_specs and r.itp_item_id in item_ids and r.inspector_user_id is None
    ]

    ncr_specs = {_NCR_OPEN, _NCR_VARIATION}
    ncr_rows = (
        await session.execute(
            select(QMSNCR.id, QMSNCR.title, QMSNCR.description, QMSNCR.severity).where(
                QMSNCR.project_id.in_(project_ids)
            )
        )
    ).all()
    ncrs = [r.id for r in ncr_rows if (r.title, r.description, r.severity) in ncr_specs]

    punch_specs = {(title, sev, cat) for title, _st, sev, cat in _PUNCH_ITEMS}
    punch_rows = (
        await session.execute(
            select(
                QMSPunchItem.id,
                QMSPunchItem.title,
                QMSPunchItem.severity,
                QMSPunchItem.category,
                QMSPunchItem.source,
                QMSPunchItem.description,
                QMSPunchItem.assigned_to,
            ).where(QMSPunchItem.project_id.in_(project_ids))
        )
    ).all()
    punches = [
        r.id
        for r in punch_rows
        if (r.title, r.severity, r.category) in punch_specs
        and r.source == "manual"
        and r.description is None
        and r.assigned_to is None
    ]

    finding_descs = sorted(desc for _t, _c, desc in _AUDIT_FINDINGS)
    audits: list[uuid.UUID] = []
    candidate_audits = (
        (
            await session.execute(
                select(QMSAudit.id).where(
                    QMSAudit.project_id.in_(project_ids),
                    QMSAudit.audit_type == _AUDIT["audit_type"],
                    QMSAudit.audit_scope == _AUDIT["audit_scope"],
                    QMSAudit.standard_ref == _AUDIT["standard_ref"],
                    QMSAudit.auditor_user_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for audit_id in candidate_audits:
        descs = (
            (await session.execute(select(QMSAuditFinding.description).where(QMSAuditFinding.audit_id == audit_id)))
            .scalars()
            .all()
        )
        if sorted(descs) == finding_descs:
            audits.append(audit_id)

    return [
        (QMSNCR, ncrs, "qms_ncrs"),
        (QMSInspection, inspections, "qms_inspections"),
        (ITPPlan, plan_ids, "qms_itp_plans"),
        (QMSPunchItem, punches, "qms_punch_items"),
        (QMSAudit, audits, "qms_audits"),
    ]
