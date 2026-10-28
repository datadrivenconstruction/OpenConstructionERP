"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests: QMS ITP hold-point workflow (item 12).

Covers the bounded increment:
    - spec linkage (link_itp_item_to_spec) + same-plan / self-cycle guards
    - hold-point predecessor sequencing guard on completion
    - signer-role authority gating
    - evidence attachment CRUD + denormalised id sync + idempotency
    - hold-point release pre-conditions + event emission
    - hold_point_passed / hold_point_failed event publishing

Service-level tests against the shared PostgreSQL fixture with per-test
transaction isolation (mirrors test_qms_fsm.py). No network I/O.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qms.schemas import (
    HoldPointReleaseCreate,
    InspectionAttachmentCreate,
    InspectionCreate,
    InspectionSignatureCreate,
    ITPItemCreate,
    ITPItemLinkSpec,
    ITPPlanCreate,
)
from app.modules.qms.service import QMSService
from tests._pg import transactional_session

_PROJECT_ID = uuid.uuid4()

# Patch target for the event bus so detached publishes are captured, not fired.
_PUBLISH = "app.modules.qms.service.event_bus.publish_detached"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as sess:
        yield sess


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> QMSService:
    return QMSService(session)


async def _plan_with_item(
    svc: QMSService,
    *,
    hold: str = "hold",
    responsible_role: str | None = None,
    signatories_required: int = 1,
):
    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=_PROJECT_ID, name="P", work_type="concrete"),
    )
    item = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="Pour gate",
            hold_witness_point=hold,
            responsible_role=responsible_role,
            signatories_required=signatories_required,
        ),
    )
    return plan, item


# ── Spec linkage ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_itp_item_to_spec_sets_fields(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    boq_id = uuid.uuid4()
    linked = await svc.link_itp_item_to_spec(
        item.id,
        ITPItemLinkSpec(
            boq_position_id=boq_id,
            csi_section_ref="03 30 00",
            spec_drawing_ref="S-101",
            bim_element_id="elem_001",
        ),
    )
    assert linked.boq_position_id == boq_id
    assert linked.csi_section_ref == "03 30 00"
    assert linked.spec_drawing_ref == "S-101"
    assert linked.bim_element_id == "elem_001"


@pytest.mark.asyncio
async def test_link_self_predecessor_rejected(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    with pytest.raises(ValueError, match="own predecessor"):
        await svc.link_itp_item_to_spec(
            item.id,
            ITPItemLinkSpec(predecessor_itp_item_id=item.id),
        )


@pytest.mark.asyncio
async def test_link_cross_plan_predecessor_rejected(svc: QMSService) -> None:
    _p1, item1 = await _plan_with_item(svc)
    _p2, item2 = await _plan_with_item(svc)
    with pytest.raises(ValueError, match="same ITP plan"):
        await svc.link_itp_item_to_spec(
            item1.id,
            ITPItemLinkSpec(predecessor_itp_item_id=item2.id),
        )


@pytest.mark.asyncio
async def test_add_item_with_predecessor_in_same_plan(svc: QMSService) -> None:
    plan, item1 = await _plan_with_item(svc)
    item2 = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="Strip formwork",
            hold_witness_point="hold",
            predecessor_itp_item_id=item1.id,
        ),
    )
    assert item2.predecessor_itp_item_id == item1.id


# ── Predecessor sequencing guard ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_predecessor_status_no_predecessor_passes(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    status = await svc.check_hold_point_predecessor_status(item.id)
    assert status["predecessor_passed"] is True


@pytest.mark.asyncio
async def test_complete_blocked_when_predecessor_not_passed(svc: QMSService) -> None:
    plan, pred = await _plan_with_item(svc)
    dependent = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="Strip formwork",
            hold_witness_point="hold",
            predecessor_itp_item_id=pred.id,
        ),
    )
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=dependent.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()), pytest.raises(ValueError, match="Blocked: predecessor"):
        await svc.complete_inspection(insp.id, result="passed")


@pytest.mark.asyncio
async def test_complete_unblocked_after_predecessor_passes(svc: QMSService) -> None:
    plan, pred = await _plan_with_item(svc)
    dependent = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="Strip formwork",
            hold_witness_point="hold",
            predecessor_itp_item_id=pred.id,
        ),
    )
    # Pass the predecessor inspection first.
    pred_insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=pred.id),
    )
    await svc.add_signature(
        pred_insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(pred_insp.id, result="passed")
    # Now the dependent inspection can pass.
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=dependent.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        done = await svc.complete_inspection(insp.id, result="passed")
    assert done.status == "passed"


@pytest.mark.asyncio
async def test_failing_dependent_not_blocked_by_predecessor(svc: QMSService) -> None:
    """A failure must always be recordable regardless of predecessor state."""
    plan, pred = await _plan_with_item(svc)
    dependent = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            control_point_name="Strip formwork",
            hold_witness_point="hold",
            predecessor_itp_item_id=pred.id,
        ),
    )
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=dependent.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        done = await svc.complete_inspection(insp.id, result="failed")
    assert done.status == "failed"


