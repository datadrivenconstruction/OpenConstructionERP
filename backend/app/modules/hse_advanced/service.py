"""‌⁠‍HSE Advanced service — pure helpers + workflows for JSA / PTW / audits / CAPA / KPI."""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.hse_advanced.models import (
    CorrectiveAction,
    HSEIncidentInvestigation,
    JobSafetyAnalysis,
    JSATemplate,
    PermitToWork,
    PPEIssue,
    SafetyAudit,
    SafetyAuditFinding,
    SafetyCertification,
    ToolboxAttendance,
    ToolboxTalk,
    ToolboxTopic,
)
from app.modules.hse_advanced.repository import (
    AuditFindingRepository,
    AuditRepository,
    CAPARepository,
    CertificationRepository,
    InvestigationRepository,
    JSARepository,
    JSATemplateRepository,
    PermitRepository,
    PPEIssueRepository,
    ToolboxAttendanceRepository,
    ToolboxTalkRepository,
    ToolboxTopicRepository,
)
from app.modules.hse_advanced.schemas import (
    AuditCreate,
    AuditFindingCreate,
    AuditUpdate,
    CAPACreate,
    CAPAEffectivenessPayload,
    CAPAFiveWhysPayload,
    CAPAUpdate,
    CertificationCreate,
    CertificationUpdate,
    IncidentEscalationEntry,
    IncidentEscalationMatrix,
    InvestigationCreate,
    InvestigationUpdate,
    JSACreate,
    JSATemplateCloneRequest,
    JSATemplateCreate,
    JSATemplateUpdate,
    JSAUpdate,
    PermitCreate,
    PermitPrerequisitesPayload,
    PermitPrerequisiteStatus,
    PermitUpdate,
    PPEIssueCreate,
    PPEIssueUpdate,
    ToolboxAttendanceEntry,
    ToolboxTalkCreate,
    ToolboxTalkUpdate,
    ToolboxTopicCreate,
    ToolboxTopicUpdate,
)
from app.modules.safety.models import HSECorrectiveAction, SafetyIncident

logger = logging.getLogger(__name__)


# ── Pure helpers ─────────────────────────────────────────────────────────────


# Permit-to-Work prerequisite matrix — keyed by permit_type.
# Each value lists prerequisite flag names that MUST be True on the
# PermitToWork row before transitioning to 'active'.
# Sourced from OSHA 1926 (US), HSG250 (UK), DGUV (DE), and SGS hot-work
# best practice.
_PTW_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "hot_work": (
        "prereq_jsa_approved",
        "prereq_fire_watch_assigned",
        "prereq_extinguisher_present",
    ),
    "confined_space": (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
        "prereq_atmospheric_test_passed",
    ),
    "work_at_height": (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
    ),
    "excavation": (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
    ),
    "electrical": (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
    ),
    "lifting": (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
    ),
    "lockout_tagout": (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
    ),
    "other": ("prereq_jsa_approved",),
}


def ptw_required_prerequisites(permit_type: str) -> tuple[str, ...]:
    """‌⁠‍Pure: return the required prerequisite flag names for a permit type."""
    return _PTW_PREREQUISITES.get(permit_type, ("prereq_jsa_approved",))


def check_ptw_prerequisites(permit: Any) -> tuple[list[str], list[str]]:
    """‌⁠‍Pure: return (met, missing) prerequisite lists for a permit.

    A flag is "met" when its boolean attribute on ``permit`` is truthy.
    Anything not in the requirement list is ignored.
    """
    required = ptw_required_prerequisites(getattr(permit, "permit_type", ""))
    met: list[str] = []
    missing: list[str] = []
    for flag in required:
        if bool(getattr(permit, flag, False)):
            met.append(flag)
        else:
            missing.append(flag)
    return met, missing


# Incident escalation matrix — severity → required role notification + SLA.
# Hours are the maximum time-to-notification per regulation.
# OSHA 29 CFR 1904.39: fatality 8h, in-patient hospitalisation/amputation/eye 24h.
# UK HSE RIDDOR: fatality / major immediate, 7-day-injury within 15 days.
# DGUV §193: meldepflichtig within 3 days (Tagebuch + Unfallanzeige).
_ESCALATION_MATRICES: dict[str, list[dict[str, Any]]] = {
    "osha": [
        {
            "severity": "fatality",
            "notify_roles": ["hse_manager", "site_director", "osha"],
            "notify_within_hours": 8,
            "regulation_ref": "29 CFR 1904.39(a)(1)",
        },
        {
            "severity": "hospitalization",
            "notify_roles": ["hse_manager", "site_director", "osha"],
            "notify_within_hours": 24,
            "regulation_ref": "29 CFR 1904.39(a)(2)",
        },
        {
            "severity": "amputation_eye_loss",
            "notify_roles": ["hse_manager", "site_director", "osha"],
            "notify_within_hours": 24,
            "regulation_ref": "29 CFR 1904.39(a)(2)",
        },
        {
            "severity": "lost_time",
            "notify_roles": ["hse_manager", "supervisor"],
            "notify_within_hours": 24,
            "regulation_ref": "29 CFR 1904 records",
        },
        {
            "severity": "near_miss",
            "notify_roles": ["hse_manager"],
            "notify_within_hours": 72,
            "regulation_ref": "ANSI Z10",
        },
    ],
    "hse_uk": [
        {
            "severity": "fatality",
            "notify_roles": ["hse_manager", "site_director", "hse_executive"],
            "notify_within_hours": 0,  # immediate by quickest means
            "regulation_ref": "RIDDOR 2013 reg.4",
        },
        {
            "severity": "specified_injury",
            "notify_roles": ["hse_manager", "hse_executive"],
            "notify_within_hours": 0,
            "regulation_ref": "RIDDOR 2013 reg.4(2)",
        },
        {
            "severity": "over_7_day_injury",
            "notify_roles": ["hse_manager", "hse_executive"],
            "notify_within_hours": 24 * 15,
            "regulation_ref": "RIDDOR 2013 reg.4(3)",
        },
        {
            "severity": "near_miss",
            "notify_roles": ["hse_manager"],
            "notify_within_hours": 72,
            "regulation_ref": "HSG65",
        },
    ],
    "dguv": [
        {
            "severity": "fatality",
            "notify_roles": ["hse_manager", "site_director", "berufsgenossenschaft"],
            "notify_within_hours": 24,
            "regulation_ref": "DGUV V1 §24",
        },
        {
            "severity": "reportable_injury",
            "notify_roles": ["hse_manager", "berufsgenossenschaft"],
            "notify_within_hours": 72,
            "regulation_ref": "SGB VII §193",
        },
        {
            "severity": "near_miss",
            "notify_roles": ["hse_manager"],
            "notify_within_hours": 168,
            "regulation_ref": "DGUV V2",
        },
    ],
    "iso45001": [
        {
            "severity": "fatality",
            "notify_roles": ["hse_manager", "site_director", "ceo"],
            "notify_within_hours": 8,
            "regulation_ref": "ISO 45001:2018 §10.2",
        },
        {
            "severity": "major_injury",
            "notify_roles": ["hse_manager", "site_director"],
            "notify_within_hours": 24,
            "regulation_ref": "ISO 45001:2018 §10.2",
        },
        {
            "severity": "minor_injury",
            "notify_roles": ["hse_manager"],
            "notify_within_hours": 48,
            "regulation_ref": "ISO 45001:2018 §10.2",
        },
        {
            "severity": "near_miss",
            "notify_roles": ["hse_manager"],
            "notify_within_hours": 72,
            "regulation_ref": "ISO 45001:2018 §10.2",
        },
    ],
}


