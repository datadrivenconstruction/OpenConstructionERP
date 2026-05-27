"""‌⁠‍Demo seed data for the QMS module.

Creates an end-to-end sample for a single project:
    * 1 ITP plan with 5 control points
    * 3 inspections (1 passed / 1 failed / 1 conditional)
    * 2 NCRs (1 open, 1 escalated to a variation order)
    * 8 punch items spread across the lifecycle statuses
    * 1 completed audit with 3 findings

The helper is idempotent at the row level — re-running ``seed_qms``
re-inserts new rows. Wrap in a unique-project filter externally if you
need true idempotency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

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


async def seed_qms(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """‌⁠‍Insert a complete demo dataset for QMS.

    Returns a small dict of created IDs the caller can use to verify
    or roll back.
    """
    project_id = project_id or uuid.uuid4()

    # 1) ITP plan + items
    plan = ITPPlan(
        project_id=project_id,
        name="Concrete pour — slab on grade",
        work_type="concrete",
        wbs_ref="WBS.03.30",
        status="active",
        version=1,
        created_by=None,
    )
    session.add(plan)
    await session.flush()

    item_specs = [
        ("Formwork inspection", "hold", "GC", 2),
        ("Rebar inspection", "hold", "GC", 2),
        ("Pre-pour clean-up", "witness", "GC", 1),
        ("Slump test", "witness", "QC", 1),
        ("Cube sampling", "review", "lab", 1),
    ]
    items: list[ITPItem] = []
    for seq, (name, kind, role, sigs) in enumerate(item_specs, start=10):
        item = ITPItem(
            itp_plan_id=plan.id,
            sequence=seq,
            control_point_name=name,
            criteria="Per project specification",
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

    # 2) Inspections — 1 passed / 1 failed / 1 conditional
    insp_passed = QMSInspection(
        itp_item_id=items[0].id,
        project_id=project_id,
        location_ref="Grid A1-A4",
        inspector_user_id=None,
        scheduled_at=_now_iso(),
        performed_at=_now_iso(),
        status="passed",
        notes="All formwork ties correctly torqued.",
        photos_json=[],
    )
    insp_failed = QMSInspection(
        itp_item_id=items[1].id,
        project_id=project_id,
        location_ref="Grid A1-A4",
        inspector_user_id=None,
        scheduled_at=_now_iso(),
        performed_at=_now_iso(),
        status="failed",
        notes="Cover blocks below 25mm in section.",
        photos_json=[],
    )
    insp_cond = QMSInspection(
        itp_item_id=items[2].id,
        project_id=project_id,
        location_ref="Grid A1-A4",
        inspector_user_id=None,
        scheduled_at=_now_iso(),
        performed_at=None,
        status="conditional",
        notes="Awaiting re-cleanup of joint surface.",
        photos_json=[],
    )
    session.add_all([insp_passed, insp_failed, insp_cond])
    await session.flush()

    # 3) NCRs — 1 open, 1 escalated to variation
    ncr_open = QMSNCR(
        project_id=project_id,
        raised_at=_now_iso(),
        title="Cover below spec",
        description="Rebar cover < 25mm in slab section A2.",
        severity="major",
        root_cause=None,
        status="open",
        cost_impact_currency="",
        cost_impact_amount=None,
        linked_inspection_id=insp_failed.id,
    )
    ncr_var = QMSNCR(
        project_id=project_id,
        raised_at=_now_iso(),
        title="Concrete strength below 28-day target",
        description="Cube test 23MPa vs spec 30MPa — remediation required.",
        severity="critical",
        root_cause="Supplier batch error",
        status="action_pending",
        cost_impact_currency="EUR",
        cost_impact_amount=Decimal("15000.00"),
        linked_variation_id=uuid.uuid4(),
    )
    session.add_all([ncr_open, ncr_var])
    await session.flush()

    # 4) Punch items — eight across the lifecycle
    punch_specs = [
        ("Wall paint scuff in lobby", "open", "minor", "finishes"),
        ("Door latch sticks 03-12", "assigned", "minor", "architectural"),
        ("HVAC noise in 04-08", "in_progress", "major", "mechanical"),
        ("Outlet misalignment 02-04", "ready_for_inspection", "minor", "electrical"),
        ("Crack in slab corner", "rejected", "major", "structure"),
        ("Window seal gap 05-10", "open", "minor", "finishes"),
        ("Door hinge stiff 02-15", "open", "minor", "architectural"),
        ("Closeout: rework verified", "closed", "minor", "finishes"),
    ]
    punches: list[QMSPunchItem] = []
    for title, st, sev, cat in punch_specs:
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
        audit_type="internal",
        planned_date=_now_iso(),
        performed_at=_now_iso(),
        auditor_user_id=None,
        audit_scope="QMS process audit Q2",
        standard_ref="ISO 9001:2015",
        status="completed",
        overall_rating=4,
    )
    session.add(audit)
    await session.flush()

    finding_specs = [
        ("observation", "8.5.1", "Record retention period inconsistent"),
        ("minor", "9.2", "Internal audit interval drifted"),
        ("major", "8.7", "Non-conforming output controls weak"),
    ]
    findings: list[QMSAuditFinding] = []
    for ft, clause, desc in finding_specs:
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
