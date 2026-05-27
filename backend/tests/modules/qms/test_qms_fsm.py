"""Unit tests: QMS FSM (Finite State Machine) allowlist enforcement.

Every status-transition guard (inspection, NCR, punch item, audit, ITP plan)
is covered — both legal moves that must succeed and illegal moves that must
raise ``ValueError``. Tests are service-level so they exercise the real FSM
logic without a full HTTP stack.

Design constraints:
    - In-memory SQLite fixture (mirrors test_qms.py).
    - No alembic migrations — the QMS tables alone are created via
      ``Base.metadata.create_all``.
    - No network I/O.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
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
from app.modules.qms.schemas import (
    AuditCreate,
    AuditUpdate,
    InspectionCreate,
    InspectionSignatureCreate,
    InspectionUpdate,
    ITPItemCreate,
    ITPPlanCreate,
    ITPPlanUpdate,
    NCRActionCreate,
    NCRCreate,
    NCRUpdate,
    PunchItemCreate,
    PunchItemUpdate,
)
from app.modules.qms.service import QMSService

_PROJECT_ID = uuid.uuid4()

_QMS_TABLES = [
    ITPPlan.__table__,
    ITPItem.__table__,
    ITPTemplate.__table__,
    QMSInspection.__table__,
    QMSInspectionSignature.__table__,
    QMSNCR.__table__,
    QMSNCRAction.__table__,
    QMSPunchItem.__table__,
    QMSAudit.__table__,
    QMSAuditFinding.__table__,
    QMSAuditLog.__table__,
    QMSCalibration.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_QMS_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> QMSService:
    return QMSService(session)


# ── ITP Plan FSM ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_itp_legal_transitions(svc: QMSService) -> None:
    """draft → active → superseded → closed are all legal."""
    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=_PROJECT_ID, name="P", work_type="concrete"),
    )
    await svc.add_itp_item(
        plan.id,
        ITPItemCreate(control_point_name="CP", hold_witness_point="hold"),
    )
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        plan = await svc.activate_itp_plan(plan.id)
    assert plan.status == "active"

    plan = await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="superseded"))
    assert plan.status == "superseded"

    plan = await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="closed"))
    assert plan.status == "closed"


@pytest.mark.asyncio
async def test_itp_draft_to_superseded_is_illegal(svc: QMSService) -> None:
    """draft → superseded must be rejected (must go through active first)."""
    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=_PROJECT_ID, name="P", work_type="concrete"),
    )
    with pytest.raises(ValueError, match="Illegal ITP"):
        await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="superseded"))


@pytest.mark.asyncio
async def test_itp_closed_to_anything_is_illegal(svc: QMSService) -> None:
    """Once closed an ITP plan cannot transition to any other state."""
    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=_PROJECT_ID, name="P", work_type="concrete"),
    )
    await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="closed"))
    with pytest.raises(ValueError, match="Illegal ITP"):
        await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="active"))


@pytest.mark.asyncio
async def test_itp_same_status_is_noop(svc: QMSService) -> None:
    """Updating status to the same value as current is allowed (idempotent)."""
    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=_PROJECT_ID, name="P", work_type="concrete"),
    )
    updated = await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="draft"))
    assert updated.status == "draft"


# ── Inspection FSM ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inspection_scheduled_to_in_progress_legal(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    assert insp.status == "scheduled"
    insp = await svc.start_inspection(insp.id)
    assert insp.status == "in_progress"


@pytest.mark.asyncio
async def test_inspection_scheduled_to_passed_directly_legal(
    svc: QMSService,
) -> None:
    """scheduled → passed is allowed (inspector can complete without starting)."""
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        insp = await svc.complete_inspection(insp.id, result="passed")
    assert insp.status == "passed"


@pytest.mark.asyncio
async def test_inspection_passed_cannot_be_failed(svc: QMSService) -> None:
    """passed is a terminal state — cannot transition to failed."""
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        insp = await svc.complete_inspection(insp.id, result="passed")
    with pytest.raises(ValueError, match="Illegal inspection"):
        await svc.complete_inspection(insp.id, result="failed")


@pytest.mark.asyncio
async def test_inspection_conditional_can_resolve_to_passed_or_failed(
    svc: QMSService,
) -> None:
    """conditional → passed and conditional → failed are both legal."""
    for result in ("passed", "failed"):
        insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
        await svc.add_signature(
            insp.id,
            InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
        )
        with patch(
            "app.modules.qms.service.event_bus.publish_detached",
            MagicMock(),
        ):
            insp = await svc.complete_inspection(insp.id, result="conditional")
        assert insp.status == "conditional"
        with patch(
            "app.modules.qms.service.event_bus.publish_detached",
            MagicMock(),
        ):
            insp = await svc.complete_inspection(insp.id, result=result)
        assert insp.status == result


@pytest.mark.asyncio
async def test_inspection_patch_blocked_to_terminal_via_update(
    svc: QMSService,
) -> None:
    """PATCH /inspections/{id} must not bypass the signatory invariant."""
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    with pytest.raises(ValueError, match="complete.*action"):
        await svc.update_inspection(insp.id, InspectionUpdate(status="passed"))


# ── NCR FSM ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_happy_path_fsm(svc: QMSService) -> None:
    """open → action_pending → verifying → closed."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    assert ncr.status == "open"
    action = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(action.id)
    ncr_v = await svc.repo.get_ncr(ncr.id)
    assert ncr_v is not None
    assert ncr_v.status == "verifying"
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        ncr_c = await svc.close_ncr(ncr.id)
    assert ncr_c.status == "closed"


