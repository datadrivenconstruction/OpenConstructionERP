"""‌⁠‍Security & audit-trail hardening tests for the hse_advanced module.

Covers Round-3 Wave F sweep findings:

* Audit-log rows are emitted for state-change + destructive ops on JSA /
  permit / audit / CAPA / investigation (the auditor "who closed what,
  when" trail).
* The ``active_only`` query param has migrated to a tri-state ``is_active``
  filter on ``/toolbox-topics/`` and ``/jsa-templates/``.
* ``evidence_url`` / ``report_url`` reject ``javascript:`` and ``data:``
  URIs so stored-XSS is not possible through an audit finding.
* Closure-bearing permissions (``close_capa``, ``conduct_audit``,
  ``close_permit``, ``close_investigation``) require MANAGER role.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.permissions import Role, permission_registry
from app.modules.hse_advanced.permissions import register_hse_advanced_permissions
from app.modules.hse_advanced.repository import (
    JSATemplateRepository,
    ToolboxTopicRepository,
)
from app.modules.hse_advanced.schemas import (
    AuditFindingPayload,
    InvestigationCreate,
)
from tests.unit.test_hse_advanced import (  # type: ignore[import-not-found]
    _make_service,
)

PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()
USER_ID = str(uuid.uuid4())


# ── 1. Audit log coverage on FSM / destructive ops ─────────────────────────


@pytest.mark.asyncio
async def test_close_capa_writes_audit_log_row() -> None:
    """``close_capa`` must call ``log_activity`` with status_changed."""
    svc = _make_service()
    from app.modules.hse_advanced.models import CorrectiveAction

    capa = CorrectiveAction(
        project_id=PROJECT_A,
        source_type="manual",
        title="Test CAPA",
        description="x",
        target_date=date.today(),
        status="open",
    )
    capa.id = uuid.uuid4()
    svc.capa_repo.rows[capa.id] = capa

    with patch(
        "app.core.audit_log.log_activity",
        new_callable=AsyncMock,
    ) as mock_log:
        await svc.close_capa(
            capa.id,
            verification_notes="Verified by HSE",
            user_id=USER_ID,
        )

    assert mock_log.await_count == 1
    kwargs = mock_log.await_args.kwargs
    assert kwargs["entity_type"] == "hse_capa"
    assert kwargs["entity_id"] == str(capa.id)
    assert kwargs["action"] == "status_changed"
    assert kwargs["from_status"] == "open"
    assert kwargs["to_status"] == "completed"
    assert str(kwargs["actor_id"]) == USER_ID


@pytest.mark.asyncio
async def test_delete_jsa_writes_audit_log_row() -> None:
    """``delete_jsa`` must capture a deletion audit-log snapshot."""
    svc = _make_service()
    from app.modules.hse_advanced.models import JobSafetyAnalysis

    jsa = JobSafetyAnalysis(
        project_id=PROJECT_A,
        task_description="Demolish wall",
        work_date="2026-06-01",
        status="draft",
        hazards=[],
        required_ppe=[],
        risk_score=4,
    )
    jsa.id = uuid.uuid4()
    svc.jsa_repo.rows[jsa.id] = jsa

    with patch(
        "app.core.audit_log.log_activity",
        new_callable=AsyncMock,
    ) as mock_log:
        await svc.delete_jsa(jsa.id, user_id=USER_ID)

    assert jsa.id not in svc.jsa_repo.rows  # actually deleted
    assert mock_log.await_count == 1
    kwargs = mock_log.await_args.kwargs
    assert kwargs["entity_type"] == "hse_jsa"
    assert kwargs["action"] == "deleted"
    # Snapshot keeps the now-deleted row's project + status discoverable.
    assert kwargs["metadata"]["project_id"] == str(PROJECT_A)
    assert kwargs["metadata"]["status"] == "draft"


@pytest.mark.asyncio
async def test_complete_audit_writes_status_change_audit_row() -> None:
    """``complete_audit`` records a status_changed → completed event."""
    svc = _make_service()
    from app.modules.hse_advanced.models import SafetyAudit

    audit = SafetyAudit(
        project_id=PROJECT_A,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="in_progress",
        summary="",
    )
    audit.id = uuid.uuid4()
    svc.audit_repo.rows[audit.id] = audit

    with patch(
        "app.core.audit_log.log_activity",
        new_callable=AsyncMock,
    ) as mock_log:
        await svc.complete_audit(audit.id, user_id=USER_ID)

    assert mock_log.await_count == 1
    kwargs = mock_log.await_args.kwargs
    assert kwargs["entity_type"] == "hse_audit"
    assert kwargs["from_status"] == "in_progress"
    assert kwargs["to_status"] == "completed"


# ── 2. Tri-state ``is_active`` filter (Round-3 Wave B convention) ─────────


@pytest.mark.asyncio
async def test_jsa_template_repo_accepts_tri_state_is_active() -> None:
    """``is_active=None`` must return both active and inactive rows."""

    captured: list[Any] = []

    class _RecordingSession:
        async def execute(self, stmt: Any) -> Any:
            captured.append(str(stmt))

            class _R:
                def scalars(self) -> Any:
                    class _S:
                        def all(self) -> list[Any]:
                            return []

                    return _S()

                def scalar_one(self) -> int:
                    return 0

            return _R()

    repo = JSATemplateRepository(_RecordingSession())  # type: ignore[arg-type]

    # ``is_active`` is also a SELECT-clause column name, so it appears in
    # the rendered SQL even without a filter. We instead detect the
    # presence of a WHERE-clause reference (``is_active IS true|false``)
    # which only the filtered branches emit.
    await repo.list_templates(is_active=None)
    joined_none = " ".join(captured).lower()
    captured.clear()
    await repo.list_templates(is_active=True)
    joined_true = " ".join(captured).lower()
    captured.clear()
    await repo.list_templates(is_active=False)
    joined_false = " ".join(captured).lower()

    # The WHERE branch emits ``is_active IS ?`` / ``is_active = ?`` —
    # the None branch must contain no such predicate.
    assert "is_active is " not in joined_none and "is_active = " not in joined_none
    assert "is_active is " in joined_true or "is_active = " in joined_true
    assert "is_active is " in joined_false or "is_active = " in joined_false


@pytest.mark.asyncio
async def test_toolbox_topic_repo_legacy_active_only_still_works() -> None:
    """Legacy ``active_only=True`` callers (e.g. test stubs) keep working."""

    captured: list[str] = []

    class _RecordingSession:
        async def execute(self, stmt: Any) -> Any:
            captured.append(str(stmt))

            class _R:
                def scalars(self) -> Any:
                    class _S:
                        def all(self) -> list[Any]:
                            return []

                    return _S()

                def scalar_one(self) -> int:
                    return 0

            return _R()

    repo = ToolboxTopicRepository(_RecordingSession())  # type: ignore[arg-type]

    # Legacy alias: active_only=False should disable the filter (tri-state
    # equivalent to is_active=None) — no ``is_active IS ?`` predicate.
    await repo.list_topics(active_only=False)
    joined = " ".join(captured).lower()
    assert "is_active is " not in joined and "is_active = " not in joined

    # And active_only=True must still apply the filter (back-compat).
    captured.clear()
    await repo.list_topics(active_only=True)
    joined_true = " ".join(captured).lower()
    assert "is_active is " in joined_true or "is_active = " in joined_true


# ── 3. URL safety on evidence / report links ──────────────────────────────


def test_evidence_url_rejects_javascript_scheme() -> None:
    """A ``javascript:`` URL in an audit finding must be rejected at the
    schema layer so it can never reach the DB.
    """
    with pytest.raises(ValidationError) as exc:
        AuditFindingPayload(
            item_description="Tripping hazard near scaffold",
            evidence_url="javascript:alert('xss')",
        )
    assert "javascript" in str(exc.value).lower() or "not allowed" in str(exc.value).lower()


def test_evidence_url_accepts_http_and_relative_paths() -> None:
    """``http(s)://...`` and ``/uploads/...`` must pass through unchanged."""
    p1 = AuditFindingPayload(
        item_description="Photo of finding",
        evidence_url="https://cdn.example.com/photo.jpg",
    )
    assert p1.evidence_url == "https://cdn.example.com/photo.jpg"

    p2 = AuditFindingPayload(
        item_description="Internal upload",
        evidence_url="/uploads/photos/abc.jpg",
    )
    assert p2.evidence_url == "/uploads/photos/abc.jpg"

    # Blank / None still allowed.
    p3 = AuditFindingPayload(item_description="No evidence")
    assert p3.evidence_url is None


def test_investigation_report_url_rejects_data_uri() -> None:
    """``InvestigationCreate.report_url`` must reject ``data:`` URIs."""
    with pytest.raises(ValidationError):
        InvestigationCreate(
            incident_ref=uuid.uuid4(),
            started_at=datetime.now(UTC),
            report_url="data:text/html,<script>alert(1)</script>",
        )


# ── 4. Closure-bearing permissions require MANAGER ─────────────────────────


def test_closure_permissions_require_manager_role() -> None:
    """Round-3 Wave F: HSE closures must require manager-or-above."""
    register_hse_advanced_permissions()

    for perm in (
        "hse_advanced.close_capa",
        "hse_advanced.close_permit",
        "hse_advanced.conduct_audit",
        "hse_advanced.close_investigation",
    ):
        required = permission_registry.get_min_role(perm)
        # A plain EDITOR must NOT satisfy a closure permission anymore.
        assert required == Role.MANAGER, f"{perm} must require MANAGER (Round-3 Wave F closure gate), got {required}"