def incident_escalation_matrix(regime: str) -> IncidentEscalationMatrix:
    """Return the regulatory escalation matrix for a regime.

    Args:
        regime: One of ``osha`` / ``hse_uk`` / ``dguv`` / ``iso45001``.
            Unknown regimes fall back to ``iso45001``.
    """
    rows = _ESCALATION_MATRICES.get(regime) or _ESCALATION_MATRICES["iso45001"]
    return IncidentEscalationMatrix(
        regime=regime if regime in _ESCALATION_MATRICES else "iso45001",
        entries=[IncidentEscalationEntry(**r) for r in rows],
    )


def compute_risk_score(severity: int, likelihood: int) -> int:
    """Pure risk score on a 1-25 grid (severity × likelihood)."""
    severity = max(1, min(5, int(severity)))
    likelihood = max(1, min(5, int(likelihood)))
    return severity * likelihood


def compute_risk_tier(risk_score: int) -> str:
    """Derive risk tier from risk_score (low/medium/high/critical)."""
    if risk_score >= 16:
        return "critical"
    if risk_score >= 11:
        return "high"
    if risk_score >= 6:
        return "medium"
    return "low"


def compute_jsa_risk(hazards: list[dict[str, Any]] | None) -> int:
    """Pure: max-of-per-hazard score within a JSA's hazard list."""
    if not hazards:
        return 0
    best = 0
    for h in hazards:
        try:
            s = int(h.get("severity", 1) or 1)
            l = int(h.get("likelihood", 1) or 1)
        except (TypeError, ValueError):
            continue
        score = compute_risk_score(s, l)
        if score > best:
            best = score
    return best


def is_permit_active(permit: Any, now: datetime | None = None) -> bool:
    """Pure: permit is `active` AND now ∈ [work_start, work_end]."""
    if permit is None:
        return False
    if getattr(permit, "status", None) != "active":
        return False
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    ws = getattr(permit, "work_start", None)
    we = getattr(permit, "work_end", None)
    if ws is None or we is None:
        return False
    if ws.tzinfo is None:
        ws = ws.replace(tzinfo=UTC)
    if we.tzinfo is None:
        we = we.replace(tzinfo=UTC)
    return ws <= now <= we


def compute_trir(recordable_count: int, hours_worked: Decimal | float | int) -> Decimal:
    """Pure: TRIR = recordable × 200000 / hours_worked. Returns 0 on zero hours."""
    hw = Decimal(str(hours_worked)) if hours_worked is not None else Decimal("0")
    if hw <= 0:
        return Decimal("0")
    return (Decimal(recordable_count) * Decimal("200000") / hw).quantize(Decimal("0.0001"))


def compute_ltifr(lti_count: int, hours_worked: Decimal | float | int) -> Decimal:
    """Pure: LTIFR = LTI × 1_000_000 / hours_worked. Returns 0 on zero hours."""
    hw = Decimal(str(hours_worked)) if hours_worked is not None else Decimal("0")
    if hw <= 0:
        return Decimal("0")
    return (Decimal(lti_count) * Decimal("1000000") / hw).quantize(Decimal("0.0001"))


def days_without_lti(incident_dates: list[date | str], today: date | None = None) -> int:
    """Pure: days since the most recent LTI incident. None-yet => some sentinel.

    Returns 0 if today equals the most recent incident date, or a large
    integer if no incidents are provided.
    """
    if today is None:
        today = date.today()
    if not incident_dates:
        return 9999  # explicit "never had an LTI" sentinel
    parsed: list[date] = []
    for d in incident_dates:
        if isinstance(d, date):
            parsed.append(d)
        elif isinstance(d, str):
            try:
                parsed.append(date.fromisoformat(d[:10]))
            except ValueError:
                continue
    if not parsed:
        return 9999
    latest = max(parsed)
    delta = (today - latest).days
    return max(0, delta)


# Severity weighting used by compute_audit_score.
_FINDING_WEIGHTS = {"low": 1, "med": 2, "high": 4, "critical": 8}


def compute_audit_score(findings: list[Any]) -> tuple[Decimal, Decimal, float]:
    """Pure: compute (score, max_score, percentage) over an audit's findings.

    Each finding contributes its severity-weight; a `is_passed=True` finding
    contributes to score, all findings contribute to max_score.
    """
    score = Decimal("0")
    max_score = Decimal("0")
    for f in findings:
        sev = getattr(f, "severity", None)
        if sev is None and isinstance(f, dict):
            sev = f.get("severity")
        weight = Decimal(_FINDING_WEIGHTS.get(sev or "low", 1))

        passed = getattr(f, "is_passed", None)
        if passed is None and isinstance(f, dict):
            passed = f.get("is_passed", True)

        max_score += weight
        if passed:
            score += weight

    if max_score <= 0:
        return Decimal("0"), Decimal("0"), 0.0
    percentage = float((score / max_score) * Decimal("100"))
    return score, max_score, round(percentage, 2)


def is_certification_valid(cert: Any, today: date | None = None) -> bool:
    """Pure: valid iff status='valid' AND today <= valid_until."""
    if cert is None:
        return False
    if getattr(cert, "status", None) != "valid":
        return False
    if today is None:
        today = date.today()
    vu = getattr(cert, "valid_until", None)
    if vu is None:
        return False
    return today <= vu


def is_user_blocked_for_work(
    user_id: uuid.UUID | str | None,
    required_cert_types: list[str],
    certifications: list[Any],
    today: date | None = None,
) -> tuple[bool, list[str]]:
    """Pure: returns (blocked, missing_cert_types) for a worker.

    A user is blocked when any required cert type is missing or expired.
    """
    if today is None:
        today = date.today()
    if not required_cert_types:
        return False, []

    held: dict[str, Any] = {}
    for c in certifications:
        if getattr(c, "owner_user_id", None) != user_id:
            continue
        ct = getattr(c, "cert_type", None)
        if ct:
            # keep the latest valid_until per type
            existing = held.get(ct)
            if existing is None or getattr(c, "valid_until", date.min) > getattr(existing, "valid_until", date.min):
                held[ct] = c

    missing: list[str] = []
    for req in required_cert_types:
        c = held.get(req)
        if c is None or not is_certification_valid(c, today=today):
            missing.append(req)
    return (len(missing) > 0), missing


def allowed_jsa_transitions(current: str) -> list[str]:
    """Pure JSA state machine."""
    mapping = {
        "draft": ["under_review", "archived"],
        "under_review": ["approved", "draft", "archived"],
        "approved": ["active", "archived"],
        "active": ["archived"],
        "archived": [],
    }
    return mapping.get(current, [])


def allowed_permit_transitions(current: str) -> list[str]:
    """Pure PTW state machine."""
    mapping = {
        "requested": ["approved", "cancelled"],
        "approved": ["active", "cancelled"],
        "active": ["suspended", "closed", "cancelled"],
        "suspended": ["active", "closed", "cancelled"],
        "closed": [],
        "cancelled": [],
    }
    return mapping.get(current, [])


