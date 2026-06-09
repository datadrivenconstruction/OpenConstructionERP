"""Unit tests for :class:`QMSService`.

Scope:
    * ITP plan CRUD + items + activation
    * Inspection scheduling, multi-signature enforcement, completion
    * NCR raise → action → verify → close happy path
    * NCR escalation to variation publishes ``qms.ncr.escalated_to_variation``
    * Punch item rolling lifecycle
    * Audit + findings flow
    * COPQ and first-pass-yield analytics
    * Illegal status transitions raise ValueError
    * Notification / variation-creation events captured via AsyncMock spy

Each test runs against PostgreSQL via :func:`tests._pg.transactional_session`,
which opens an outer transaction on the shared, fully-schema-loaded
``oe_test_unit`` database and rolls it back on teardown. The session's own
``commit()`` calls become savepoint releases, so committed data is visible
within the test but undone afterwards - giving per-test isolation without any
``create_all`` round-trip. PostgreSQL enforces foreign keys natively, so the
escalation happy-path test inserts real User/Project/VariationOrder rows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.qms.models import QMSNCRAction
from app.modules.qms.schemas import (
    AuditCreate,
    AuditFindingCreate,
    InspectionCreate,
    InspectionSignatureCreate,
    ITPItemCreate,
    ITPPlanCreate,
    ITPPlanUpdate,
    NCRActionCreate,
    NCRCreate,
    PunchItemCreate,
    PunchItemUpdate,
)
from app.modules.qms.service import QMSService
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from tests._pg import transactional_session

PROJECT_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction.

    The full schema already exists on the shared ``oe_test_unit`` database, so
    no table creation is needed. Everything done in the test is undone on
    teardown, giving clean isolation. FKs are enforced natively by PostgreSQL.
    """
    async with transactional_session() as sess:
        yield sess


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> QMSService:
    return QMSService(session)


# ── ITP plan ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_itp_plan(svc: QMSService) -> None:
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="Concrete pour",
            work_type="concrete",
        ),
        user_id="u-1",
    )
    assert plan.id is not None
    assert plan.status == "draft"
    assert plan.name == "Concrete pour"


@pytest.mark.asyncio
async def test_add_itp_item_to_draft_plan(svc: QMSService) -> None:
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="ITP",
            work_type="concrete",
        ),
    )
    item = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            sequence=10,
            control_point_name="Rebar inspection",
            hold_witness_point="hold",
            signatories_required=2,
        ),
    )
    assert item.itp_plan_id == plan.id
    assert item.signatories_required == 2


@pytest.mark.asyncio
async def test_activate_empty_itp_plan_rejected(svc: QMSService) -> None:
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="Empty",
            work_type="concrete",
        ),
    )
    with pytest.raises(ValueError, match="no items"):
        await svc.activate_itp_plan(plan.id)


@pytest.mark.asyncio
async def test_activate_itp_plan_publishes_event(svc: QMSService) -> None:
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="P",
            work_type="concrete",
        ),
    )
    await svc.add_itp_item(
        plan.id,
        ITPItemCreate(control_point_name="CP1", hold_witness_point="hold"),
    )

    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        plan = await svc.activate_itp_plan(plan.id)

    assert plan.status == "active"
    assert spy.call_count == 1
    name, payload = spy.call_args.args[0], spy.call_args.args[1]
    assert name == "qms.itp.activated"
    assert payload["itp_plan_id"] == str(plan.id)


@pytest.mark.asyncio
async def test_itp_illegal_transition(svc: QMSService) -> None:
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="P",
            work_type="concrete",
        ),
    )
    # draft → superseded is illegal (must go through active)
    with pytest.raises(ValueError, match="Illegal ITP"):
        await svc.update_itp_plan(plan.id, ITPPlanUpdate(status="superseded"))


# ── Inspections ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_and_start_inspection(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    assert insp.status == "scheduled"
    insp = await svc.start_inspection(insp.id)
    assert insp.status == "in_progress"


@pytest.mark.asyncio
async def test_inspection_complete_requires_signatures(svc: QMSService) -> None:
    """Cannot complete an inspection if fewer than required signatures are present."""
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="P",
            work_type="concrete",
        ),
    )
    item = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="CP",
            hold_witness_point="hold",
            signatories_required=2,
        ),
    )
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID, itp_item_id=item.id),
    )
    # 0/2 signatures
    with pytest.raises(ValueError, match="signatures"):
        await svc.complete_inspection(insp.id, result="passed")

    # Add 1 signature — still insufficient
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(
            signer_user_id=uuid.uuid4(),
            signer_role="GC",
            signature_method="electronic",
        ),
    )
    with pytest.raises(ValueError, match="signatures"):
        await svc.complete_inspection(insp.id, result="passed")


