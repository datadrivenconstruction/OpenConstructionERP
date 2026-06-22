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
from fastapi import HTTPException
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


# ── 5. Cross-tenant GET-by-id IDOR guard (Max-Audit #15) ───────────────────
#
# Max-Audit v8.8.3 #15: the single-item READ endpoints for project-scoped HSE
# resources fetched the row by URL id and returned it WITHOUT calling
# _guard_project(existing.project_id, ...), even though their PATCH/DELETE
# siblings do. A VIEWER in tenant A could therefore GET a JSA / permit / audit
# / CAPA / finding belonging to tenant B by guessing a UUID. These tests drive
# the router handlers directly with a verify_project_access that denies the
# foreign project (404, the same opaque surface the real dependency uses) and
# assert the read is blocked. They FAIL on the pre-fix handlers (which never
# called the guard) and PASS once the guard is threaded in.


class _DenyForProject:
    """Stand-in for ``verify_project_access`` that denies one project.

    Mirrors the real helper: a 404 is raised for both "missing" and "denied"
    so the response is opaque. Any *other* project id is allowed through.
    """

    def __init__(self, denied_project_id: uuid.UUID) -> None:
        self.denied = denied_project_id
        self.calls: list[Any] = []

    async def __call__(self, project_id: Any, user_id: Any, session: Any) -> None:
        self.calls.append(project_id)
        if project_id == self.denied:
            raise HTTPException(status_code=404, detail="Project not found")


def _seed_jsa(svc: Any, project_id: uuid.UUID) -> uuid.UUID:
    from app.modules.hse_advanced.models import JobSafetyAnalysis

    now = datetime.now(UTC)
    jsa = JobSafetyAnalysis(
        project_id=project_id,
        task_description="Confined-space entry",
        work_date="2026-06-01",
        status="approved",
        hazards=[],
        required_ppe=[],
        risk_score=9,
        created_at=now,
        updated_at=now,
    )
    jsa.id = uuid.uuid4()
    svc.jsa_repo.rows[jsa.id] = jsa
    return jsa.id


def _seed_permit(svc: Any, project_id: uuid.UUID) -> uuid.UUID:
    from app.modules.hse_advanced.models import PermitToWork

    permit = PermitToWork(
        project_id=project_id,
        permit_number="PTW-001",
        permit_type="hot_work",
        status="active",
    )
    permit.id = uuid.uuid4()
    svc.permit_repo.rows[permit.id] = permit
    return permit.id


def _seed_audit(svc: Any, project_id: uuid.UUID) -> uuid.UUID:
    from app.modules.hse_advanced.models import SafetyAudit

    audit = SafetyAudit(
        project_id=project_id,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="in_progress",
        summary="",
    )
    audit.id = uuid.uuid4()
    svc.audit_repo.rows[audit.id] = audit
    return audit.id


def _seed_capa(svc: Any, project_id: uuid.UUID) -> uuid.UUID:
    from app.modules.hse_advanced.models import CorrectiveAction

    capa = CorrectiveAction(
        project_id=project_id,
        source_type="manual",
        title="Fix guardrail",
        description="x",
        target_date=date.today(),
        status="open",
    )
    capa.id = uuid.uuid4()
    svc.capa_repo.rows[capa.id] = capa
    return capa.id


