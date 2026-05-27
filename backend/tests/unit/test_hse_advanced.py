"""Unit tests for the HSE Advanced module.

Coverage:
    * pure helpers — risk score, JSA risk, permit window, TRIR / LTIFR,
      days-without-LTI, audit score, certification validity, worker
      blocked-for-work calculation
    * JSA / PTW / CAPA / Audit state-machine transitions
      (valid + invalid raise HTTPException 409)
    * service workflow events emitted via ``event_bus.publish_detached``
    * ``conduct_audit`` creates a CAPA per failed finding
    * repository CRUD basics through stubbed sessions
    * permission registry contract
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.modules.hse_advanced.models import (
    CorrectiveAction,
    JobSafetyAnalysis,
    PermitToWork,
    SafetyAudit,
    SafetyAuditFinding,
    SafetyCertification,
)
from app.modules.hse_advanced.permissions import register_hse_advanced_permissions
from app.modules.hse_advanced.schemas import (
    AuditCreate,
    AuditFindingCreate,
    CAPACreate,
    CertificationCreate,
    JSACreate,
    JSAHazardEntry,
    PermitCreate,
)
from app.modules.hse_advanced.service import (
    HSEAdvancedService,
    allowed_audit_transitions,
    allowed_capa_transitions,
    allowed_certification_transitions,
    allowed_jsa_transitions,
    allowed_permit_transitions,
    compute_audit_score,
    compute_jsa_risk,
    compute_ltifr,
    compute_risk_score,
    compute_risk_tier,
    compute_trir,
    days_without_lti,
    is_certification_valid,
    is_permit_active,
    is_user_blocked_for_work,
)

PROJECT_ID = uuid.uuid4()


# ── Stubs ──────────────────────────────────────────────────────────────────


class _StubSession:
    """Minimal async-session stub — refresh is a no-op; flush returns None."""

    async def refresh(self, obj: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> Any:  # pragma: no cover - unused
        return None

    async def delete(self, obj: Any) -> None:
        return None

    def expire_all(self) -> None:
        return None


class _StubRepo:
    """Generic in-memory repository with create / get_by_id / update_fields / delete."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not getattr(obj, "created_at", None):
            obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return self.rows.get(item_id)

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(item_id)
        if row is not None:
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = datetime.now(UTC)

    async def delete(self, item_id: uuid.UUID) -> None:
        self.rows.pop(item_id, None)


class _FindingRepo(_StubRepo):
    async def list_for_audit(self, audit_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "audit_id", None) == audit_id]


class _JSATemplateRepo(_StubRepo):
    async def list_templates(
        self,
        *,
        trade: str | None = None,
        region: str | None = None,
        active_only: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Any], int]:
        rows = [
            r
            for r in self.rows.values()
            if (trade is None or getattr(r, "trade", None) == trade)
            and (region is None or getattr(r, "region", None) == region)
            and (not active_only or getattr(r, "is_active", True))
        ]
        return rows[offset : offset + limit], len(rows)


def _make_service() -> HSEAdvancedService:
    svc = HSEAdvancedService.__new__(HSEAdvancedService)
    svc.session = _StubSession()
    svc.investigation_repo = _StubRepo()
    svc.jsa_repo = _StubRepo()
    svc.permit_repo = _StubRepo()
    svc.talk_repo = _StubRepo()
    svc.attendance_repo = _StubRepo()
    svc.topic_repo = _StubRepo()
    svc.ppe_repo = _StubRepo()
    svc.audit_repo = _StubRepo()
    svc.finding_repo = _FindingRepo()
    svc.capa_repo = _StubRepo()
    svc.cert_repo = _StubRepo()
    svc.jsa_template_repo = _JSATemplateRepo()
    return svc


# ── Pure helpers: risk score & risk tier ─────────────────────────────────


def test_compute_risk_score_basic() -> None:
    assert compute_risk_score(3, 4) == 12
    assert compute_risk_score(1, 1) == 1
    assert compute_risk_score(5, 5) == 25


def test_compute_risk_score_clamps_out_of_range() -> None:
    """severity / likelihood are clamped to [1, 5]."""
    assert compute_risk_score(0, 7) == 1 * 5
    assert compute_risk_score(-3, 9) == 1 * 5
    assert compute_risk_score(99, 99) == 25


def test_compute_risk_tier_brackets() -> None:
    assert compute_risk_tier(1) == "low"
    assert compute_risk_tier(5) == "low"
    assert compute_risk_tier(6) == "medium"
    assert compute_risk_tier(10) == "medium"
    assert compute_risk_tier(11) == "high"
    assert compute_risk_tier(15) == "high"
    assert compute_risk_tier(16) == "critical"
    assert compute_risk_tier(25) == "critical"


def test_compute_jsa_risk_empty() -> None:
    assert compute_jsa_risk(None) == 0
    assert compute_jsa_risk([]) == 0