@pytest.mark.asyncio
async def test_inspection_complete_with_required_signatures(svc: QMSService) -> None:
    plan = await svc.create_itp_plan(
        ITPPlanCreate(
            project_id=PROJECT_ID,
            name="P",
            work_type="concrete",
        ),
    )
    item = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="CP",
            hold_witness_point="hold",
            signatories_required=2,
        ),
    )
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID, itp_item_id=item.id),
    )
    for role in ("GC", "designer"):
        await svc.add_signature(
            insp.id,
            InspectionSignatureCreate(
                signer_user_id=uuid.uuid4(),
                signer_role=role,
            ),
        )
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        insp = await svc.complete_inspection(insp.id, result="passed")
    assert insp.status == "passed"
    # complete_inspection emits the generic passed event, and for a hold or
    # witness point it also fans out a dedicated hold_point_passed event. The
    # generic event must be among those published (call_args is only the last).
    published = [call.args[0] for call in spy.call_args_list]
    assert "qms.inspection.passed" in published


@pytest.mark.asyncio
async def test_inspection_failed_emits_failed_event(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    # No ITP linked → default 1 signature required
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(
            signer_user_id=uuid.uuid4(),
            signer_role="GC",
        ),
    )
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        insp = await svc.complete_inspection(insp.id, result="failed")
    assert insp.status == "failed"
    assert spy.call_args.args[0] == "qms.inspection.failed"


@pytest.mark.asyncio
async def test_add_signature_defaults_to_caller_when_omitted(svc: QMSService) -> None:
    """Omitting ``signer_user_id`` signs as the authenticated caller.

    This is the "sign as me" flow the UI relies on so a normal user never
    has to hand-type a UUID.
    """
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    caller = uuid.uuid4()
    sig = await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_role="inspector"),
        default_signer_user_id=caller,
    )
    assert sig.signer_user_id == caller


@pytest.mark.asyncio
async def test_add_signature_explicit_id_overrides_default(svc: QMSService) -> None:
    """An explicit ``signer_user_id`` records a sign-off for another member."""
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    caller = uuid.uuid4()
    on_behalf_of = uuid.uuid4()
    sig = await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=on_behalf_of, signer_role="GC"),
        default_signer_user_id=caller,
    )
    assert sig.signer_user_id == on_behalf_of


@pytest.mark.asyncio
async def test_add_signature_requires_a_signer(svc: QMSService) -> None:
    """With neither an explicit id nor a caller default, signing is rejected."""
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    with pytest.raises(ValueError, match="signer_user_id"):
        await svc.add_signature(
            insp.id,
            InspectionSignatureCreate(signer_role="inspector"),
        )


@pytest.mark.asyncio
async def test_complete_already_completed_inspection(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(
            signer_user_id=uuid.uuid4(),
            signer_role="GC",
        ),
    )
    await svc.complete_inspection(insp.id, result="passed")
    with pytest.raises(ValueError, match="Illegal inspection"):
        await svc.complete_inspection(insp.id, result="failed")


@pytest.mark.asyncio
async def test_inspection_invalid_result_arg(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID),
    )
    with pytest.raises(ValueError, match="Invalid completion result"):
        await svc.complete_inspection(insp.id, result="bogus")


# ── NCRs ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raise_ncr_emits_event(svc: QMSService) -> None:
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        ncr = await svc.raise_ncr(
            NCRCreate(
                project_id=PROJECT_ID,
                title="Wall hairline crack",
                description="Crack visible in 12-08 wall.",
                severity="minor",
            ),
        )
    assert ncr.status == "open"
    assert spy.call_args.args[0] == "qms.ncr.raised"


@pytest.mark.asyncio
async def test_ncr_action_auto_progresses_status(svc: QMSService) -> None:
    """Adding an action against an `open` NCR moves it to `action_pending`."""
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="major",
        ),
    )
    await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Replace bracket"),
    )
    # Re-fetch
    ncr_refreshed = await svc.repo.get_ncr(ncr.id)
    assert ncr_refreshed is not None
    assert ncr_refreshed.status == "action_pending"


@pytest.mark.asyncio
async def test_ncr_verify_action_advances_to_verifying(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="major",
        ),
    )
    a1 = await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Fix"),
    )
    a2 = await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Verify"),
    )
    await svc.verify_action(a1.id)
    # Still action_pending — second action outstanding
    ncr_mid = await svc.repo.get_ncr(ncr.id)
    assert ncr_mid is not None and ncr_mid.status == "action_pending"
    await svc.verify_action(a2.id)
    ncr_done = await svc.repo.get_ncr(ncr.id)
    assert ncr_done is not None and ncr_done.status == "verifying"