# ── Signer-role authority gating ───────────────────────────────────────────


def test_validate_signer_role_ladder() -> None:
    # client (rank 4) requires client-or-above; GC (rank 3) is below.
    with pytest.raises(ValueError, match="below"):
        QMSService.validate_signer_role("client", "GC")
    # GC requirement satisfied by GC and by client (higher), not subcontractor.
    QMSService.validate_signer_role("GC", "GC")
    QMSService.validate_signer_role("GC", "client")
    with pytest.raises(ValueError, match="below"):
        QMSService.validate_signer_role("GC", "subcontractor")
    # Empty / unknown required role never gates.
    QMSService.validate_signer_role(None, "subcontractor")
    QMSService.validate_signer_role("foreman", "subcontractor")


@pytest.mark.asyncio
async def test_add_signature_role_gated(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc, responsible_role="client")
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    with pytest.raises(ValueError, match="below"):
        await svc.add_signature(
            insp.id,
            InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
        )
    # A client-level signer is accepted.
    sig = await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="client"),
    )
    assert sig.signer_role == "client"


@pytest.mark.asyncio
async def test_signature_captures_non_repudiation(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    sig = await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
        signer_ip="203.0.113.7",
        signer_user_agent="Mozilla/5.0 test",
    )
    assert sig.signer_ip == "203.0.113.7"
    assert sig.signer_user_agent == "Mozilla/5.0 test"
    assert sig.timestamp_utc is not None


# ── Evidence attachments ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attach_evidence_syncs_denormalised_ids(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    doc_id = uuid.uuid4()
    digest = "a" * 64
    att = await svc.add_inspection_attachment(
        insp.id,
        InspectionAttachmentCreate(
            document_id=doc_id,
            caption="Slab photo",
            file_hash_sha256=digest,
        ),
        uploaded_by_user_id=uuid.uuid4(),
    )
    assert att.document_id == doc_id
    assert att.file_hash_sha256 == digest
    refreshed = await svc.repo.get_inspection(insp.id)
    assert refreshed is not None
    assert str(doc_id) in (refreshed.attachment_document_ids or [])


@pytest.mark.asyncio
async def test_attach_evidence_duplicate_rejected(svc: QMSService) -> None:
    insp = await svc.schedule_inspection(InspectionCreate(project_id=_PROJECT_ID))
    doc_id = uuid.uuid4()
    await svc.add_inspection_attachment(
        insp.id,
        InspectionAttachmentCreate(document_id=doc_id),
    )
    with pytest.raises(ValueError, match="already attached"):
        await svc.add_inspection_attachment(
            insp.id,
            InspectionAttachmentCreate(document_id=doc_id),
        )


# ── Hold-point release ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_release_requires_passed_inspection(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    with pytest.raises(ValueError, match="must have passed"):
        await svc.release_hold_point(
            insp.id,
            HoldPointReleaseCreate(justification="Proceed"),
        )