def test_compute_jsa_risk_max_of_per_hazard() -> None:
    hazards = [
        {"severity": 2, "likelihood": 3},  # 6
        {"severity": 5, "likelihood": 4},  # 20 ← max
        {"severity": 1, "likelihood": 1},  # 1
    ]
    assert compute_jsa_risk(hazards) == 20


def test_compute_jsa_risk_ignores_malformed() -> None:
    hazards = [
        {"severity": "not-a-number", "likelihood": 3},
        {"severity": 4, "likelihood": 2},
    ]
    assert compute_jsa_risk(hazards) == 8


# ── Pure helpers: permit active window ───────────────────────────────────


def test_is_permit_active_when_in_window() -> None:
    now = datetime.now(UTC)
    permit = SimpleNamespace(
        status="active",
        work_start=now - timedelta(hours=1),
        work_end=now + timedelta(hours=1),
    )
    assert is_permit_active(permit, now=now) is True


def test_is_permit_active_false_when_status_not_active() -> None:
    now = datetime.now(UTC)
    permit = SimpleNamespace(
        status="requested",
        work_start=now - timedelta(hours=1),
        work_end=now + timedelta(hours=1),
    )
    assert is_permit_active(permit, now=now) is False


def test_is_permit_active_false_when_outside_window() -> None:
    now = datetime.now(UTC)
    permit = SimpleNamespace(
        status="active",
        work_start=now - timedelta(days=3),
        work_end=now - timedelta(days=1),
    )
    assert is_permit_active(permit, now=now) is False


def test_is_permit_active_handles_none() -> None:
    assert is_permit_active(None) is False


# ── Pure helpers: TRIR / LTIFR / days-without-LTI ────────────────────────


def test_compute_trir_basic() -> None:
    # 2 recordable * 200000 / 100000 hours = 4.0
    assert compute_trir(2, 100000) == Decimal("4.0000")


def test_compute_trir_zero_hours_returns_zero() -> None:
    assert compute_trir(10, 0) == Decimal("0")
    assert compute_trir(10, -1) == Decimal("0")


def test_compute_ltifr_basic() -> None:
    # 1 LTI * 1_000_000 / 200000 hours = 5.0
    assert compute_ltifr(1, 200000) == Decimal("5.0000")


def test_compute_ltifr_zero_hours_returns_zero() -> None:
    assert compute_ltifr(5, 0) == Decimal("0")


def test_days_without_lti_never() -> None:
    assert days_without_lti([], today=date(2026, 5, 12)) == 9999


def test_days_without_lti_simple() -> None:
    assert days_without_lti([date(2026, 5, 1)], today=date(2026, 5, 12)) == 11


def test_days_without_lti_string_dates() -> None:
    assert days_without_lti(["2026-04-01"], today=date(2026, 5, 12)) == 41


def test_days_without_lti_picks_latest() -> None:
    assert (
        days_without_lti(
            [date(2026, 1, 1), date(2026, 5, 10), date(2026, 3, 4)],
            today=date(2026, 5, 12),
        )
        == 2
    )


# ── Pure helpers: audit score ────────────────────────────────────────────


def test_compute_audit_score_empty() -> None:
    score, max_score, pct = compute_audit_score([])
    assert score == Decimal("0")
    assert max_score == Decimal("0")
    assert pct == 0.0


def test_compute_audit_score_weighted() -> None:
    findings = [
        SafetyAuditFinding(severity="low", is_passed=True),
        SafetyAuditFinding(severity="high", is_passed=True),
        SafetyAuditFinding(severity="critical", is_passed=False),
    ]
    # weights: low=1, high=4, critical=8 → max=13, passed=5 → ~38.46%
    score, max_score, pct = compute_audit_score(findings)
    assert score == Decimal("5")
    assert max_score == Decimal("13")
    assert 38.4 <= pct <= 38.5


def test_compute_audit_score_dicts() -> None:
    findings: list[dict[str, Any]] = [
        {"severity": "med", "is_passed": True},
        {"severity": "med", "is_passed": True},
    ]
    score, max_score, pct = compute_audit_score(findings)
    assert score == Decimal("4")
    assert max_score == Decimal("4")
    assert pct == 100.0


# ── Pure helpers: certification validity & blocked-for-work ──────────────


def test_is_certification_valid_true() -> None:
    cert = SafetyCertification(
        cert_type="working_at_height",
        issue_date=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
        status="valid",
    )
    assert is_certification_valid(cert, today=date(2026, 5, 12)) is True


def test_is_certification_valid_expired_by_date() -> None:
    cert = SafetyCertification(
        cert_type="working_at_height",
        issue_date=date(2024, 1, 1),
        valid_until=date(2025, 1, 1),
        status="valid",
    )
    assert is_certification_valid(cert, today=date(2026, 5, 12)) is False