@pytest.mark.asyncio
async def test_close_ncr_requires_all_actions_done(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="major",
        ),
    )
    a1 = await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Fix"),
    )
    # No verify → cannot close
    with pytest.raises(ValueError, match="every corrective action"):
        await svc.close_ncr(ncr.id)
    await svc.verify_action(a1.id)
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        ncr = await svc.close_ncr(ncr.id)
    assert ncr.status == "closed"
    assert spy.call_args.args[0] == "qms.ncr.closed"


@pytest.mark.asyncio
async def test_close_ncr_with_no_actions_blocked(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="minor",
        ),
    )
    with pytest.raises(ValueError, match="every corrective action"):
        await svc.close_ncr(ncr.id)


@pytest.mark.asyncio
async def test_escalate_ncr_publishes_event(svc: QMSService) -> None:
    """NCR escalation publishes ``qms.ncr.escalated_to_variation`` event.

    Mirrors the product flow: the caller supplies an existing
    :class:`VariationOrder` in the same project; the QMS module does not
    fabricate one. The escalation links the NCR to that variation.
    """
    # A real owner + project so the VariationOrder FK is satisfied
    # (PostgreSQL enforces foreign keys natively).
    owner = User(email=f"u{uuid.uuid4().hex[:6]}@test.com", hashed_password="x")
    svc.session.add(owner)
    await svc.session.flush()
    project = Project(id=PROJECT_ID, name="Escalation Test", owner_id=owner.id)
    svc.session.add(project)
    await svc.session.flush()

    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="Strength below spec",
            description="d",
            severity="critical",
            cost_impact_currency="EUR",
            cost_impact_amount=Decimal("12500.00"),
        ),
    )

    # An existing variation order in the same project to escalate into.
    variation = VariationOrder(project_id=PROJECT_ID, code="VO-0001")
    svc.session.add(variation)
    await svc.session.flush()

    spy = MagicMock()
    with patch("app.modules.qms.service.event_bus.publish_detached", spy):
        ncr_after = await svc.escalate_ncr_to_variation(
            ncr.id,
            variation_id=variation.id,
        )

    assert ncr_after.linked_variation_id == variation.id
    assert spy.call_count == 1
    event_name = spy.call_args.args[0]
    payload = spy.call_args.args[1]
    assert event_name == "qms.ncr.escalated_to_variation"
    assert payload["ncr_id"] == str(ncr.id)
    assert payload["cost_impact"] == "12500.00"
    assert payload["cost_impact_currency"] == "EUR"


@pytest.mark.asyncio
async def test_escalate_ncr_without_cost_impact_rejected(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="major",
        ),
    )
    with pytest.raises(ValueError, match="cost_impact"):
        await svc.escalate_ncr_to_variation(ncr.id)


@pytest.mark.asyncio
async def test_ncr_illegal_status_transition(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="minor",
        ),
    )
    from app.modules.qms.schemas import NCRUpdate

    # open → verifying is illegal (must walk through action_pending)
    with pytest.raises(ValueError, match="Illegal NCR"):
        await svc.update_ncr(ncr.id, NCRUpdate(status="verifying"))


@pytest.mark.asyncio
async def test_ncr_patch_cannot_bypass_close_action(svc: QMSService) -> None:
    """PATCH must not close an NCR — that bypasses the corrective-action
    completeness invariant enforced by ``close_ncr``."""
    from app.modules.qms.schemas import NCRUpdate

    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="minor",
        ),
    )
    # Directly from open
    with pytest.raises(ValueError, match="close.* action"):
        await svc.update_ncr(ncr.id, NCRUpdate(status="closed"))

    # And from verifying (the real integrity hole: verifying → closed is
    # in the transition table, so only the explicit guard blocks it).
    a1 = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(a1.id)
    ncr_v = await svc.repo.get_ncr(ncr.id)
    assert ncr_v is not None
    assert ncr_v.status == "verifying"
    with pytest.raises(ValueError, match="close.* action"):
        await svc.update_ncr(ncr.id, NCRUpdate(status="closed"))
    # The dedicated close action still works.
    closed = await svc.close_ncr(ncr.id)
    assert closed.status == "closed"


@pytest.mark.asyncio
async def test_inspection_patch_cannot_bypass_complete_action(
    svc: QMSService,
) -> None:
    """PATCH must not set a terminal result — that bypasses the ITP
    signatory-count invariant enforced by ``complete_inspection``."""
    from app.modules.qms.schemas import InspectionUpdate

    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=PROJECT_ID, name="P", work_type="concrete"),
    )
    item = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="CP",
            hold_witness_point="hold",
            signatories_required=2,
        ),
    )
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=PROJECT_ID, itp_item_id=item.id),
    )
    # No signatures collected — a raw PATCH must not be able to pass it.
    with pytest.raises(ValueError, match="complete.* action"):
        await svc.update_inspection(
            insp.id,
            InspectionUpdate(status="passed"),
        )
    # Non-terminal PATCH transitions still work.
    insp = await svc.update_inspection(
        insp.id,
        InspectionUpdate(status="in_progress"),
    )
    assert insp.status == "in_progress"