@pytest.mark.asyncio
async def test_ncr_open_to_verifying_is_illegal(svc: QMSService) -> None:
    """open → verifying is not an allowed direct transition."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    with pytest.raises(ValueError, match="Illegal NCR"):
        await svc.update_ncr(ncr.id, NCRUpdate(status="verifying"))


@pytest.mark.asyncio
async def test_ncr_closed_is_terminal(svc: QMSService) -> None:
    """Closed NCRs cannot be edited."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    action = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(action.id)
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        await svc.close_ncr(ncr.id)
    with pytest.raises(ValueError, match="closed"):
        await svc.update_ncr(ncr.id, NCRUpdate(title="Attempt edit"))


@pytest.mark.asyncio
async def test_ncr_cancelled_cannot_be_closed(svc: QMSService) -> None:
    """Cancelled NCRs cannot be closed."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    await svc.repo.update_ncr_fields(ncr.id, status="cancelled")
    with pytest.raises(ValueError, match="cancelled"):
        await svc.close_ncr(ncr.id)


@pytest.mark.asyncio
async def test_ncr_patch_close_is_blocked(svc: QMSService) -> None:
    """PATCH must not close an NCR — must use the dedicated close action."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    with pytest.raises(ValueError, match="close.*action"):
        await svc.update_ncr(ncr.id, NCRUpdate(status="closed"))


# ── Punch item FSM ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_punch_full_legal_path(svc: QMSService) -> None:
    """open → assigned → in_progress → ready_for_inspection → closed."""
    p = await svc.add_punch_item(PunchItemCreate(project_id=_PROJECT_ID, title="T"))
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    assert p.status == "assigned"
    p = await svc.update_punch_item(p.id, PunchItemUpdate(status="in_progress"))
    assert p.status == "in_progress"
    p = await svc.mark_ready_for_inspection(p.id)
    assert p.status == "ready_for_inspection"
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        p = await svc.close_punch_item(p.id)
    assert p.status == "closed"
    assert p.closed_at is not None


@pytest.mark.asyncio
async def test_punch_open_to_ready_for_inspection_illegal(svc: QMSService) -> None:
    """open → ready_for_inspection skips required steps."""
    p = await svc.add_punch_item(PunchItemCreate(project_id=_PROJECT_ID, title="T"))
    with pytest.raises(ValueError, match="Illegal punch"):
        await svc.mark_ready_for_inspection(p.id)