def test_is_certification_valid_revoked() -> None:
    cert = SafetyCertification(
        cert_type="working_at_height",
        issue_date=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
        status="revoked",
    )
    assert is_certification_valid(cert, today=date(2026, 5, 12)) is False


def test_is_certification_valid_handles_none() -> None:
    assert is_certification_valid(None) is False


def test_is_user_blocked_missing_required_cert() -> None:
    user_id = uuid.uuid4()
    blocked, missing = is_user_blocked_for_work(
        user_id,
        required_cert_types=["working_at_height", "first_aid"],
        certifications=[],
        today=date(2026, 5, 12),
    )
    assert blocked is True
    assert set(missing) == {"working_at_height", "first_aid"}


def test_is_user_blocked_with_expired_cert() -> None:
    user_id = uuid.uuid4()
    cert = SafetyCertification(
        owner_user_id=user_id,
        cert_type="working_at_height",
        issue_date=date(2024, 1, 1),
        valid_until=date(2025, 1, 1),
        status="valid",
    )
    blocked, missing = is_user_blocked_for_work(
        user_id,
        required_cert_types=["working_at_height"],
        certifications=[cert],
        today=date(2026, 5, 12),
    )
    assert blocked is True
    assert missing == ["working_at_height"]


def test_is_user_blocked_all_valid() -> None:
    user_id = uuid.uuid4()
    cert = SafetyCertification(
        owner_user_id=user_id,
        cert_type="working_at_height",
        issue_date=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
        status="valid",
    )
    blocked, missing = is_user_blocked_for_work(
        user_id,
        required_cert_types=["working_at_height"],
        certifications=[cert],
        today=date(2026, 5, 12),
    )
    assert blocked is False
    assert missing == []


def test_is_user_blocked_empty_required_returns_false() -> None:
    blocked, missing = is_user_blocked_for_work(
        uuid.uuid4(),
        required_cert_types=[],
        certifications=[],
    )
    assert blocked is False
    assert missing == []


# ── State machines ────────────────────────────────────────────────────────


def test_allowed_jsa_transitions() -> None:
    assert "under_review" in allowed_jsa_transitions("draft")
    assert "approved" in allowed_jsa_transitions("under_review")
    assert allowed_jsa_transitions("archived") == []


def test_allowed_permit_transitions() -> None:
    assert "approved" in allowed_permit_transitions("requested")
    assert "active" in allowed_permit_transitions("approved")
    assert "closed" in allowed_permit_transitions("active")
    assert allowed_permit_transitions("closed") == []


def test_allowed_audit_transitions() -> None:
    assert "in_progress" in allowed_audit_transitions("scheduled")
    assert "completed" in allowed_audit_transitions("in_progress")
    assert allowed_audit_transitions("completed") == []


def test_allowed_capa_transitions() -> None:
    assert "completed" in allowed_capa_transitions("open")
    assert "overdue" in allowed_capa_transitions("open")
    assert allowed_capa_transitions("completed") == []


def test_allowed_certification_transitions() -> None:
    assert "expired" in allowed_certification_transitions("valid")
    assert "revoked" in allowed_certification_transitions("valid")
    assert allowed_certification_transitions("revoked") == []


# ── Service workflow: JSA ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_jsa_emits_event() -> None:
    svc = _make_service()
    jsa = JobSafetyAnalysis(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        task_description="Pour slab",
        work_date="2026-05-12",
        status="draft",
        hazards=[],
        required_ppe=[],
        risk_score=0,
    )
    await svc.jsa_repo.create(jsa)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.submit_jsa(jsa.id)

    assert result.status == "under_review"
    assert mock_pub.called
    assert mock_pub.call_args.args[0] == "hse.jsa.submitted"