@pytest.mark.asyncio
async def test_cannot_edit_closed_ncr(svc: QMSService) -> None:
    """Sanity check — once closed, an NCR rejects further edits."""
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="minor",
        ),
    )
    a1 = await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Fix"),
    )
    await svc.verify_action(a1.id)
    await svc.close_ncr(ncr.id)

    from app.modules.qms.schemas import NCRUpdate

    with pytest.raises(ValueError, match="closed"):
        await svc.update_ncr(ncr.id, NCRUpdate(title="Edit-attempt"))


@pytest.mark.asyncio
async def test_cannot_verify_action_on_closed_ncr(svc: QMSService) -> None:
    """Once an NCR is closed, lingering actions cannot be re-verified."""
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="minor",
        ),
    )
    a1 = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(a1.id)
    await svc.close_ncr(ncr.id)
    # Add a stray second action directly (bypassing service guard) then
    # confirm verify_action refuses because the parent NCR is terminal.
    a2 = QMSNCRAction(ncr_id=ncr.id, description="late", status="assigned")
    svc.session.add(a2)
    await svc.session.flush()
    with pytest.raises(ValueError, match="status 'closed'"):
        await svc.verify_action(a2.id)


@pytest.mark.asyncio
async def test_cannot_escalate_closed_ncr(svc: QMSService) -> None:
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="t",
            description="d",
            severity="critical",
            cost_impact_currency="EUR",
            cost_impact_amount=Decimal("5000.00"),
        ),
    )
    a1 = await svc.assign_ncr_action(ncr.id, NCRActionCreate(description="Fix"))
    await svc.verify_action(a1.id)
    await svc.close_ncr(ncr.id)
    with pytest.raises(ValueError, match="terminal status 'closed'"):
        await svc.escalate_ncr_to_variation(ncr.id)


# ── Punch list ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_punch_lifecycle_rolling(svc: QMSService) -> None:
    p = await svc.add_punch_item(
        PunchItemCreate(project_id=PROJECT_ID, title="Scuff"),
    )
    assert p.status == "open"
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    assert p.status == "assigned"
    p = await svc.update_punch_item(
        p.id,
        PunchItemUpdate(status="in_progress"),
    )
    assert p.status == "in_progress"
    p = await svc.mark_ready_for_inspection(p.id)
    assert p.status == "ready_for_inspection"
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        p = await svc.close_punch_item(p.id)
    assert p.status == "closed"
    assert spy.call_args.args[0] == "qms.punch.closed"


@pytest.mark.asyncio
async def test_punch_illegal_transition(svc: QMSService) -> None:
    p = await svc.add_punch_item(
        PunchItemCreate(project_id=PROJECT_ID, title="T"),
    )
    # open → ready_for_inspection is illegal (must go assigned/in_progress first)
    with pytest.raises(ValueError, match="Illegal punch"):
        await svc.mark_ready_for_inspection(p.id)


@pytest.mark.asyncio
async def test_punch_rejected_can_be_reassigned(svc: QMSService) -> None:
    p = await svc.add_punch_item(
        PunchItemCreate(project_id=PROJECT_ID, title="T"),
    )
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    p = await svc.reject_punch_item(p.id)
    assert p.status == "rejected"
    p = await svc.assign_punch_item(p.id, assigned_to=uuid.uuid4())
    assert p.status == "assigned"


@pytest.mark.asyncio
async def test_punch_creation_emits_event(svc: QMSService) -> None:
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        await svc.add_punch_item(
            PunchItemCreate(project_id=PROJECT_ID, title="T"),
        )
    assert spy.call_args.args[0] == "qms.punch.created"


# ── Audit ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_start_complete_audit(svc: QMSService) -> None:
    audit = await svc.plan_audit(
        AuditCreate(
            project_id=PROJECT_ID,
            audit_type="internal",
            standard_ref="ISO 9001:2015",
        ),
    )
    assert audit.status == "planned"
    audit = await svc.start_audit(audit.id)
    assert audit.status == "in_progress"
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        audit = await svc.complete_audit(audit.id, overall_rating=4)
    assert audit.status == "completed"
    assert audit.overall_rating == 4
    assert spy.call_args.args[0] == "qms.audit.completed"