def allowed_audit_transitions(current: str) -> list[str]:
    """Pure SafetyAudit state machine."""
    mapping = {
        "scheduled": ["in_progress", "cancelled"],
        "in_progress": ["completed", "cancelled"],
        "completed": [],
        "cancelled": [],
    }
    return mapping.get(current, [])


def allowed_capa_transitions(current: str) -> list[str]:
    """Pure CAPA state machine."""
    mapping = {
        "open": ["in_progress", "completed", "overdue", "cancelled"],
        "in_progress": ["completed", "overdue", "cancelled"],
        "overdue": ["in_progress", "completed", "cancelled"],
        "completed": [],
        "cancelled": [],
    }
    return mapping.get(current, [])


def allowed_corrective_action_transitions(current: str) -> list[str]:
    """‌⁠‍Pure slim CorrectiveAction FSM (incident-scoped).

    Strict linear lifecycle modelled on Procore Quality & Safety + Sphera
    SafetyStratus: ``pending → in_progress → verified → closed``. Any other
    transition (e.g. ``pending → verified`` or ``closed → in_progress``)
    is rejected by :meth:`HSEAdvancedService.transition_corrective_action`.
    """
    mapping = {
        "pending": ["in_progress"],
        "in_progress": ["verified"],
        "verified": ["closed"],
        "closed": [],
    }
    return mapping.get(current, [])


def allowed_certification_transitions(current: str) -> list[str]:
    """Pure SafetyCertification state machine."""
    mapping = {
        "valid": ["expired", "revoked"],
        "expired": ["valid"],
        "revoked": [],
    }
    return mapping.get(current, [])


# ── Async workflow service ─────────────────────────────────────────────────