@pytest.mark.asyncio
async def test_submit_jsa_invalid_transition_raises() -> None:
    svc = _make_service()
    jsa = JobSafetyAnalysis(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        task_description="Pour slab",
        work_date="2026-05-12",
        status="archived",  # terminal
        hazards=[],
        required_ppe=[],
        risk_score=0,
    )
    await svc.jsa_repo.create(jsa)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.submit_jsa(jsa.id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_approve_jsa_emits_event() -> None:
    svc = _make_service()
    jsa = JobSafetyAnalysis(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        task_description="Pour slab",
        work_date="2026-05-12",
        status="under_review",
        hazards=[],
        required_ppe=[],
        risk_score=0,
    )
    await svc.jsa_repo.create(jsa)

    approver = uuid.uuid4()
    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.approve_jsa(jsa.id, approver_id=approver)

    assert result.status == "approved"
    assert mock_pub.called
    assert mock_pub.call_args.args[0] == "hse.jsa.approved"


@pytest.mark.asyncio
async def test_create_jsa_computes_risk_score() -> None:
    svc = _make_service()
    data = JSACreate(
        project_id=PROJECT_ID,
        task_description="Erect scaffold",
        work_date="2026-05-12",
        hazards=[
            JSAHazardEntry(step="step1", hazard="Fall", severity=5, likelihood=4),
            JSAHazardEntry(
                step="step2",
                hazard="Pinch",
                severity=2,
                likelihood=2,
            ),
        ],
    )
    with patch("app.modules.hse_advanced.service.event_bus.publish_detached"):
        jsa = await svc.create_jsa(data, user_id="u1")
    assert jsa.risk_score == 20  # max(5*4, 2*2)
    assert jsa.created_by == "u1"


# ── Service workflow: PTW ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_permit_emits_event() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    data = PermitCreate(
        project_id=PROJECT_ID,
        permit_number="PTW-0001",
        permit_type="hot_work",
        work_start=now,
        work_end=now + timedelta(hours=4),
    )
    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        permit = await svc.request_permit(data, user_id="u1")

    assert permit.status == "requested"
    assert mock_pub.called
    assert mock_pub.call_args.args[0] == "hse.permit.requested"


@pytest.mark.asyncio
async def test_request_permit_rejects_bad_window() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    data = PermitCreate(
        project_id=PROJECT_ID,
        permit_number="PTW-0002",
        permit_type="hot_work",
        work_start=now,
        work_end=now - timedelta(hours=1),  # end before start
    )
    with patch("app.modules.hse_advanced.service.event_bus.publish_detached"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.request_permit(data, user_id="u1")
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_approve_permit_emits_event() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    permit = PermitToWork(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        permit_number="PTW-0003",
        permit_type="hot_work",
        work_start=now,
        work_end=now + timedelta(hours=2),
        status="requested",
        description="",
        conditions="",
        closure_checklist_passed=False,
        closure_notes="",
    )
    await svc.permit_repo.create(permit)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.approve_permit(permit.id, approver_id=uuid.uuid4())

    assert result.status == "approved"
    assert mock_pub.called
    assert mock_pub.call_args.args[0] == "hse.permit.approved"


@pytest.mark.asyncio
async def test_activate_permit_emits_event() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    # Hot-work permit requires: jsa_approved + fire_watch + extinguisher.
    permit = PermitToWork(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        permit_number="PTW-0004",
        permit_type="hot_work",
        work_start=now,
        work_end=now + timedelta(hours=2),
        status="approved",
        description="",
        conditions="",
        closure_checklist_passed=False,
        closure_notes="",
        prereq_jsa_approved=True,
        prereq_fire_watch_assigned=True,
        prereq_extinguisher_present=True,
    )
    await svc.permit_repo.create(permit)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.activate_permit(permit.id)
    assert result.status == "active"
    assert mock_pub.call_args.args[0] == "hse.permit.activated"


@pytest.mark.asyncio
async def test_close_permit_requires_checklist_pass() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    permit = PermitToWork(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        permit_number="PTW-0005",
        permit_type="hot_work",
        work_start=now,
        work_end=now + timedelta(hours=2),
        status="active",
        description="",
        conditions="",
        closure_checklist_passed=False,
        closure_notes="",
    )
    await svc.permit_repo.create(permit)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.close_permit(
                permit.id,
                closure_checklist_passed=False,
            )
        assert exc_info.value.status_code == 422

        result = await svc.close_permit(
            permit.id,
            closure_checklist_passed=True,
            closure_notes="All clear",
        )
    assert result.status == "closed"


@pytest.mark.asyncio
async def test_close_permit_invalid_state_raises() -> None:
    svc = _make_service()
    now = datetime.now(UTC)
    permit = PermitToWork(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        permit_number="PTW-0006",
        permit_type="hot_work",
        work_start=now,
        work_end=now + timedelta(hours=2),
        status="requested",  # cannot go straight to closed
        description="",
        conditions="",
        closure_checklist_passed=False,
        closure_notes="",
    )
    await svc.permit_repo.create(permit)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.close_permit(
                permit.id,
                closure_checklist_passed=True,
            )
    assert exc_info.value.status_code == 409


# ── Service workflow: Audits + CAPA ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_audit_basic() -> None:
    svc = _make_service()
    data = AuditCreate(
        project_id=PROJECT_ID,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="scheduled",
    )
    audit = await svc.create_audit(data, user_id="u1")
    assert audit.project_id == PROJECT_ID
    assert audit.status == "scheduled"


@pytest.mark.asyncio
async def test_conduct_audit_creates_capa_per_failure() -> None:
    """Failing findings should each generate a CAPA tied to the audit."""
    svc = _make_service()
    audit = SafetyAudit(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="scheduled",
        summary="",
    )
    await svc.audit_repo.create(audit)

    payload = [
        AuditFindingCreate(
            item_description="PPE not worn",
            category="PPE",
            severity="high",
            is_passed=False,
        ),
        AuditFindingCreate(
            item_description="MSDS available",
            category="other",
            severity="low",
            is_passed=True,
        ),
        AuditFindingCreate(
            item_description="Permit missing",
            category="permit",
            severity="critical",
            is_passed=False,
        ),
    ]
    await svc.conduct_audit(audit.id, payload, user_id="auditor-1")

    # 3 findings persisted
    findings = list(svc.finding_repo.rows.values())
    assert len(findings) == 3

    # 2 failures → 2 CAPAs, each with source_type='audit'
    capas = list(svc.capa_repo.rows.values())
    assert len(capas) == 2
    assert all(c.source_type == "audit" for c in capas)
    assert all(c.source_ref == audit.id for c in capas)


@pytest.mark.asyncio
async def test_complete_audit_emits_event() -> None:
    svc = _make_service()
    audit = SafetyAudit(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="in_progress",
        summary="",
    )
    await svc.audit_repo.create(audit)
    # Add some findings so scoring runs.
    f = SafetyAuditFinding(
        id=uuid.uuid4(),
        audit_id=audit.id,
        item_description="x",
        category="other",
        severity="low",
        is_passed=True,
    )
    await svc.finding_repo.create(f)

    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.complete_audit(audit.id)
    assert result.status == "completed"
    assert mock_pub.call_args.args[0] == "hse.audit.completed"


@pytest.mark.asyncio
async def test_complete_audit_invalid_state_raises() -> None:
    svc = _make_service()
    audit = SafetyAudit(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="cancelled",  # terminal
        summary="",
    )
    await svc.audit_repo.create(audit)
    with pytest.raises(HTTPException) as exc_info:
        await svc.complete_audit(audit.id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_capa_basic() -> None:
    svc = _make_service()
    data = CAPACreate(
        project_id=PROJECT_ID,
        source_type="audit",
        title="Replace damaged hard hats",
        target_date=date(2026, 6, 1),
    )
    capa = await svc.create_capa(data, user_id="u1")
    assert capa.status == "open"
    assert capa.title == "Replace damaged hard hats"


@pytest.mark.asyncio
async def test_close_capa_emits_event_and_transitions() -> None:
    svc = _make_service()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="Test",
        target_date=date.today(),
        status="open",
    )
    await svc.capa_repo.create(capa)
    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.close_capa(capa.id, verification_notes="Done")
    assert result.status == "completed"
    assert mock_pub.call_args.args[0] == "hse.capa.completed"


@pytest.mark.asyncio
async def test_close_capa_invalid_state_raises() -> None:
    svc = _make_service()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="Test",
        target_date=date.today(),
        status="completed",  # terminal
    )
    await svc.capa_repo.create(capa)
    with pytest.raises(HTTPException) as exc_info:
        await svc.close_capa(capa.id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_escalate_capa_emits_event() -> None:
    svc = _make_service()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="Test",
        target_date=date.today() - timedelta(days=5),
        status="open",
    )
    await svc.capa_repo.create(capa)
    with patch("app.modules.hse_advanced.service.event_bus.publish_detached") as mock_pub:
        result = await svc.escalate_capa(capa.id)
    assert result.status == "overdue"
    assert mock_pub.call_args.args[0] == "hse.capa.escalated"