@pytest.mark.asyncio
async def test_add_finding_emits_event(svc: QMSService) -> None:
    audit = await svc.plan_audit(
        AuditCreate(project_id=PROJECT_ID),
    )
    await svc.start_audit(audit.id)
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        finding = await svc.add_finding(
            audit.id,
            AuditFindingCreate(
                finding_type="minor",
                description="Documentation gap",
                clause_ref="7.5.1",
            ),
        )
    assert finding.status == "open"
    assert spy.call_args.args[0] == "qms.audit.finding_raised"


@pytest.mark.asyncio
async def test_close_finding(svc: QMSService) -> None:
    audit = await svc.plan_audit(AuditCreate(project_id=PROJECT_ID))
    finding = await svc.add_finding(
        audit.id,
        AuditFindingCreate(description="x"),
    )
    finding = await svc.close_finding(finding.id)
    assert finding.status == "closed"
    assert finding.closed_at is not None


@pytest.mark.asyncio
async def test_audit_invalid_rating_rejected(svc: QMSService) -> None:
    audit = await svc.plan_audit(AuditCreate(project_id=PROJECT_ID))
    await svc.start_audit(audit.id)
    with pytest.raises(ValueError, match="overall_rating"):
        await svc.complete_audit(audit.id, overall_rating=99)


@pytest.mark.asyncio
async def test_audit_finding_blocked_on_closed_audit(svc: QMSService) -> None:
    audit = await svc.plan_audit(AuditCreate(project_id=PROJECT_ID))
    # Force terminal state
    await svc.repo.update_audit_fields(audit.id, status="closed")
    with pytest.raises(ValueError, match="closed audit"):
        await svc.add_finding(
            audit.id,
            AuditFindingCreate(description="x"),
        )


# ── COPQ analytics ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_copq_computation(svc: QMSService) -> None:
    """COPQ = sum(NCR cost impact) + open_punch_count * default rework cost."""
    await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="A",
            description="d",
            severity="major",
            cost_impact_currency="EUR",
            cost_impact_amount=Decimal("1000.00"),
        ),
    )
    await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="B",
            description="d",
            severity="minor",
            cost_impact_currency="EUR",
            cost_impact_amount=Decimal("500.00"),
        ),
    )
    # Cancelled NCRs should NOT count
    cancel_ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="C",
            description="d",
            severity="minor",
            cost_impact_currency="EUR",
            cost_impact_amount=Decimal("999.00"),
        ),
    )
    await svc.repo.update_ncr_fields(cancel_ncr.id, status="cancelled")
    # 3 open punch items
    for _ in range(3):
        await svc.add_punch_item(
            PunchItemCreate(project_id=PROJECT_ID, title="t"),
        )
    # 1 closed punch — must NOT count
    p_closed = await svc.add_punch_item(
        PunchItemCreate(project_id=PROJECT_ID, title="closed"),
    )
    await svc.repo.update_punch_fields(p_closed.id, status="closed")

    report = await svc.compute_copq(PROJECT_ID, currency="EUR")
    assert report["ncr_cost_total"] == Decimal("1500.00")
    assert report["open_punch_count"] == 3
    # Default rework cost 250 × 3 = 750
    assert report["rework_cost_estimate"] == Decimal("750.00")
    assert report["copq_total"] == Decimal("2250.00")
    assert report["currency"] == "EUR"


@pytest.mark.asyncio
async def test_copq_empty_project(svc: QMSService) -> None:
    report = await svc.compute_copq(PROJECT_ID)
    assert report["ncr_cost_total"] == Decimal("0")
    assert report["open_punch_count"] == 0
    assert report["copq_total"] == Decimal("0")


@pytest.mark.asyncio
async def test_copq_with_override_per_punch(svc: QMSService) -> None:
    await svc.add_punch_item(
        PunchItemCreate(project_id=PROJECT_ID, title="t"),
    )
    report = await svc.compute_copq(
        PROJECT_ID,
        rework_cost_per_punch=Decimal("100.00"),
    )
    assert report["rework_cost_estimate"] == Decimal("100.00")


# ── First-pass yield ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_pass_yield(svc: QMSService) -> None:
    # 3 inspections, 2 passed
    for r in ("passed", "passed", "failed"):
        i = await svc.schedule_inspection(
            InspectionCreate(project_id=PROJECT_ID),
        )
        await svc.add_signature(
            i.id,
            InspectionSignatureCreate(
                signer_user_id=uuid.uuid4(),
                signer_role="GC",
            ),
        )
        await svc.complete_inspection(i.id, result=r)

    report = await svc.compute_first_pass_yield(PROJECT_ID)
    assert report["inspections_total"] == 3
    assert report["inspections_passed_first_time"] == 2
    assert report["first_pass_yield"] == pytest.approx(2 / 3, abs=1e-3)