def _safe_publish(name: str, data: dict, source_module: str = "hse_advanced") -> None:
    """Fire-and-forget publish — silenced on bus errors."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        logger.debug("Event publish skipped: %s", name)


async def _safe_audit(
    session: AsyncSession,
    *,
    actor_id: str | uuid.UUID | None,
    entity_type: str,
    entity_id: str | uuid.UUID | None,
    action: str,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """‌⁠‍Best-effort write to ``activity_log`` for HSE audit-trail coverage.

    Round-3 Wave F flagged 21 HSE PATCH/DELETE / FSM-transition endpoints
    as silent on the audit trail. We funnel every state change and
    destructive op through this helper so a compliance auditor can answer
    "who closed CAPA #X on Y date" without reading service logs. Errors
    are swallowed: a flaky audit row must never block a legitimate write.
    """
    try:
        from app.core.audit_log import log_activity

        await log_activity(
            session,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            reason=None,
            metadata=metadata,
        )
    except Exception:
        logger.debug("hse_advanced audit_log skipped: %s %s", entity_type, action)


class HSEAdvancedService:
    """Business logic for the HSE Advanced module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.investigation_repo = InvestigationRepository(session)
        self.jsa_repo = JSARepository(session)
        self.permit_repo = PermitRepository(session)
        self.talk_repo = ToolboxTalkRepository(session)
        self.attendance_repo = ToolboxAttendanceRepository(session)
        self.topic_repo = ToolboxTopicRepository(session)
        self.ppe_repo = PPEIssueRepository(session)
        self.audit_repo = AuditRepository(session)
        self.finding_repo = AuditFindingRepository(session)
        self.capa_repo = CAPARepository(session)
        self.cert_repo = CertificationRepository(session)
        self.jsa_template_repo = JSATemplateRepository(session)

    # ── Investigation ─────────────────────────────────────────────────────

    async def create_investigation(
        self, data: InvestigationCreate, user_id: str | None = None
    ) -> HSEIncidentInvestigation:
        obj = HSEIncidentInvestigation(
            incident_ref=data.incident_ref,
            investigation_lead=data.investigation_lead,
            started_at=data.started_at,
            method=data.method,
            findings=data.findings,
            recommendations=data.recommendations,
            status=data.status,
            report_url=data.report_url,
            created_by=user_id,
        )
        obj = await self.investigation_repo.create(obj)
        return obj

    async def get_investigation(self, item_id: uuid.UUID) -> HSEIncidentInvestigation:
        obj = await self.investigation_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "Investigation not found")
        return obj

    async def update_investigation(self, item_id: uuid.UUID, data: InvestigationUpdate) -> HSEIncidentInvestigation:
        obj = await self.get_investigation(item_id)
        fields = data.model_dump(exclude_unset=True)
        # RIDDOR (UK) / OSHA 1904.33 (US) require the formal investigation
        # record to be immutable once closed — re-editing findings or root
        # cause after completion would falsify the regulatory submission.
        # Pure status transitions go via dedicated workflow methods, so a
        # content-only update on a terminal investigation is rejected here.
        # ``status`` may still be edited so a mis-closed probe can be
        # re-opened explicitly (which is itself audit-logged downstream).
        content_keys = fields.keys() - {"status"}
        if content_keys and obj.status in ("completed", "abandoned"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot edit a {obj.status} investigation — "
                "regulatory records (RIDDOR / OSHA) are immutable. "
                "Re-open it explicitly to amend.",
            )
        if fields:
            await self.investigation_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
        return obj

    async def complete_investigation(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> HSEIncidentInvestigation:
        obj = await self.get_investigation(item_id)
        # `completed` and `abandoned` are terminal — re-completing would
        # silently reset `completed_at` and resurrect an abandoned probe.
        if obj.status != "in_progress":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot complete an investigation in status '{obj.status}'",
            )
        prior = obj.status
        await self.investigation_repo.update_fields(item_id, status="completed", completed_at=datetime.now(UTC))
        await self.session.refresh(obj)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_investigation",
            entity_id=str(item_id),
            action="status_changed",
            from_status=prior,
            to_status="completed",
            metadata={"incident_ref": str(obj.incident_ref)},
        )
        return obj

    async def abandon_investigation(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> HSEIncidentInvestigation:
        obj = await self.get_investigation(item_id)
        # A completed investigation is a closed record; an already-abandoned
        # one is terminal. Only an in-progress probe may be abandoned, and
        # we stamp `completed_at` so the closure time is auditable.
        if obj.status != "in_progress":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot abandon an investigation in status '{obj.status}'",
            )
        prior = obj.status
        await self.investigation_repo.update_fields(item_id, status="abandoned", completed_at=datetime.now(UTC))
        await self.session.refresh(obj)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_investigation",
            entity_id=str(item_id),
            action="status_changed",
            from_status=prior,
            to_status="abandoned",
            metadata={"incident_ref": str(obj.incident_ref)},
        )
        return obj

    # ── JSA ───────────────────────────────────────────────────────────────

    async def create_jsa(self, data: JSACreate, user_id: str | None = None) -> JobSafetyAnalysis:
        hazards = [h.model_dump() for h in data.hazards]
        risk = compute_jsa_risk(hazards)
        obj = JobSafetyAnalysis(
            project_id=data.project_id,
            task_description=data.task_description,
            location=data.location,
            work_date=data.work_date,
            prepared_by=data.prepared_by,
            status=data.status,
            hazards=hazards,
            required_ppe=list(data.required_ppe),
            risk_score=risk,
            created_by=user_id,
        )
        obj = await self.jsa_repo.create(obj)
        return obj

    async def get_jsa(self, item_id: uuid.UUID) -> JobSafetyAnalysis:
        obj = await self.jsa_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "JSA not found")
        return obj

    async def update_jsa(
        self,
        item_id: uuid.UUID,
        data: JSAUpdate,
        user_id: str | None = None,
    ) -> JobSafetyAnalysis:
        obj = await self.get_jsa(item_id)
        fields = data.model_dump(exclude_unset=True)
        # A JSA's hazard analysis / work_date is the artifact that was
        # signed off. Editing it after approval would silently invalidate
        # the approval (approved_by / approved_at would still point at the
        # old content). Only draft / under_review JSAs are content-editable;
        # a pure status transition uses the dedicated workflow methods.
        content_keys = fields.keys() - {"status"}
        if content_keys and obj.status not in ("draft", "under_review"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot edit a JSA in status '{obj.status}' — revert it to draft before changing content",
            )
        if "hazards" in fields and fields["hazards"] is not None:
            fields["hazards"] = [h.model_dump() if hasattr(h, "model_dump") else h for h in fields["hazards"]]
            fields["risk_score"] = compute_jsa_risk(fields["hazards"])
        if fields:
            await self.jsa_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
            await _safe_audit(
                self.session,
                actor_id=user_id,
                entity_type="hse_jsa",
                entity_id=str(item_id),
                action="updated",
                metadata={
                    "project_id": str(obj.project_id),
                    "fields": sorted(fields.keys()),
                },
            )
        return obj

    async def delete_jsa(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> None:
        obj = await self.get_jsa(item_id)
        snapshot = {
            "project_id": str(obj.project_id),
            "status": obj.status,
            "task_description": (obj.task_description or "")[:200],
        }
        await self.jsa_repo.delete(item_id)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_jsa",
            entity_id=str(item_id),
            action="deleted",
            metadata=snapshot,
        )

    async def _transition_jsa(self, item_id: uuid.UUID, target: str) -> JobSafetyAnalysis:
        obj = await self.get_jsa(item_id)
        if target not in allowed_jsa_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid JSA transition {obj.status} → {target}",
            )
        await self.jsa_repo.update_fields(item_id, status=target)
        await self.session.refresh(obj)
        return obj

    async def submit_jsa(self, item_id: uuid.UUID) -> JobSafetyAnalysis:
        obj = await self._transition_jsa(item_id, "under_review")
        _safe_publish(
            "hse.jsa.submitted",
            {
                "jsa_id": str(item_id),
                "project_id": str(obj.project_id),
                "risk_score": obj.risk_score,
            },
        )
        return obj

    async def approve_jsa(self, item_id: uuid.UUID, approver_id: uuid.UUID | None = None) -> JobSafetyAnalysis:
        obj = await self.get_jsa(item_id)
        if "approved" not in allowed_jsa_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid JSA transition {obj.status} → approved",
            )
        await self.jsa_repo.update_fields(
            item_id,
            status="approved",
            approved_by=approver_id,
            approved_at=datetime.now(UTC),
        )
        await self.session.refresh(obj)
        _safe_publish(
            "hse.jsa.approved",
            {
                "jsa_id": str(item_id),
                "project_id": str(obj.project_id),
                "approver_id": str(approver_id) if approver_id else None,
            },
        )
        return obj

    async def activate_jsa(self, item_id: uuid.UUID) -> JobSafetyAnalysis:
        return await self._transition_jsa(item_id, "active")

    async def archive_jsa(self, item_id: uuid.UUID) -> JobSafetyAnalysis:
        return await self._transition_jsa(item_id, "archived")

    # ── PTW ──────────────────────────────────────────────────────────────

    async def request_permit(self, data: PermitCreate, user_id: str | None = None) -> PermitToWork:
        if data.work_end <= data.work_start:
            raise HTTPException(422, "work_end must be after work_start")
        obj = PermitToWork(
            project_id=data.project_id,
            permit_number=data.permit_number,
            permit_type=data.permit_type,
            description=data.description,
            location=data.location,
            work_start=data.work_start,
            work_end=data.work_end,
            applicant_id=data.applicant_id,
            supervisor_id=data.supervisor_id,
            jsa_id=data.jsa_id,
            status="requested",
            conditions=data.conditions,
            closure_checklist_passed=False,
            closure_notes="",
            created_by=user_id,
        )
        obj = await self.permit_repo.create(obj)
        _safe_publish(
            "hse.permit.requested",
            {
                "permit_id": str(obj.id),
                "permit_number": obj.permit_number,
                "permit_type": obj.permit_type,
                "project_id": str(obj.project_id),
            },
        )
        return obj

    async def get_permit(self, item_id: uuid.UUID) -> PermitToWork:
        obj = await self.permit_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "Permit not found")
        return obj

    async def update_permit(
        self,
        item_id: uuid.UUID,
        data: PermitUpdate,
        user_id: str | None = None,
    ) -> PermitToWork:
        obj = await self.get_permit(item_id)
        # Editing the scope / window of a live, closed or cancelled permit
        # would falsify the work-authorisation record. Mirror the
        # prerequisite-edit guard: only pre-active permits are editable.
        if obj.status not in ("requested", "approved", "suspended"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot edit a permit in status '{obj.status}'",
            )
        fields = data.model_dump(exclude_unset=True)
        # If a caller adjusts the window, keep the work_end > work_start
        # invariant that request_permit enforces at creation time.
        new_start = fields.get("work_start", obj.work_start)
        new_end = fields.get("work_end", obj.work_end)
        if new_start is not None and new_end is not None and new_end <= new_start:
            raise HTTPException(422, "work_end must be after work_start")
        if fields:
            await self.permit_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
            await _safe_audit(
                self.session,
                actor_id=user_id,
                entity_type="hse_permit",
                entity_id=str(item_id),
                action="updated",
                metadata={
                    "project_id": str(obj.project_id),
                    "permit_number": obj.permit_number,
                    "fields": sorted(fields.keys()),
                },
            )
        return obj

    async def delete_permit(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> None:
        obj = await self.get_permit(item_id)
        snapshot = {
            "project_id": str(obj.project_id),
            "permit_number": obj.permit_number,
            "status": obj.status,
        }
        await self.permit_repo.delete(item_id)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_permit",
            entity_id=str(item_id),
            action="deleted",
            metadata=snapshot,
        )

    async def approve_permit(
        self,
        item_id: uuid.UUID,
        approver_id: uuid.UUID | None = None,
        conditions: str = "",
    ) -> PermitToWork:
        obj = await self.get_permit(item_id)
        if "approved" not in allowed_permit_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid permit transition {obj.status} → approved",
            )
        fields: dict[str, Any] = {
            "status": "approved",
            "approved_by": approver_id,
            "approved_at": datetime.now(UTC),
        }
        if conditions:
            fields["conditions"] = conditions
        await self.permit_repo.update_fields(item_id, **fields)
        await self.session.refresh(obj)
        _safe_publish(
            "hse.permit.approved",
            {
                "permit_id": str(item_id),
                "permit_number": obj.permit_number,
                "project_id": str(obj.project_id),
            },
        )
        return obj

    async def activate_permit(self, item_id: uuid.UUID) -> PermitToWork:
        obj = await self.get_permit(item_id)
        if "active" not in allowed_permit_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid permit transition {obj.status} → active",
            )
        # Enforce prerequisite checklist per permit type.
        _met, missing = check_ptw_prerequisites(obj)
        if missing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cannot activate permit — unmet prerequisites: " + ", ".join(missing),
            )
        # If the permit references a JSA, ensure it is approved.
        if obj.jsa_id is not None:
            jsa = await self.jsa_repo.get_by_id(obj.jsa_id)
            if jsa is None or jsa.status not in ("approved", "active"):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Cannot activate permit — linked JSA must be approved",
                )
        await self.permit_repo.update_fields(item_id, status="active")
        await self.session.refresh(obj)
        _safe_publish(
            "hse.permit.activated",
            {
                "permit_id": str(item_id),
                "permit_number": obj.permit_number,
                "project_id": str(obj.project_id),
            },
        )
        return obj

    async def update_permit_prerequisites(
        self,
        item_id: uuid.UUID,
        data: PermitPrerequisitesPayload,
    ) -> PermitToWork:
        """Update one or more prerequisite flags on a permit."""
        obj = await self.get_permit(item_id)
        if obj.status not in ("requested", "approved", "suspended"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot update prereqs on a permit in status '{obj.status}'",
            )
        fields = data.model_dump(exclude_unset=True, exclude_none=True)
        if fields:
            await self.permit_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
        return obj

    def permit_prerequisite_status(
        self,
        permit: PermitToWork,
    ) -> PermitPrerequisiteStatus:
        """Build a human-readable summary of permit prerequisite state."""
        required = list(ptw_required_prerequisites(permit.permit_type))
        met, missing = check_ptw_prerequisites(permit)
        return PermitPrerequisiteStatus(
            permit_id=permit.id,
            permit_type=permit.permit_type,
            prereqs_required=required,
            prereqs_met=met,
            prereqs_missing=missing,
            ready_to_activate=len(missing) == 0,
        )

    async def suspend_permit(self, item_id: uuid.UUID) -> PermitToWork:
        obj = await self.get_permit(item_id)
        if "suspended" not in allowed_permit_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid permit transition {obj.status} → suspended",
            )
        await self.permit_repo.update_fields(item_id, status="suspended")
        await self.session.refresh(obj)
        return obj

    async def close_permit(
        self,
        item_id: uuid.UUID,
        closure_checklist_passed: bool,
        closure_notes: str = "",
    ) -> PermitToWork:
        obj = await self.get_permit(item_id)
        if "closed" not in allowed_permit_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid permit transition {obj.status} → closed",
            )
        if not closure_checklist_passed:
            raise HTTPException(
                422,
                "Cannot close permit: closure_checklist_passed must be True",
            )
        await self.permit_repo.update_fields(
            item_id,
            status="closed",
            closure_checklist_passed=True,
            closure_notes=closure_notes,
        )
        await self.session.refresh(obj)
        _safe_publish(
            "hse.permit.closed",
            {
                "permit_id": str(item_id),
                "permit_number": obj.permit_number,
                "project_id": str(obj.project_id),
            },
        )
        return obj

    async def cancel_permit(self, item_id: uuid.UUID) -> PermitToWork:
        obj = await self.get_permit(item_id)
        if "cancelled" not in allowed_permit_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid permit transition {obj.status} → cancelled",
            )
        await self.permit_repo.update_fields(item_id, status="cancelled")
        await self.session.refresh(obj)
        return obj

    # ── Toolbox ──────────────────────────────────────────────────────────

    async def record_toolbox_talk(
        self,
        data: ToolboxTalkCreate,
        user_id: str | None = None,
    ) -> ToolboxTalk:
        talk = ToolboxTalk(
            project_id=data.project_id,
            topic_code=data.topic_code,
            topic_title=data.topic_title,
            conducted_at=data.conducted_at,
            conducted_by=data.conducted_by,
            language=data.language,
            attendance_count=len(data.attendance),
            notes=data.notes,
            library_topic_ref=data.library_topic_ref,
            created_by=user_id,
        )
        talk = await self.talk_repo.create(talk)
        for att in data.attendance:
            row = ToolboxAttendance(
                toolbox_talk_id=talk.id,
                attendee_name=att.attendee_name,
                attendee_company=att.attendee_company,
                attendee_role=att.attendee_role,
                signature_ref=att.signature_ref,
                signed_at=att.signed_at,
                attendance_status=att.attendance_status,
            )
            await self.attendance_repo.create(row)
        return talk

    async def add_attendance(
        self,
        talk_id: uuid.UUID,
        entries: list[ToolboxAttendanceEntry],
    ) -> list[ToolboxAttendance]:
        talk = await self.talk_repo.get_by_id(talk_id)
        if talk is None:
            raise HTTPException(404, "Toolbox talk not found")
        added: list[ToolboxAttendance] = []
        for att in entries:
            row = ToolboxAttendance(
                toolbox_talk_id=talk_id,
                attendee_name=att.attendee_name,
                attendee_company=att.attendee_company,
                attendee_role=att.attendee_role,
                signature_ref=att.signature_ref,
                signed_at=att.signed_at,
                attendance_status=att.attendance_status,
            )
            added.append(await self.attendance_repo.create(row))
        await self.talk_repo.update_fields(talk_id, attendance_count=talk.attendance_count + len(added))
        return added

    async def get_toolbox_talk(self, item_id: uuid.UUID) -> ToolboxTalk:
        obj = await self.talk_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "Toolbox talk not found")
        return obj

    async def update_toolbox_talk(self, item_id: uuid.UUID, data: ToolboxTalkUpdate) -> ToolboxTalk:
        obj = await self.get_toolbox_talk(item_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.talk_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
        return obj

    # ── Toolbox topic catalogue ─────────────────────────────────────────

    async def create_topic(self, data: ToolboxTopicCreate) -> ToolboxTopic:
        # ``ToolboxTopic.code`` is globally unique. Reject a duplicate with a
        # clean 409 instead of letting the DB raise an uncaught IntegrityError
        # that surfaces to the client as an opaque 500.
        existing = await self.topic_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A toolbox topic with code '{data.code}' already exists",
            )
        obj = ToolboxTopic(**data.model_dump())
        return await self.topic_repo.create(obj)

    async def update_topic(self, item_id: uuid.UUID, data: ToolboxTopicUpdate) -> ToolboxTopic:
        obj = await self.topic_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "Toolbox topic not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.topic_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
        return obj

    # ── PPE ──────────────────────────────────────────────────────────────

    async def issue_ppe(self, data: PPEIssueCreate) -> PPEIssue:
        obj = PPEIssue(**data.model_dump())
        return await self.ppe_repo.create(obj)

    async def get_ppe_issue(self, item_id: uuid.UUID) -> PPEIssue:
        obj = await self.ppe_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "PPE issue not found")
        return obj

    async def update_ppe_issue(self, item_id: uuid.UUID, data: PPEIssueUpdate) -> PPEIssue:
        obj = await self.get_ppe_issue(item_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.ppe_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
        return obj

    async def return_ppe(self, item_id: uuid.UUID) -> PPEIssue:
        obj = await self.get_ppe_issue(item_id)
        await self.ppe_repo.update_fields(item_id, status="returned", returned_at=datetime.now(UTC))
        await self.session.refresh(obj)
        return obj

    # ── Audits ───────────────────────────────────────────────────────────

    async def create_audit(self, data: AuditCreate, user_id: str | None = None) -> SafetyAudit:
        obj = SafetyAudit(
            project_id=data.project_id,
            audit_type=data.audit_type,
            conducted_at=data.conducted_at,
            conducted_by=data.conducted_by,
            status=data.status,
            summary=data.summary,
            checklist_template_ref=data.checklist_template_ref,
            created_by=user_id,
        )
        return await self.audit_repo.create(obj)

    async def get_audit(self, item_id: uuid.UUID) -> SafetyAudit:
        obj = await self.audit_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "Audit not found")
        return obj

    async def update_audit(
        self,
        item_id: uuid.UUID,
        data: AuditUpdate,
        user_id: str | None = None,
    ) -> SafetyAudit:
        obj = await self.get_audit(item_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.audit_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
            await _safe_audit(
                self.session,
                actor_id=user_id,
                entity_type="hse_audit",
                entity_id=str(item_id),
                action="updated",
                metadata={
                    "project_id": str(obj.project_id),
                    "fields": sorted(fields.keys()),
                },
            )
        return obj

    async def delete_audit(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> None:
        obj = await self.get_audit(item_id)
        snapshot = {
            "project_id": str(obj.project_id),
            "audit_type": obj.audit_type,
            "status": obj.status,
        }
        await self.audit_repo.delete(item_id)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_audit",
            entity_id=str(item_id),
            action="deleted",
            metadata=snapshot,
        )

    async def conduct_audit(
        self,
        audit_id: uuid.UUID,
        findings_payload: list[AuditFindingCreate],
        user_id: str | None = None,
    ) -> SafetyAudit:
        """Record findings against an audit; create a CAPA for each failure."""
        audit = await self.get_audit(audit_id)
        for fp in findings_payload:
            finding = SafetyAuditFinding(
                audit_id=audit_id,
                item_description=fp.item_description,
                category=fp.category,
                severity=fp.severity,
                is_passed=fp.is_passed,
                evidence_url=fp.evidence_url,
            )
            finding = await self.finding_repo.create(finding)
            if not fp.is_passed:
                # Create a CAPA tied to this failure (14d default closure target)
                target_date = date.fromordinal(date.today().toordinal() + 14)
                capa = CorrectiveAction(
                    project_id=audit.project_id,
                    source_type="audit",
                    source_ref=audit_id,
                    title=f"Audit finding: {fp.item_description[:200]}",
                    description=fp.item_description,
                    target_date=target_date,
                    status="open",
                    created_by=user_id,
                )
                capa = await self.capa_repo.create(capa)
                await self.finding_repo.update_fields(finding.id, corrective_action_ref=capa.id)

        # Recompute audit score from all findings now persisted.
        findings = await self.finding_repo.list_for_audit(audit_id)
        score, max_score, _pct = compute_audit_score(findings)
        await self.audit_repo.update_fields(
            audit_id,
            score_total=score,
            max_score=max_score,
            status="in_progress" if audit.status == "scheduled" else audit.status,
        )
        await self.session.refresh(audit)
        return audit

    async def complete_audit(
        self,
        audit_id: uuid.UUID,
        user_id: str | None = None,
    ) -> SafetyAudit:
        audit = await self.get_audit(audit_id)
        if "completed" not in allowed_audit_transitions(audit.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid audit transition {audit.status} → completed",
            )
        prior = audit.status
        findings = await self.finding_repo.list_for_audit(audit_id)
        score, max_score, _pct = compute_audit_score(findings)
        await self.audit_repo.update_fields(
            audit_id,
            status="completed",
            score_total=score,
            max_score=max_score,
        )
        await self.session.refresh(audit)
        _safe_publish(
            "hse.audit.completed",
            {
                "audit_id": str(audit_id),
                "project_id": str(audit.project_id),
                "score_total": float(score),
                "max_score": float(max_score),
            },
        )
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_audit",
            entity_id=str(audit_id),
            action="status_changed",
            from_status=prior,
            to_status="completed",
            metadata={
                "project_id": str(audit.project_id),
                "score_total": float(score),
                "max_score": float(max_score),
            },
        )
        return audit

    # ── Audit Findings (CRUD basics) ────────────────────────────────────

    async def create_finding(self, audit_id: uuid.UUID, payload: AuditFindingCreate) -> SafetyAuditFinding:
        await self.get_audit(audit_id)
        obj = SafetyAuditFinding(
            audit_id=audit_id,
            item_description=payload.item_description,
            category=payload.category,
            severity=payload.severity,
            is_passed=payload.is_passed,
            evidence_url=payload.evidence_url,
        )
        return await self.finding_repo.create(obj)

    async def delete_finding(self, finding_id: uuid.UUID) -> None:
        await self.finding_repo.delete(finding_id)

    # ── CAPA ─────────────────────────────────────────────────────────────

    async def create_capa(self, data: CAPACreate, user_id: str | None = None) -> CorrectiveAction:
        obj = CorrectiveAction(
            project_id=data.project_id,
            source_type=data.source_type,
            source_ref=data.source_ref,
            title=data.title,
            description=data.description,
            owner_user_id=data.owner_user_id,
            target_date=data.target_date,
            status=data.status,
            root_cause_category=data.root_cause_category,
            created_by=user_id,
        )
        return await self.capa_repo.create(obj)

    async def get_capa(self, item_id: uuid.UUID) -> CorrectiveAction:
        obj = await self.capa_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "CAPA not found")
        return obj

    async def update_capa(
        self,
        item_id: uuid.UUID,
        data: CAPAUpdate,
        user_id: str | None = None,
    ) -> CorrectiveAction:
        obj = await self.get_capa(item_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.capa_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
            await _safe_audit(
                self.session,
                actor_id=user_id,
                entity_type="hse_capa",
                entity_id=str(item_id),
                action="updated",
                metadata={
                    "project_id": str(obj.project_id),
                    "fields": sorted(fields.keys()),
                },
            )
        return obj

    async def delete_capa(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> None:
        obj = await self.get_capa(item_id)
        snapshot = {
            "project_id": str(obj.project_id),
            "title": (obj.title or "")[:200],
            "status": obj.status,
        }
        await self.capa_repo.delete(item_id)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_capa",
            entity_id=str(item_id),
            action="deleted",
            metadata=snapshot,
        )

    async def escalate_capa(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> CorrectiveAction:
        obj = await self.get_capa(item_id)
        if "overdue" not in allowed_capa_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid CAPA transition {obj.status} → overdue",
            )
        prior = obj.status
        await self.capa_repo.update_fields(item_id, status="overdue")
        await self.session.refresh(obj)
        _safe_publish(
            "hse.capa.escalated",
            {
                "capa_id": str(item_id),
                "project_id": str(obj.project_id),
                "title": obj.title,
            },
        )
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_capa",
            entity_id=str(item_id),
            action="status_changed",
            from_status=prior,
            to_status="overdue",
            metadata={"project_id": str(obj.project_id)},
        )
        return obj

    async def close_capa(
        self,
        item_id: uuid.UUID,
        verification_notes: str = "",
        user_id: str | None = None,
    ) -> CorrectiveAction:
        obj = await self.get_capa(item_id)
        if "completed" not in allowed_capa_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid CAPA transition {obj.status} → completed",
            )
        prior = obj.status
        await self.capa_repo.update_fields(
            item_id,
            status="completed",
            completed_at=datetime.now(UTC),
            verification_notes=verification_notes,
        )
        await self.session.refresh(obj)
        _safe_publish(
            "hse.capa.completed",
            {
                "capa_id": str(item_id),
                "project_id": str(obj.project_id),
                "title": obj.title,
            },
        )
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_capa",
            entity_id=str(item_id),
            action="status_changed",
            from_status=prior,
            to_status="completed",
            metadata={
                "project_id": str(obj.project_id),
                "has_verification_notes": bool(verification_notes),
            },
        )
        return obj

    async def cancel_capa(
        self,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> CorrectiveAction:
        obj = await self.get_capa(item_id)
        if "cancelled" not in allowed_capa_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid CAPA transition {obj.status} → cancelled",
            )
        prior = obj.status
        await self.capa_repo.update_fields(item_id, status="cancelled")
        await self.session.refresh(obj)
        await _safe_audit(
            self.session,
            actor_id=user_id,
            entity_type="hse_capa",
            entity_id=str(item_id),
            action="status_changed",
            from_status=prior,
            to_status="cancelled",
            metadata={"project_id": str(obj.project_id)},
        )
        return obj

    # ── Certifications ──────────────────────────────────────────────────

    async def create_certification(self, data: CertificationCreate) -> SafetyCertification:
        obj = SafetyCertification(**data.model_dump())
        return await self.cert_repo.create(obj)

    async def get_certification(self, item_id: uuid.UUID) -> SafetyCertification:
        obj = await self.cert_repo.get_by_id(item_id)
        if obj is None:
            raise HTTPException(404, "Certification not found")
        return obj

    async def update_certification(self, item_id: uuid.UUID, data: CertificationUpdate) -> SafetyCertification:
        obj = await self.get_certification(item_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.cert_repo.update_fields(item_id, **fields)
            await self.session.refresh(obj)
        return obj

    async def expiring_certifications(self, days: int = 30, today: date | None = None) -> list[SafetyCertification]:
        today = today or date.today()
        certs = await self.cert_repo.expiring_within(days, today)
        # Publish a single dashboard tick for dashboard counters.
        if certs:
            _safe_publish(
                "hse.cert.expiring",
                {"count": len(certs), "days": days},
            )
        return certs

    # ── CAPA 5-Whys + Effectiveness Verification ─────────────────────────

    async def set_capa_five_whys(
        self,
        item_id: uuid.UUID,
        payload: CAPAFiveWhysPayload,
    ) -> CorrectiveAction:
        """Record a structured 5-Whys chain on a CAPA.

        Per Toyota TPS / TapRoot guidance, a 5-Whys chain should have at
        least three (and at most seven) steps. We enforce a soft bound
        of 3..10 to support both compact and deep chains.
        """
        if len(payload.steps) < 3:
            raise HTTPException(
                422,
                "5-Whys analysis must have at least 3 steps "
                "(TPS guidance: keep asking 'why' until the root cause surfaces).",
            )
        if len(payload.steps) > 10:
            raise HTTPException(422, "5-Whys chain capped at 10 steps")
        obj = await self.get_capa(item_id)
        await self.capa_repo.update_fields(
            item_id,
            five_whys=[s.model_dump() for s in payload.steps],
            **({"root_cause_category": payload.root_cause_category} if payload.root_cause_category else {}),
        )
        await self.session.refresh(obj)
        _safe_publish(
            "hse.capa.root_cause_recorded",
            {
                "capa_id": str(item_id),
                "project_id": str(obj.project_id),
                "steps_count": len(payload.steps),
                "category": payload.root_cause_category,
            },
        )
        return obj

    async def verify_capa_effectiveness(
        self,
        item_id: uuid.UUID,
        payload: CAPAEffectivenessPayload,
        verified_by: uuid.UUID | None = None,
    ) -> CorrectiveAction:
        """ISO 9001 §10.2.1 — verify that a CAPA actually worked.

        Allowed only on completed CAPAs. If the action proves
        ineffective, the CAPA is reopened.
        """
        obj = await self.get_capa(item_id)
        if obj.status != "completed":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Effectiveness can only be verified on completed CAPAs",
            )
        fields: dict[str, Any] = {
            "effectiveness_verified_at": datetime.now(UTC),
            "effectiveness_verified_by": verified_by,
        }
        if not payload.effective:
            # Reopen for further work — record the additional notes.
            fields["status"] = "in_progress"
            extra = (
                f"\n[Effectiveness check failed: {payload.notes}]"
                if payload.notes
                else "\n[Effectiveness check failed]"
            )
            fields["verification_notes"] = (obj.verification_notes or "") + extra
        elif payload.notes:
            fields["verification_notes"] = (obj.verification_notes or "") + f"\n[Effective: {payload.notes}]"
        await self.capa_repo.update_fields(item_id, **fields)
        await self.session.refresh(obj)
        _safe_publish(
            "hse.capa.effectiveness_verified",
            {
                "capa_id": str(item_id),
                "project_id": str(obj.project_id),
                "effective": payload.effective,
            },
        )
        return obj

    # ── JSA template library ─────────────────────────────────────────────

    async def create_jsa_template(
        self,
        data: JSATemplateCreate,
        user_id: str | None = None,
    ) -> JSATemplate:
        tpl = JSATemplate(
            trade=data.trade,
            name=data.name,
            task_description=data.task_description,
            hazards_json=[(h.model_dump() if hasattr(h, "model_dump") else dict(h)) for h in data.hazards],
            required_ppe_json=list(data.required_ppe),
            region=data.region,
            is_active=data.is_active,
            version=data.version,
            created_by=user_id,
        )
        return await self.jsa_template_repo.create(tpl)

    async def update_jsa_template(
        self,
        tpl_id: uuid.UUID,
        data: JSATemplateUpdate,
    ) -> JSATemplate:
        tpl = await self.jsa_template_repo.get_by_id(tpl_id)
        if tpl is None:
            raise HTTPException(404, "JSA template not found")
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "hazards" in fields and fields["hazards"] is not None:
            fields["hazards_json"] = [
                (h.model_dump() if hasattr(h, "model_dump") else dict(h)) for h in fields.pop("hazards")
            ]
        else:
            fields.pop("hazards", None)
        if "required_ppe" in fields and fields["required_ppe"] is not None:
            fields["required_ppe_json"] = list(fields.pop("required_ppe"))
        else:
            fields.pop("required_ppe", None)
        if fields:
            await self.jsa_template_repo.update_fields(tpl_id, **fields)
            await self.session.refresh(tpl)
        return tpl

    async def delete_jsa_template(self, tpl_id: uuid.UUID) -> None:
        tpl = await self.jsa_template_repo.get_by_id(tpl_id)
        if tpl is None:
            raise HTTPException(404, "JSA template not found")
        await self.jsa_template_repo.delete(tpl_id)

    async def clone_jsa_template_to_project(
        self,
        tpl_id: uuid.UUID,
        request: JSATemplateCloneRequest,
        user_id: str | None = None,
    ) -> JobSafetyAnalysis:
        """Deep-clone a JSA template into a project as a draft JSA."""
        tpl = await self.jsa_template_repo.get_by_id(tpl_id)
        if tpl is None:
            raise HTTPException(404, "JSA template not found")
        if not tpl.is_active:
            raise HTTPException(400, "Cannot clone an inactive JSA template")

        hazards = list(tpl.hazards_json or [])
        jsa = JobSafetyAnalysis(
            project_id=request.project_id,
            task_description=tpl.task_description,
            location=request.location,
            work_date=request.work_date,
            prepared_by=request.prepared_by,
            status="draft",
            hazards=hazards,
            required_ppe=list(tpl.required_ppe_json or []),
            risk_score=compute_jsa_risk(hazards),
            created_by=user_id,
        )
        jsa = await self.jsa_repo.create(jsa)
        _safe_publish(
            "hse.jsa.cloned_from_template",
            {
                "template_id": str(tpl_id),
                "jsa_id": str(jsa.id),
                "project_id": str(jsa.project_id),
                "trade": tpl.trade,
                "hazards_count": len(hazards),
            },
        )
        return jsa

    # ── OSHA Form 300 export ────────────────────────────────────────────

    # The official Form 300 carries many descriptive columns; this export
    # ships the subset that's load-bearing for the recordable-incident
    # audit trail. It is *not* a direct OSHA submission file — for that
    # employers file Form 300A through OSHA's ITA portal.
    _OSHA_300_HEADER: tuple[str, ...] = (
        "case_no",
        "employee_name",
        "job_title",
        "date_of_injury",
        "location",
        "description_of_injury",
        "days_away",
        "days_restricted",
        "death_yes_no",
        "other_recordable_yes_no",
    )

    async def generate_osha_300_csv(
        self,
        project_id: uuid.UUID,
        year: int,
    ) -> str:
        """‌⁠‍Render the OSHA 300 incident log for one project + year.

        Filters to ``SafetyIncident.osha_recordable=True`` and incidents
        whose ``incident_date`` (stored as ``YYYY-MM-DD`` string) starts
        with the requested year. Empty cells render as empty strings
        (Form 300 leaves blank fields blank). Uses the stdlib :mod:`csv`
        module so quoting follows RFC 4180.
        """
        stmt = (
            select(SafetyIncident)
            .where(SafetyIncident.project_id == project_id)
            .where(SafetyIncident.osha_recordable.is_(True))
        )
        rows = list((await self.session.execute(stmt)).scalars().all())

        year_prefix = f"{int(year):04d}-"
        rows = [r for r in rows if (r.incident_date or "").startswith(year_prefix)]

        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(self._OSHA_300_HEADER)

        for r in rows:
            ipd = r.injured_person_details or {}
            employee_name = (ipd.get("name") if isinstance(ipd, dict) else None) or ""
            job_title = (ipd.get("role") if isinstance(ipd, dict) else None) or ""
            # OSHA 1904.7 — fatality wins over "other recordable".
            is_fatality = (r.treatment_type or "").lower() == "fatality"
            death_yes_no = "Y" if is_fatality else "N"
            # "Other recordable" = recordable AND neither death nor
            # days_away nor days_restricted nor job-transfer (we collapse
            # the latter two into the days_restricted column).
            other_recordable = not is_fatality and not (r.days_away or 0) and not (r.days_restricted or 0)
            writer.writerow(
                [
                    r.osha_case_number or r.incident_number or "",
                    employee_name,
                    job_title,
                    r.incident_date or "",
                    r.location or "",
                    (r.description or "").replace("\r\n", " ").replace("\n", " "),
                    str(r.days_away) if r.days_away is not None else "",
                    str(r.days_restricted) if r.days_restricted is not None else "",
                    death_yes_no,
                    "Y" if other_recordable else "N",
                ]
            )

        return buf.getvalue()

    # ── Slim CorrectiveAction FSM (incident-scoped) ─────────────────────

    async def create_corrective_action(
        self,
        incident_id: uuid.UUID,
        description: str,
        assigned_to_user_id: uuid.UUID | None = None,
        due_date: date | None = None,
    ) -> HSECorrectiveAction:
        """‌⁠‍Open a new corrective action on an incident in status=pending."""
        obj = HSECorrectiveAction(
            incident_id=incident_id,
            description=description,
            assigned_to_user_id=assigned_to_user_id,
            due_date=due_date,
            status="pending",
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_corrective_action(
        self,
        ca_id: uuid.UUID,
    ) -> HSECorrectiveAction:
        obj = (
            await self.session.execute(select(HSECorrectiveAction).where(HSECorrectiveAction.id == ca_id))
        ).scalar_one_or_none()
        if obj is None:
            raise HTTPException(404, "Corrective action not found")
        return obj

    async def list_corrective_actions(
        self,
        *,
        incident_id: uuid.UUID | None = None,
        status_filter: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[HSECorrectiveAction]:
        stmt = select(HSECorrectiveAction)
        if incident_id is not None:
            stmt = stmt.where(HSECorrectiveAction.incident_id == incident_id)
        if status_filter is not None:
            stmt = stmt.where(HSECorrectiveAction.status == status_filter)
        stmt = stmt.offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def transition_corrective_action(
        self,
        ca_id: uuid.UUID,
        to_status: str,
        user_id: uuid.UUID | str | None,
        verification_notes: str | None = None,
    ) -> HSECorrectiveAction:
        """‌⁠‍Strict FSM transition.

        Allowed: ``pending → in_progress → verified → closed``. Any other
        target raises HTTP 409 with a message naming the rejected hop, so
        the UI can surface a clear actionable error.

        When entering ``verified`` we stamp ``verified_by_user_id`` +
        ``verified_at``. ``verification_notes`` is *appended* (preserving
        history) when provided — not overwritten — so the audit trail is
        not silently lost on subsequent transitions.
        """
        obj = await self.get_corrective_action(ca_id)
        if to_status not in allowed_corrective_action_transitions(obj.status):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invalid corrective-action transition "
                f"{obj.status} → {to_status} "
                f"(allowed: {allowed_corrective_action_transitions(obj.status) or 'none'})",
            )

        obj.status = to_status
        if to_status == "verified":
            verifier_uuid: uuid.UUID | None = None
            if user_id is not None:
                try:
                    verifier_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
                except (TypeError, ValueError):
                    verifier_uuid = None
            obj.verified_by_user_id = verifier_uuid
            obj.verified_at = datetime.now(UTC)
        if verification_notes:
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            entry = f"[{stamp} {to_status}] {verification_notes}"
            obj.verification_notes = f"{obj.verification_notes}\n{entry}" if obj.verification_notes else entry

        await self.session.flush()
        _safe_publish(
            "hse.corrective_action.transitioned",
            {
                "corrective_action_id": str(ca_id),
                "incident_id": str(obj.incident_id),
                "to_status": to_status,
                "verifier_id": str(user_id) if user_id else None,
            },
        )
        return obj