# ── Certifications ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_certification_basic() -> None:
    svc = _make_service()
    data = CertificationCreate(
        cert_type="working_at_height",
        issue_date=date(2026, 1, 1),
        valid_until=date(2027, 1, 1),
    )
    cert = await svc.create_certification(data)
    assert cert.cert_type == "working_at_height"
    assert cert.status == "valid"


# ── Repository CRUD basics ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_create_and_get() -> None:
    repo = _StubRepo()
    obj = SafetyAuditFinding(
        audit_id=uuid.uuid4(),
        item_description="x",
        category="other",
        severity="low",
        is_passed=True,
    )
    created = await repo.create(obj)
    assert created.id is not None
    fetched = await repo.get_by_id(created.id)
    assert fetched is created


@pytest.mark.asyncio
async def test_repo_update_fields_changes_attrs() -> None:
    repo = _StubRepo()
    audit = SafetyAudit(
        project_id=PROJECT_ID,
        audit_type="internal",
        conducted_at=datetime.now(UTC),
        status="scheduled",
        summary="",
    )
    audit = await repo.create(audit)
    await repo.update_fields(audit.id, status="completed", summary="Done")
    fetched = await repo.get_by_id(audit.id)
    assert fetched.status == "completed"
    assert fetched.summary == "Done"


@pytest.mark.asyncio
async def test_repo_delete_removes_row() -> None:
    repo = _StubRepo()
    cert = SafetyCertification(
        cert_type="working_at_height",
        issue_date=date(2026, 1, 1),
        valid_until=date(2027, 1, 1),
        status="valid",
    )
    await repo.create(cert)
    await repo.delete(cert.id)
    assert await repo.get_by_id(cert.id) is None