@pytest.mark.asyncio
async def test_first_pass_yield_zero_inspections(svc: QMSService) -> None:
    report = await svc.compute_first_pass_yield(PROJECT_ID)
    assert report["inspections_total"] == 0
    assert report["first_pass_yield"] == 0.0


# ── Permission registry sanity ────────────────────────────────────────────


def test_permissions_register_does_not_raise() -> None:
    """Module permissions are registerable and resolve to valid roles."""
    from app.core.permissions import permission_registry
    from app.modules.qms.permissions import register_qms_permissions

    register_qms_permissions()
    expected = [
        "qms.itp.read",
        "qms.itp.write",
        "qms.inspection.read",
        "qms.inspection.write",
        "qms.inspection.sign",
        "qms.ncr.read",
        "qms.ncr.write",
        "qms.ncr.escalate",
        "qms.punch.read",
        "qms.punch.write",
        "qms.audit.read",
        "qms.audit.write",
    ]
    for perm in expected:
        assert perm in permission_registry._permissions, f"missing permission {perm}"


# ── Seed sanity ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_qms_creates_demo_data(session: AsyncSession) -> None:
    from app.modules.qms.seed import seed_qms

    result = await seed_qms(session)
    assert "project_id" in result
    assert len(result["itp_item_ids"]) == 5  # type: ignore[arg-type]
    assert len(result["inspection_ids"]) == 3  # type: ignore[arg-type]
    assert len(result["ncr_ids"]) == 2  # type: ignore[arg-type]
    assert len(result["punch_ids"]) == 8  # type: ignore[arg-type]
    assert len(result["finding_ids"]) == 3  # type: ignore[arg-type]


# ── publish_detached vs publish (sanity) ──────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_raised_event_uses_publish_detached(svc: QMSService) -> None:
    """Confirms the service uses ``publish_detached`` (fire-and-forget),
    not blocking ``publish``."""
    spy_detached = MagicMock()
    spy_publish = AsyncMock()
    with (
        patch(
            "app.modules.qms.service.event_bus.publish_detached",
            spy_detached,
        ),
        patch("app.modules.qms.service.event_bus.publish", spy_publish),
    ):
        await svc.raise_ncr(
            NCRCreate(
                project_id=PROJECT_ID,
                title="t",
                description="d",
                severity="minor",
            ),
        )
    assert spy_detached.called
    spy_publish.assert_not_called()


# ── ITP template library ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_itp_template_with_items(svc: QMSService) -> None:
    from app.modules.qms.schemas import ITPTemplateCreate, ITPTemplateItemSpec

    tpl = await svc.create_itp_template(
        ITPTemplateCreate(
            csi_division="03",
            work_type="concrete",
            name="Slab on grade — std ITP",
            description="Standard ITP for slab on grade pours",
            standard_ref="ACI 318",
            items=[
                ITPTemplateItemSpec(
                    sequence=10,
                    control_point_name="Formwork",
                    hold_witness_point="hold",
                    signatories_required=2,
                ),
                ITPTemplateItemSpec(
                    sequence=20,
                    control_point_name="Rebar",
                    hold_witness_point="hold",
                    signatories_required=2,
                ),
            ],
        ),
        user_id="u-1",
    )
    assert tpl.id is not None
    assert tpl.csi_division == "03"
    assert len(tpl.items_json) == 2


@pytest.mark.asyncio
async def test_clone_itp_template_to_project_publishes_event(
    svc: QMSService,
) -> None:
    from app.modules.qms.schemas import (
        ITPTemplateCloneRequest,
        ITPTemplateCreate,
        ITPTemplateItemSpec,
    )

    tpl = await svc.create_itp_template(
        ITPTemplateCreate(
            csi_division="05",
            work_type="structural_steel",
            name="Steel erection ITP",
            items=[
                ITPTemplateItemSpec(
                    sequence=10,
                    control_point_name="Bolt torque",
                    hold_witness_point="witness",
                    signatories_required=1,
                ),
            ],
        ),
    )
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        plan = await svc.clone_itp_template_to_project(
            tpl.id,
            ITPTemplateCloneRequest(
                project_id=PROJECT_ID,
                wbs_ref="WBS.05",
                name_override="Steel erection Q3",
            ),
            user_id="u-2",
        )
    assert plan.project_id == PROJECT_ID
    assert plan.work_type == "structural_steel"
    assert plan.name == "Steel erection Q3"
    assert plan.status == "draft"
    # Items copied across
    items = await svc.repo.list_itp_items(plan.id)
    assert len(items) == 1
    assert items[0].control_point_name == "Bolt torque"
    assert spy.call_count == 1
    assert spy.call_args.args[0] == "qms.itp.cloned_from_template"