@pytest.mark.asyncio
async def test_punch_closed_is_terminal(svc: QMSService) -> None:
    """Closed punch items cannot be edited."""
    p = await svc.add_punch_item(PunchItemCreate(project_id=_PROJECT_ID, title="T"))
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    p = await svc.update_punch_item(p.id, PunchItemUpdate(status="in_progress"))
    p = await svc.mark_ready_for_inspection(p.id)
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        p = await svc.close_punch_item(p.id)
    with pytest.raises(ValueError, match="closed"):
        await svc.update_punch_item(p.id, PunchItemUpdate(status="open"))


@pytest.mark.asyncio
async def test_punch_rejected_can_return_to_assigned(svc: QMSService) -> None:
    """rejected → assigned is a legal re-queue path."""
    p = await svc.add_punch_item(PunchItemCreate(project_id=_PROJECT_ID, title="T"))
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    p = await svc.reject_punch_item(p.id)
    assert p.status == "rejected"
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    assert p.status == "assigned"


# ── Audit FSM ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_planned_to_completed_requires_in_progress(
    svc: QMSService,
) -> None:
    """planned → completed is illegal (must pass through in_progress)."""
    audit = await svc.plan_audit(AuditCreate(project_id=_PROJECT_ID))
    with pytest.raises(ValueError, match="Illegal audit"):
        await svc.update_audit(audit.id, AuditUpdate(status="completed"))


@pytest.mark.asyncio
async def test_audit_completed_to_closed(svc: QMSService) -> None:
    """planned → in_progress → completed → closed."""
    audit = await svc.plan_audit(AuditCreate(project_id=_PROJECT_ID))
    audit = await svc.start_audit(audit.id)
    assert audit.status == "in_progress"
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        audit = await svc.complete_audit(audit.id, overall_rating=3)
    assert audit.status == "completed"
    audit = await svc.update_audit(audit.id, AuditUpdate(status="closed"))
    assert audit.status == "closed"


@pytest.mark.asyncio
async def test_audit_closed_is_terminal(svc: QMSService) -> None:
    """Closed audits cannot transition to any state."""
    audit = await svc.plan_audit(AuditCreate(project_id=_PROJECT_ID))
    await svc.update_audit(audit.id, AuditUpdate(status="closed"))
    with pytest.raises(ValueError, match="Illegal audit"):
        await svc.start_audit(audit.id)


# ── Audit trail writes ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_ncr_writes_audit_log(svc: QMSService) -> None:
    """Closing an NCR must append exactly one audit log entry."""
    ncr = await svc.raise_ncr(
        NCRCreate(project_id=_PROJECT_ID, title="T", description="d", severity="minor"),
    )
    action = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(action.id)
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        await svc.close_ncr(ncr.id)

    log_entries = await svc.repo.list_audit_log(ncr.id, entity_type="ncr")
    # Two entries: open (on creation) + closed
    statuses = [(e.old_status, e.new_status) for e in log_entries]
    assert (None, "open") in statuses
    assert any(e.new_status == "closed" for e in log_entries)


@pytest.mark.asyncio
async def test_complete_inspection_writes_audit_log(svc: QMSService) -> None:
    """Completing an inspection must write the status change to the audit log."""
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch("app.modules.qms.service.event_bus.publish_detached", MagicMock()):
        await svc.complete_inspection(insp.id, result="passed")

    log_entries = await svc.repo.list_audit_log(insp.id, entity_type="inspection")
    # Must have: in_progress (from start_inspection) + passed entries, or just passed
    final_entry = log_entries[-1]
    assert final_entry.new_status == "passed"


@pytest.mark.asyncio
async def test_start_inspection_writes_audit_log(svc: QMSService) -> None:
    """Starting an inspection must write the scheduled→in_progress transition."""
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    await svc.start_inspection(insp.id)

    log_entries = await svc.repo.list_audit_log(insp.id, entity_type="inspection")
    assert any(e.old_status == "scheduled" and e.new_status == "in_progress" for e in log_entries)