# ── Permissions ──────────────────────────────────────────────────────────


def test_register_hse_advanced_permissions_registers_min_set() -> None:
    """Registering should populate ≥6 hse_advanced.* permissions."""
    register_hse_advanced_permissions()
    modules = permission_registry.list_modules()
    assert "hse_advanced" in modules
    perms = modules["hse_advanced"]
    assert len(perms) >= 6
    # Core permissions must be present.
    for required in (
        "hse_advanced.read",
        "hse_advanced.create",
        "hse_advanced.update",
        "hse_advanced.delete",
        "hse_advanced.approve_jsa",
        "hse_advanced.approve_permit",
    ):
        assert required in perms


def test_register_hse_advanced_permissions_roles() -> None:
    register_hse_advanced_permissions()
    # Manager role should have all hse_advanced permissions; Viewer only read.
    assert permission_registry.role_has_permission(Role.VIEWER, "hse_advanced.read")
    assert not permission_registry.role_has_permission(Role.VIEWER, "hse_advanced.create")
    assert permission_registry.role_has_permission(Role.MANAGER, "hse_advanced.delete")
    assert permission_registry.role_has_permission(Role.MANAGER, "hse_advanced.approve_jsa")


# ── PTW prerequisites matrix ─────────────────────────────────────────────


def test_ptw_required_prereqs_hot_work() -> None:
    from app.modules.hse_advanced.service import ptw_required_prerequisites

    required = ptw_required_prerequisites("hot_work")
    assert "prereq_jsa_approved" in required
    assert "prereq_fire_watch_assigned" in required
    assert "prereq_extinguisher_present" in required


def test_ptw_required_prereqs_confined_space() -> None:
    from app.modules.hse_advanced.service import ptw_required_prerequisites

    required = ptw_required_prerequisites("confined_space")
    assert "prereq_atmospheric_test_passed" in required
    assert "prereq_supervisor_present" in required


def test_ptw_required_prereqs_unknown_type_falls_back_to_jsa() -> None:
    from app.modules.hse_advanced.service import ptw_required_prerequisites

    required = ptw_required_prerequisites("plumbing_xyz")
    assert required == ("prereq_jsa_approved",)


def test_check_ptw_prerequisites_returns_missing() -> None:
    from types import SimpleNamespace

    from app.modules.hse_advanced.service import check_ptw_prerequisites

    permit = SimpleNamespace(
        permit_type="hot_work",
        prereq_jsa_approved=True,
        prereq_fire_watch_assigned=False,
        prereq_extinguisher_present=False,
    )
    met, missing = check_ptw_prerequisites(permit)
    assert "prereq_jsa_approved" in met
    assert "prereq_fire_watch_assigned" in missing
    assert "prereq_extinguisher_present" in missing


@pytest.mark.asyncio
async def test_activate_permit_blocks_when_prereqs_unmet() -> None:
    """Activating a hot-work permit without fire-watch should 409."""
    # Use the module-level _make_service via runtime import.
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from app.modules.hse_advanced.models import PermitToWork as _PTW

    # Re-instantiate the same lightweight service the existing tests use.
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    now = _dt.now(_UTC)
    permit = _PTW(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        permit_number="PTW-PREREQ-1",
        permit_type="hot_work",
        work_start=now,
        work_end=now + _td(hours=1),
        status="approved",
        description="",
        conditions="",
        closure_checklist_passed=False,
        closure_notes="",
        prereq_jsa_approved=False,
        prereq_fire_watch_assigned=False,
        prereq_extinguisher_present=False,
    )
    await svc.permit_repo.create(permit)
    with pytest.raises(HTTPException) as exc:
        await svc.activate_permit(permit.id)
    assert exc.value.status_code == 409
    assert "prereq" in exc.value.detail.lower()


# ── Incident escalation matrix ───────────────────────────────────────────


def test_incident_escalation_matrix_osha_fatality_8h() -> None:
    from app.modules.hse_advanced.service import incident_escalation_matrix

    m = incident_escalation_matrix("osha")
    assert m.regime == "osha"
    fat = next(e for e in m.entries if e.severity == "fatality")
    assert fat.notify_within_hours == 8
    assert "osha" in fat.notify_roles
    assert "1904.39" in (fat.regulation_ref or "")


def test_incident_escalation_matrix_hse_uk_immediate_for_fatality() -> None:
    from app.modules.hse_advanced.service import incident_escalation_matrix

    m = incident_escalation_matrix("hse_uk")
    fat = next(e for e in m.entries if e.severity == "fatality")
    assert fat.notify_within_hours == 0  # immediate by quickest means
    assert "RIDDOR" in (fat.regulation_ref or "")