@pytest.mark.asyncio
async def test_clone_inactive_itp_template_rejected(svc: QMSService) -> None:
    from app.modules.qms.schemas import (
        ITPTemplateCloneRequest,
        ITPTemplateCreate,
    )

    tpl = await svc.create_itp_template(
        ITPTemplateCreate(
            csi_division="09",
            work_type="finishes",
            name="Inactive ITP",
            is_active=False,
        ),
    )
    with pytest.raises(ValueError, match="inactive"):
        await svc.clone_itp_template_to_project(
            tpl.id,
            ITPTemplateCloneRequest(project_id=PROJECT_ID),
        )


# ── Calibration tracking ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_calibration_persists_certificate(svc: QMSService) -> None:
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.modules.qms.schemas import CalibrationCreate

    cal = await svc.create_calibration(
        CalibrationCreate(
            project_id=PROJECT_ID,
            instrument_id="TM-001",
            instrument_name="Torque wrench 0-200Nm",
            instrument_type="torque_wrench",
            serial_number="SN12345",
            manufacturer="Norbar",
            calibration_date=_date.today() - _td(days=30),
            valid_until=_date.today() + _td(days=335),
            calibrated_by="Acme Calibration Lab",
        ),
    )
    assert cal.id is not None
    assert cal.status == "valid"
    assert cal.instrument_id == "TM-001"


@pytest.mark.asyncio
async def test_calibration_rejects_invalid_dates(svc: QMSService) -> None:
    from datetime import date as _date

    from app.modules.qms.schemas import CalibrationCreate

    with pytest.raises(ValueError, match="valid_until"):
        await svc.create_calibration(
            CalibrationCreate(
                instrument_id="X",
                instrument_name="X",
                instrument_type="x",
                calibration_date=_date.today(),
                valid_until=_date.today(),  # not after
            ),
        )


@pytest.mark.asyncio
async def test_expiring_calibrations_filters_and_publishes(
    svc: QMSService,
) -> None:
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.modules.qms.schemas import CalibrationCreate

    today = _date.today()
    # Expires in 10 days
    await svc.create_calibration(
        CalibrationCreate(
            instrument_id="A",
            instrument_name="A",
            instrument_type="meter",
            calibration_date=today - _td(days=300),
            valid_until=today + _td(days=10),
        )
    )
    # Expires in 100 days — not in 30-day window
    await svc.create_calibration(
        CalibrationCreate(
            instrument_id="B",
            instrument_name="B",
            instrument_type="meter",
            calibration_date=today - _td(days=200),
            valid_until=today + _td(days=100),
        )
    )
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        rows = await svc.expiring_calibrations(days=30, today=today)
    assert len(rows) == 1
    assert rows[0].instrument_id == "A"
    assert spy.call_count == 1
    assert spy.call_args.args[0] == "qms.calibration.expiring"


# ── COPQ detailed (with warranty + delay penalty) ────────────────────────


@pytest.mark.asyncio
async def test_copq_detailed_aggregates_all_components(
    svc: QMSService,
) -> None:
    from decimal import Decimal as _D

    # Raise an NCR with cost impact so it sums into COPQ.
    await svc.raise_ncr(
        NCRCreate(
            project_id=PROJECT_ID,
            title="Concrete strength below spec",
            description="Cube test 23MPa",
            severity="critical",
            cost_impact_amount=_D("10000"),
            cost_impact_currency="EUR",
        ),
    )
    data = await svc.compute_copq_detailed(
        PROJECT_ID,
        rework_cost_per_punch=_D("100"),
        warranty_cost=_D("2500"),
        delay_penalty_cost=_D("5000"),
        currency="EUR",
    )
    assert data["currency"] == "EUR"
    assert data["ncr_cost_total"] == _D("10000")
    # No open punches yet → 0 rework
    assert data["rework_cost_estimate"] == _D("0")
    assert data["warranty_cost"] == _D("2500")
    assert data["delay_penalty_cost"] == _D("5000")
    assert data["copq_total"] == _D("17500")


def test_compute_copq_breakdown_pure_helper() -> None:
    from decimal import Decimal as _D

    from app.modules.qms.service import compute_copq_breakdown

    out = compute_copq_breakdown(
        ncr_cost=_D("1000"),
        open_punch_count=5,
        rework_cost_per_punch=_D("200"),
        warranty_cost=_D("300"),
        delay_penalty_cost=_D("400"),
    )
    assert out["rework_cost"] == _D("1000")  # 5 × 200
    assert out["copq_total"] == _D("2700")


