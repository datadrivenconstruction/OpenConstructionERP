"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the file_approvals notification routing.

The document-approval engine now emits detached events so the ball-holder gets
a notification (the generic approval engine already did; this one did not).
These tests pin the ROUTING logic - which event fires and who it targets - in
memory, without a database: they build transient workflow/step objects and
capture ``_emit`` calls. The event->NotificationService mapping itself reuses
the proven Wave-subscriber pattern and is exercised by the app at runtime.

Run: pytest backend/tests/modules/file_approvals/test_notifications.py -v
"""

import uuid

from app.modules.file_approvals.models import FileApprovalStep, FileApprovalWorkflow
from app.modules.file_approvals.service import ApprovalService


def _svc_with_capture() -> tuple[ApprovalService, list[tuple[str, dict]]]:
    """A service whose ``_emit`` records (event_name, payload) instead of publishing."""
    svc = ApprovalService.__new__(ApprovalService)
    captured: list[tuple[str, dict]] = []
    svc._emit = lambda name, payload: captured.append((name, payload))  # type: ignore[method-assign]
    return svc, captured


def _step(order: int, approver: uuid.UUID | None, decision: str = "pending") -> FileApprovalStep:
    return FileApprovalStep(
        id=uuid.uuid4(),
        sort_order=order,
        approver_id=approver,
        role_label=f"role{order}",
        decision=decision,
    )


def _wf(status: str, steps: list[FileApprovalStep], submitter: uuid.UUID | None = None) -> FileApprovalWorkflow:
    wf = FileApprovalWorkflow(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        file_kind="document",
        file_id=uuid.uuid4(),
        submitted_by_id=submitter,
        status=status,
    )
    wf.steps = steps
    return wf


# ── submit -> first approver ────────────────────────────────────────────────


def test_submitted_targets_the_first_step_approver():
    svc, captured = _svc_with_capture()
    a0, a1 = uuid.uuid4(), uuid.uuid4()
    # Deliberately out of order to prove we sort by sort_order.
    wf = _wf("in_review", [_step(1, a1), _step(0, a0)])

    svc._notify_submitted(wf)

    assert len(captured) == 1
    name, payload = captured[0]
    assert name == "file_approval.submitted"
    assert payload["approver_id"] == str(a0)
    assert payload["step_ordinal"] == 1


def test_submitted_with_no_steps_emits_nothing():
    svc, captured = _svc_with_capture()
    svc._notify_submitted(_wf("in_review", []))
    assert captured == []


# ── decide -> outcome routing ───────────────────────────────────────────────


def test_final_approval_notifies_the_submitter():
    svc, captured = _svc_with_capture()
    submitter = uuid.uuid4()
    wf = _wf("approved", [_step(0, uuid.uuid4(), "approved")], submitter=submitter)

    svc._notify_decided(wf, "approved", uuid.uuid4(), None)

    assert len(captured) == 1
    name, payload = captured[0]
    assert name == "file_approval.approved"
    assert payload["submitter_id"] == str(submitter)


def test_rejection_notifies_the_submitter_with_note():
    svc, captured = _svc_with_capture()
    submitter = uuid.uuid4()
    wf = _wf("rejected", [_step(0, uuid.uuid4(), "rejected")], submitter=submitter)

    svc._notify_decided(wf, "rejected", uuid.uuid4(), "Fix the north elevation")

    assert len(captured) == 1
    name, payload = captured[0]
    assert name == "file_approval.rejected"
    assert payload["submitter_id"] == str(submitter)
    assert payload["note"] == "Fix the north elevation"


def test_middle_approval_advances_to_next_pending_approver():
    svc, captured = _svc_with_capture()
    a1 = uuid.uuid4()
    # Step 0 just approved, step 1 still pending -> ball moves to step 1.
    wf = _wf(
        "in_review",
        [_step(0, uuid.uuid4(), "approved"), _step(1, a1, "pending")],
    )

    svc._notify_decided(wf, "approved", uuid.uuid4(), None)

    assert len(captured) == 1
    name, payload = captured[0]
    assert name == "file_approval.step_advanced"
    assert payload["approver_id"] == str(a1)
    assert payload["step_ordinal"] == 2


def test_delegation_is_a_soft_no_op():
    svc, captured = _svc_with_capture()
    wf = _wf("in_review", [_step(0, uuid.uuid4(), "pending")])
    svc._notify_decided(wf, "delegated", uuid.uuid4(), None)
    assert captured == []