def test_incident_escalation_matrix_unknown_regime_falls_back() -> None:
    from app.modules.hse_advanced.service import incident_escalation_matrix

    m = incident_escalation_matrix("not_a_regime")
    assert m.regime == "iso45001"
    assert len(m.entries) > 0


# ── CAPA 5-Whys ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_capa_five_whys_records_chain() -> None:
    from app.modules.hse_advanced.models import CorrectiveAction
    from app.modules.hse_advanced.schemas import (
        CAPAFiveWhysPayload,
        FiveWhyStep,
    )
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        source_ref=None,
        title="Rebar cover non-conformance",
        description="Cover < 25mm in slab",
        target_date=date.today() + timedelta(days=14),
        status="open",
        verification_notes="",
        five_whys=None,
    )
    await svc.capa_repo.create(capa)
    payload = CAPAFiveWhysPayload(
        steps=[
            FiveWhyStep(why="Why was cover low?", answer="Spacers wrong size"),
            FiveWhyStep(why="Why wrong spacers?", answer="Wrong batch from supplier"),
            FiveWhyStep(why="Why wrong batch?", answer="No incoming inspection"),
            FiveWhyStep(why="Why no inspection?", answer="Procedure not enforced"),
            FiveWhyStep(why="Why not enforced?", answer="Training gap on QA team"),
        ],
        root_cause_category="method",
    )
    obj = await svc.set_capa_five_whys(capa.id, payload)
    assert len(obj.five_whys or []) == 5
    assert obj.root_cause_category == "method"


@pytest.mark.asyncio
async def test_set_capa_five_whys_rejects_too_few_steps() -> None:
    from app.modules.hse_advanced.models import CorrectiveAction
    from app.modules.hse_advanced.schemas import (
        CAPAFiveWhysPayload,
        FiveWhyStep,
    )
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="X",
        description="x",
        target_date=date.today() + timedelta(days=7),
        status="open",
        verification_notes="",
    )
    await svc.capa_repo.create(capa)
    payload = CAPAFiveWhysPayload(
        steps=[FiveWhyStep(why="Why?", answer="Because")],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.set_capa_five_whys(capa.id, payload)
    assert exc.value.status_code == 422


# ── CAPA effectiveness verification ──────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_capa_effectiveness_marks_verified() -> None:
    from app.modules.hse_advanced.models import CorrectiveAction
    from app.modules.hse_advanced.schemas import CAPAEffectivenessPayload
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="X",
        description="x",
        target_date=date.today() + timedelta(days=7),
        status="completed",
        verification_notes="closed",
    )
    await svc.capa_repo.create(capa)
    payload = CAPAEffectivenessPayload(effective=True, notes="Holding 90 days")
    obj = await svc.verify_capa_effectiveness(capa.id, payload)
    assert obj.effectiveness_verified_at is not None


@pytest.mark.asyncio
async def test_verify_capa_effectiveness_reopens_when_ineffective() -> None:
    from app.modules.hse_advanced.models import CorrectiveAction
    from app.modules.hse_advanced.schemas import CAPAEffectivenessPayload
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="X",
        description="x",
        target_date=date.today() + timedelta(days=7),
        status="completed",
        verification_notes="",
    )
    await svc.capa_repo.create(capa)
    payload = CAPAEffectivenessPayload(effective=False, notes="Recurred")
    obj = await svc.verify_capa_effectiveness(capa.id, payload)
    assert obj.status == "in_progress"
    assert "failed" in (obj.verification_notes or "").lower()


@pytest.mark.asyncio
async def test_verify_capa_effectiveness_requires_completed() -> None:
    from app.modules.hse_advanced.models import CorrectiveAction
    from app.modules.hse_advanced.schemas import CAPAEffectivenessPayload
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        source_type="audit",
        title="X",
        description="x",
        target_date=date.today() + timedelta(days=7),
        status="open",
        verification_notes="",
    )
    await svc.capa_repo.create(capa)
    with pytest.raises(HTTPException) as exc:
        await svc.verify_capa_effectiveness(
            capa.id,
            CAPAEffectivenessPayload(effective=True),
        )
    assert exc.value.status_code == 409


# ── JSA template library ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_jsa_template_persists_hazards() -> None:
    from app.modules.hse_advanced.schemas import JSATemplateCreate
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    tpl = await svc.create_jsa_template(
        JSATemplateCreate(
            trade="concrete",
            name="Slab on grade pour",
            task_description="Pour 30m³ slab",
            hazards=[
                {"step": "Setup", "hazard": "Slip", "severity": 2, "likelihood": 3, "controls": "Mark wet areas"},
                {"step": "Pour", "hazard": "Splash", "severity": 3, "likelihood": 2, "controls": "PPE goggles"},
            ],
            required_ppe=["hard_hat", "safety_boots", "gloves"],
            region="DE",
        ),
        user_id="u-1",
    )
    assert tpl.trade == "concrete"
    assert len(tpl.hazards_json) == 2
    assert "hard_hat" in tpl.required_ppe_json
    assert tpl.region == "DE"