# ── FPY trend ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fpy_trend_returns_correct_bucket_count(svc: QMSService) -> None:
    data = await svc.compute_fpy_trend(
        PROJECT_ID,
        period_days=7,
        periods=4,
    )
    assert data["period_days"] == 7
    assert len(data["buckets"]) == 4
    # Each bucket present has the 5 required keys
    for b in data["buckets"]:
        for k in (
            "period_start",
            "period_end",
            "inspections_total",
            "inspections_passed_first_time",
            "first_pass_yield",
        ):
            assert k in b


@pytest.mark.asyncio
async def test_fpy_trend_rejects_invalid_inputs(svc: QMSService) -> None:
    with pytest.raises(ValueError):
        await svc.compute_fpy_trend(PROJECT_ID, period_days=0, periods=4)
    with pytest.raises(ValueError):
        await svc.compute_fpy_trend(PROJECT_ID, period_days=7, periods=0)


# ── Supplier audit linkage ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_supplier_audit_publishes_event(svc: QMSService) -> None:
    audit = await svc.plan_audit(
        AuditCreate(
            project_id=PROJECT_ID,
            audit_type="supplier",
            audit_scope="Q3 supplier audit",
        ),
    )
    sub_id = uuid.uuid4()
    with patch(
        "app.modules.qms.service.event_bus.publish_detached",
        new_callable=MagicMock,
    ) as spy:
        payload = await svc.link_audit_to_subcontractor(
            audit.id,
            subcontractor_id=sub_id,
            rating_delta=-2,
        )
    assert payload["audit_id"] == str(audit.id)
    assert payload["subcontractor_id"] == str(sub_id)
    assert payload["rating_delta"] == -2
    assert spy.call_count == 1
    assert spy.call_args.args[0] == "qms.audit.linked_to_subcontractor"


@pytest.mark.asyncio
async def test_link_non_supplier_audit_rejected(svc: QMSService) -> None:
    audit = await svc.plan_audit(
        AuditCreate(project_id=PROJECT_ID, audit_type="internal"),
    )
    with pytest.raises(ValueError, match="supplier audits"):
        await svc.link_audit_to_subcontractor(
            audit.id,
            subcontractor_id=uuid.uuid4(),
            rating_delta=-1,
        )


def test_severity_to_rating_delta_mapping() -> None:
    from app.modules.qms.service import severity_to_rating_delta

    assert severity_to_rating_delta("critical") == -3
    assert severity_to_rating_delta("major") == -2
    assert severity_to_rating_delta("minor") == -1
    assert severity_to_rating_delta("unknown") == 0


# ── Management review report ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_management_review_report_basic(svc: QMSService) -> None:
    from datetime import date as _date
    from datetime import timedelta as _td

    today = _date.today()
    data = await svc.generate_management_review(
        PROJECT_ID,
        period_from=today - _td(days=30),
        period_to=today,
        currency="EUR",
    )
    assert data["project_id"] == PROJECT_ID
    assert data["currency"] == "EUR"
    assert isinstance(data["recommendations"], list)
    assert len(data["recommendations"]) >= 1
    # Required keys
    for k in (
        "audits_completed",
        "findings_open",
        "findings_closed",
        "ncrs_raised",
        "ncrs_closed",
        "first_pass_yield",
        "copq_total",
        "inspections_total",
    ):
        assert k in data


@pytest.mark.asyncio
async def test_management_review_period_validation(svc: QMSService) -> None:
    from datetime import date as _date
    from datetime import timedelta as _td

    today = _date.today()
    with pytest.raises(ValueError, match="period_to"):
        await svc.generate_management_review(
            PROJECT_ID,
            period_from=today,
            period_to=today - _td(days=7),  # wrong direction
        )


# ── Wave M4: cross-module wiring ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_raised_fanout_publishes_supplier_rating_and_kpi() -> None:
    """``qms.ncr.raised`` → procurement.supplier_rating_update + bi.kpi_recompute."""
    import asyncio
    import uuid as _uuid

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.qms.events import _on_ncr_raised_fanout

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    event = Event(
        name="qms.ncr.raised",
        data={
            "ncr_id": str(_uuid.uuid4()),
            "project_id": str(_uuid.uuid4()),
            "severity": "major",
            "title": "Wrong rebar grade in pour P-12",
            "cost_impact_amount": "12000",
            "cost_impact_currency": "EUR",
        },
        source_module="qms",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_ncr_raised_fanout(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    names = [n for n, _ in captured]
    assert "procurement.supplier_rating_update" in names
    assert "bi_dashboards.kpi_recompute" in names
    rating = next(d for n, d in captured if n == "procurement.supplier_rating_update")
    assert rating["cost_impact_amount"] == "12000"
    assert rating["cost_impact_currency"] == "EUR"
    kpi = next(d for n, d in captured if n == "bi_dashboards.kpi_recompute")
    assert "copq" in kpi["kpi_codes"]
    assert "first_pass_yield" in kpi["kpi_codes"]