@pytest.mark.asyncio
async def test_release_hold_point_happy_path_emits_event(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    publish = MagicMock()
    with patch(_PUBLISH, publish):
        await svc.complete_inspection(insp.id, result="passed")
        release = await svc.release_hold_point(
            insp.id,
            HoldPointReleaseCreate(justification="Concrete strength confirmed"),
            released_by_user_id=uuid.uuid4(),
        )
    assert release.justification == "Concrete strength confirmed"
    events = [c.args[0] for c in publish.call_args_list]
    assert "qms.inspection.hold_point_passed" in events
    assert "qms.inspection.hold_point_released" in events


@pytest.mark.asyncio
async def test_release_twice_rejected(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(insp.id, result="passed")
        await svc.release_hold_point(
            insp.id,
            HoldPointReleaseCreate(justification="Once"),
        )
        with pytest.raises(ValueError, match="already been released"):
            await svc.release_hold_point(
                insp.id,
                HoldPointReleaseCreate(justification="Twice"),
            )


@pytest.mark.asyncio
async def test_hold_point_failed_event_on_fail(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    publish = MagicMock()
    with patch(_PUBLISH, publish):
        await svc.complete_inspection(insp.id, result="failed")
    events = [c.args[0] for c in publish.call_args_list]
    assert "qms.inspection.hold_point_failed" in events


@pytest.mark.asyncio
async def test_review_point_emits_no_hold_event(svc: QMSService) -> None:
    """A plain 'review' control point is not a hold/witness gate."""
    _plan, item = await _plan_with_item(svc, hold="review")
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    publish = MagicMock()
    with patch(_PUBLISH, publish):
        await svc.complete_inspection(insp.id, result="passed")
    events = [c.args[0] for c in publish.call_args_list]
    assert "qms.inspection.hold_point_passed" not in events
    # And releasing a review point is not allowed.
    with pytest.raises(ValueError, match="hold or witness"):
        await svc.release_hold_point(
            insp.id,
            HoldPointReleaseCreate(justification="x"),
        )


# ── Quality-gate enforcement for downstream modules (gap #3) ───────────────


@pytest.mark.asyncio
async def test_review_point_gate_always_satisfied(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc, hold="review")
    status = await svc.is_hold_point_satisfied(item.id)
    assert status["is_hold_point"] is False
    assert status["satisfied"] is True


@pytest.mark.asyncio
async def test_hold_point_not_satisfied_without_inspection(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    status = await svc.is_hold_point_satisfied(item.id)
    assert status["satisfied"] is False
    assert "no inspection" in (status["reason"] or "")
    # And the fail-closed guard raises.
    with pytest.raises(ValueError, match="Blocked by quality gate"):
        await svc.assert_downstream_action_allowed(item.id)


@pytest.mark.asyncio
async def test_hold_point_passed_not_satisfied_until_released(svc: QMSService) -> None:
    """A hold point that passed still blocks downstream work until released."""
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(insp.id, result="passed")
    status = await svc.is_hold_point_satisfied(item.id)
    assert status["satisfied"] is False
    assert "not been released" in (status["reason"] or "")
    # Release unblocks it.
    with patch(_PUBLISH, MagicMock()):
        await svc.release_hold_point(insp.id, HoldPointReleaseCreate(justification="ok"))
    status2 = await svc.is_hold_point_satisfied(item.id)
    assert status2["satisfied"] is True
    # And the guard no longer raises.
    await svc.assert_downstream_action_allowed(item.id)


@pytest.mark.asyncio
async def test_witness_point_satisfied_on_pass(svc: QMSService) -> None:
    """A witness point is satisfied on a pass (no manual release needed)."""
    _plan, item = await _plan_with_item(svc, hold="witness")
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(insp.id, result="passed")
    status = await svc.is_hold_point_satisfied(item.id)
    assert status["satisfied"] is True


@pytest.mark.asyncio
async def test_failed_hold_point_blocks_downstream(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(insp.id, result="failed")
    status = await svc.is_hold_point_satisfied(item.id)
    assert status["satisfied"] is False
    assert "failed" in (status["reason"] or "")


# ── Approval integration on failed / conditional (gap #4) ──────────────────


@pytest.mark.asyncio
async def test_failed_hold_point_emits_approval_requested(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    publish = MagicMock()
    with patch(_PUBLISH, publish):
        await svc.complete_inspection(insp.id, result="failed")
    events = [c.args[0] for c in publish.call_args_list]
    assert "qms.inspection.approval_requested" in events


@pytest.mark.asyncio
async def test_passed_hold_point_does_not_request_approval(svc: QMSService) -> None:
    _plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    publish = MagicMock()
    with patch(_PUBLISH, publish):
        await svc.complete_inspection(insp.id, result="passed")
    events = [c.args[0] for c in publish.call_args_list]
    assert "qms.inspection.approval_requested" not in events


# ── Compliance export (gap #7) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inspection_compliance_record_bundles_evidence_and_signatures(
    svc: QMSService,
) -> None:
    _plan, item = await _plan_with_item(svc, responsible_role="GC")
    await svc.link_itp_item_to_spec(
        item.id,
        ITPItemLinkSpec(csi_section_ref="03 30 00", spec_drawing_ref="S-101"),
    )
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id, location_ref="Grid A1"),
    )
    digest = "b" * 64
    await svc.add_inspection_attachment(
        insp.id,
        InspectionAttachmentCreate(document_id=uuid.uuid4(), file_hash_sha256=digest),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
        signer_ip="203.0.113.9",
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(insp.id, result="passed")
    record = await svc.build_inspection_compliance_record(insp.id)
    assert record["status"] == "passed"
    assert record["control_point_name"] == "Pour gate"
    assert record["csi_section_ref"] == "03 30 00"
    assert record["location_ref"] == "Grid A1"
    assert len(record["signatures"]) == 1
    assert record["signatures"][0]["signer_ip"] == "203.0.113.9"
    assert len(record["evidence"]) == 1
    assert record["evidence"][0]["file_hash_sha256"] == digest


@pytest.mark.asyncio
async def test_plan_compliance_export_collects_all_inspections(svc: QMSService) -> None:
    plan, item = await _plan_with_item(svc)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=_PROJECT_ID, itp_item_id=item.id),
    )
    await svc.add_signature(
        insp.id,
        InspectionSignatureCreate(signer_user_id=uuid.uuid4(), signer_role="GC"),
    )
    with patch(_PUBLISH, MagicMock()):
        await svc.complete_inspection(insp.id, result="passed")
    export = await svc.build_plan_compliance_export(plan.id)
    assert export["plan_id"] == str(plan.id)
    assert export["work_type"] == "concrete"
    assert len(export["records"]) == 1
    assert export["records"][0]["inspection_id"] == str(insp.id)