@pytest.mark.asyncio
async def test_clone_jsa_template_creates_project_jsa() -> None:
    from app.modules.hse_advanced.schemas import (
        JSATemplateCloneRequest,
        JSATemplateCreate,
    )
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    tpl = await svc.create_jsa_template(
        JSATemplateCreate(
            trade="electrical",
            name="Panel work",
            task_description="LOTO before opening panel",
            hazards=[
                {"step": "Open", "hazard": "Shock", "severity": 5, "likelihood": 2, "controls": "LOTO"},
            ],
            required_ppe=["arc_flash_suit"],
        ),
    )
    new_project = uuid.uuid4()
    jsa = await svc.clone_jsa_template_to_project(
        tpl.id,
        JSATemplateCloneRequest(
            project_id=new_project,
            work_date="2026-05-15",
            location="Panel A",
        ),
        user_id="u-2",
    )
    assert jsa.project_id == new_project
    assert jsa.work_date == "2026-05-15"
    assert len(jsa.hazards) == 1
    # Risk score computed from cloned hazards: 5×2=10
    assert jsa.risk_score == 10
    assert jsa.status == "draft"


@pytest.mark.asyncio
async def test_clone_inactive_jsa_template_rejected() -> None:
    from app.modules.hse_advanced.schemas import (
        JSATemplateCloneRequest,
        JSATemplateCreate,
    )
    from tests.unit.test_hse_advanced import _make_service as _ms

    svc = _ms()
    tpl = await svc.create_jsa_template(
        JSATemplateCreate(
            trade="welding",
            name="Weld test",
            task_description="x",
            hazards=[],
            required_ppe=[],
            is_active=False,
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.clone_jsa_template_to_project(
            tpl.id,
            JSATemplateCloneRequest(
                project_id=uuid.uuid4(),
                work_date="2026-05-15",
            ),
        )
    assert exc.value.status_code == 400


# ── Wave M4: cross-module wiring ───────────────────────────────────────


@pytest.mark.asyncio
async def test_safety_incident_subscriber_fans_out() -> None:
    """``safety.incident.created`` → risk_register_update + kpi_recompute."""
    import asyncio

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.hse_advanced.events import _on_safety_incident_created

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    pid = str(uuid.uuid4())
    iid = str(uuid.uuid4())
    event = Event(
        name="safety.incident.created",
        data={
            "project_id": pid,
            "incident_id": iid,
            "incident_number": "INC-001",
            "severity": "high",
        },
        source_module="safety",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_safety_incident_created(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    names = [n for n, _ in captured]
    assert "contracts.risk_register_update" in names
    assert "bi_dashboards.kpi_recompute" in names
    risk = next(d for n, d in captured if n == "contracts.risk_register_update")
    assert risk["project_id"] == pid
    assert risk["incident_id"] == iid
    assert risk["impact"] == "severe"  # high severity → severe impact
    kpi = next(d for n, d in captured if n == "bi_dashboards.kpi_recompute")
    assert "safety_trir" in kpi["kpi_codes"]


@pytest.mark.asyncio
async def test_qms_ncr_safety_check_filters_non_safety() -> None:
    """Non-safety NCR (no safety keyword, low severity) → no fanout."""
    import asyncio

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.hse_advanced.events import _on_qms_ncr_safety_check

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    event = Event(
        name="qms.ncr.raised",
        data={
            "ncr_id": str(uuid.uuid4()),
            "project_id": str(uuid.uuid4()),
            "severity": "minor",
            "title": "Painting touch-up required",
        },
        source_module="qms",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_qms_ncr_safety_check(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    assert captured == []


@pytest.mark.asyncio
async def test_qms_ncr_safety_check_fans_out_on_critical() -> None:
    """Critical NCR → publishes hse_advanced.if_safety_related."""
    import asyncio

    from app.core import events as _ev_module
    from app.core.events import Event
    from app.modules.hse_advanced.events import _on_qms_ncr_safety_check

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    event = Event(
        name="qms.ncr.raised",
        data={
            "ncr_id": str(uuid.uuid4()),
            "project_id": str(uuid.uuid4()),
            "severity": "critical",
            "title": "Structural deficiency in column C-14",
        },
        source_module="qms",
    )
    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_qms_ncr_safety_check(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]
    names = [n for n, _ in captured]
    assert "hse_advanced.if_safety_related" in names


@pytest.mark.asyncio
async def test_hse_register_subscribers_idempotent() -> None:
    """register_subscribers is safe to call repeatedly."""
    from app.modules.hse_advanced.events import register_subscribers

    register_subscribers()
    register_subscribers()