@pytest.mark.asyncio
async def test_get_jsa_denies_foreign_project_viewer() -> None:
    """A viewer outside the JSA's project gets 404 (no cross-tenant read)."""
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    jsa_id = _seed_jsa(svc, PROJECT_B)
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.get_jsa(jsa_id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    # The guard must have been consulted with the row's true project.
    assert guard.calls == [PROJECT_B]


@pytest.mark.asyncio
async def test_get_jsa_allows_member_of_project() -> None:
    """A user with access to the JSA's project reads it normally."""
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    jsa_id = _seed_jsa(svc, PROJECT_A)
    guard = _DenyForProject(PROJECT_B)  # PROJECT_A is allowed

    with patch.object(hse_router, "verify_project_access", guard):
        resp = await hse_router.get_jsa(jsa_id, USER_ID, svc.session, None, svc)

    assert resp.id == jsa_id
    assert guard.calls == [PROJECT_A]


@pytest.mark.asyncio
async def test_get_permit_denies_foreign_project_viewer() -> None:
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    permit_id = _seed_permit(svc, PROJECT_B)
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.get_permit(permit_id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]


@pytest.mark.asyncio
async def test_get_audit_denies_foreign_project_viewer() -> None:
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    audit_id = _seed_audit(svc, PROJECT_B)
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.get_audit(audit_id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]


@pytest.mark.asyncio
async def test_get_capa_denies_foreign_project_viewer() -> None:
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    capa_id = _seed_capa(svc, PROJECT_B)
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.get_capa(capa_id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]


@pytest.mark.asyncio
async def test_list_findings_denies_foreign_audit_viewer() -> None:
    """Findings are guarded via the parent audit's project."""
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    audit_id = _seed_audit(svc, PROJECT_B)
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.list_findings(audit_id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]


@pytest.mark.asyncio
async def test_create_finding_denies_foreign_audit_viewer() -> None:
    """An attacker cannot inject a finding into another tenant's audit."""
    from app.modules.hse_advanced import router as hse_router

    svc = _make_service()
    audit_id = _seed_audit(svc, PROJECT_B)
    guard = _DenyForProject(PROJECT_B)
    payload = AuditFindingPayload(item_description="Planted finding")

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.create_finding(audit_id, payload, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]
    # No finding row was written for the foreign audit.
    assert all(getattr(r, "audit_id", None) != audit_id for r in svc.finding_repo.rows.values())


@pytest.mark.asyncio
async def test_delete_finding_denies_foreign_audit_viewer() -> None:
    """A finding may only be deleted by someone with access to its audit's
    project; the guard resolves the project via the parent audit.
    """
    from app.modules.hse_advanced import router as hse_router
    from app.modules.hse_advanced.models import SafetyAuditFinding

    svc = _make_service()
    audit_id = _seed_audit(svc, PROJECT_B)
    finding = SafetyAuditFinding(
        audit_id=audit_id,
        item_description="Missing extinguisher",
        category="other",
        severity="high",
        is_passed=False,
    )
    finding.id = uuid.uuid4()
    svc.finding_repo.rows[finding.id] = finding
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.delete_finding(finding.id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]
    assert finding.id in svc.finding_repo.rows  # not deleted


@pytest.mark.asyncio
async def test_get_investigation_denies_foreign_project_via_incident() -> None:
    """Investigations carry no project_id; the guard resolves PROJECT_B via
    the linked safety incident (incident_ref) and denies the viewer.
    """
    from app.modules.hse_advanced import router as hse_router
    from app.modules.hse_advanced.models import HSEIncidentInvestigation

    svc = _make_service()
    incident_id = uuid.uuid4()
    inv = HSEIncidentInvestigation(
        incident_ref=incident_id,
        started_at=datetime.now(UTC),
        status="in_progress",
    )
    inv.id = uuid.uuid4()
    svc.investigation_repo.rows[inv.id] = inv

    # Resolve incident_ref -> PROJECT_B (what investigation_project_id queries).
    class _IncidentSession:
        async def execute(self, stmt: Any) -> Any:
            class _R:
                def scalar_one_or_none(self) -> Any:
                    return PROJECT_B

            return _R()

    svc.session = _IncidentSession()  # type: ignore[assignment]
    guard = _DenyForProject(PROJECT_B)

    with patch.object(hse_router, "verify_project_access", guard):
        with pytest.raises(HTTPException) as exc:
            await hse_router.get_investigation(inv.id, USER_ID, svc.session, None, svc)

    assert exc.value.status_code == 404
    assert guard.calls == [PROJECT_B]
