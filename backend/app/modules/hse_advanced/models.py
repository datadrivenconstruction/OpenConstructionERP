"""‌⁠‍HSE Advanced ORM models.

Tables:
    oe_hse_advanced_incident_investigation
    oe_hse_advanced_jsa
    oe_hse_advanced_jsa_template         (reusable tenant-level JSA library)
    oe_hse_advanced_ptw                  (permit-to-work)
    oe_hse_advanced_toolbox_talk
    oe_hse_advanced_toolbox_attendance
    oe_hse_advanced_toolbox_topic        (catalogue / library)
    oe_hse_advanced_ppe_issue
    oe_hse_advanced_audit
    oe_hse_advanced_audit_finding
    oe_hse_advanced_capa                 (corrective + preventive action)
    oe_hse_advanced_certification
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class HSEIncidentInvestigation(Base):
    """‌⁠‍In-depth root-cause investigation of a safety incident."""

    __tablename__ = "oe_hse_advanced_incident_investigation"

    # Plain UUID — references oe_safety_incident.id, no FK to avoid cross-module coupling
    incident_ref: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)

    investigation_lead: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    method: Mapped[str] = mapped_column(String(50), nullable=False, default="5_whys")
    findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendations: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="in_progress", index=True)
    report_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<HSEIncidentInvestigation incident={self.incident_ref} status={self.status}>"


class JobSafetyAnalysis(Base):
    """‌⁠‍JSA — Job Safety Analysis (a.k.a. Job Hazard Analysis)."""

    __tablename__ = "oe_hse_advanced_jsa"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    work_date: Mapped[str] = mapped_column(String(20), nullable=False)
    prepared_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    # hazards: [{step, hazard, severity, likelihood, controls}]
    hazards: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    required_ppe: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<JSA project={self.project_id} status={self.status} risk={self.risk_score}>"


class PermitToWork(Base):
    """PTW — Permit-to-Work (hot work, confined space, work at height, etc.)."""

    __tablename__ = "oe_hse_advanced_ptw"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permit_number: Mapped[str] = mapped_column(String(50), nullable=False)
    permit_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    work_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    work_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    supervisor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    jsa_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_hse_advanced_jsa.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="requested", index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    closure_checklist_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closure_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Prerequisites — checked before transition to 'active'
    prereq_jsa_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prereq_supervisor_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prereq_fire_watch_assigned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prereq_extinguisher_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prereq_atmospheric_test_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<PTW {self.permit_number} type={self.permit_type} status={self.status}>"


class JSATemplate(Base):
    """Reusable JSA template at tenant scope.

    Stored once per trade/region and cloned into per-project JSA rows.
    The hazards list mirrors :class:`JobSafetyAnalysis.hazards`, allowing
    a deep-clone with no shape conversion.
    """

    __tablename__ = "oe_hse_advanced_jsa_template"

    trade: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    hazards_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    required_ppe_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<JSATemplate {self.trade}/{self.name} v{self.version}>"


class ToolboxTalk(Base):
    """A delivered toolbox safety talk (5-min daily briefing)."""

    __tablename__ = "oe_hse_advanced_toolbox_talk"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_code: Mapped[str] = mapped_column(String(50), nullable=False)
    topic_title: Mapped[str] = mapped_column(String(500), nullable=False)
    conducted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    conducted_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    attendance_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # plain UUID — references oe_hse_advanced_toolbox_topic.id
    library_topic_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ToolboxTalk {self.topic_code} project={self.project_id}>"


class ToolboxAttendance(Base):
    """A single attendee at a ToolboxTalk."""

    __tablename__ = "oe_hse_advanced_toolbox_attendance"

    toolbox_talk_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_hse_advanced_toolbox_talk.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attendee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    attendee_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attendee_role: Mapped[str] = mapped_column(String(50), nullable=False, default="worker")
    signature_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attendance_status: Mapped[str] = mapped_column(String(50), nullable=False, default="present")

    def __repr__(self) -> str:
        return f"<ToolboxAttendance talk={self.toolbox_talk_id} name={self.attendee_name}>"


class ToolboxTopic(Base):
    """Reusable safety-talk catalogue entry (the "library" side)."""

    __tablename__ = "oe_hse_advanced_toolbox_topic"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general", index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<ToolboxTopic {self.code} category={self.category}>"


class PPEIssue(Base):
    """A single PPE issuance event tying gear to a worker."""

    __tablename__ = "oe_hse_advanced_ppe_issue"

    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    ppe_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date(), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="issued", index=True)

    def __repr__(self) -> str:
        return f"<PPEIssue type={self.ppe_type} status={self.status}>"


class SafetyAudit(Base):
    """A safety audit / site walk record."""

    __tablename__ = "oe_hse_advanced_audit"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    audit_type: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    conducted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    conducted_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    score_total: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # plain UUID — references external audit template registry
    checklist_template_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<SafetyAudit type={self.audit_type} status={self.status}>"


class SafetyAuditFinding(Base):
    """A single finding (passed or failed item) within a SafetyAudit."""

    __tablename__ = "oe_hse_advanced_audit_finding"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_hse_advanced_audit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other", index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    is_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    corrective_action_ref: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_hse_advanced_capa.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<AuditFinding audit={self.audit_id} category={self.category} passed={self.is_passed}>"


class CorrectiveAction(Base):
    """CAPA — corrective + preventive action tied to incident/JSA/audit/etc."""

    __tablename__ = "oe_hse_advanced_capa"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # plain UUID — depends on source_type (incident/jsa/audit/observation/permit)
    source_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_date: Mapped[date] = mapped_column(Date(), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    root_cause_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Structured 5-Whys chain (list of {"why": str, "answer": str}) — nullable
    # so existing rows continue to validate.
    five_whys: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    # Effectiveness verification (ISO 9001 §10.2.1) — a CAPA may close but
    # the corrective action's effectiveness is reviewed later.
    effectiveness_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    effectiveness_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CAPA {self.title} status={self.status} target={self.target_date}>"


class SafetyCertification(Base):
    """Worker safety certification (e.g. working-at-height, first-aid)."""

    __tablename__ = "oe_hse_advanced_certification"

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cert_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    issued_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[date] = mapped_column(Date(), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    document_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="valid", index=True)

    def __repr__(self) -> str:
        return f"<Certification {self.cert_type} status={self.status}>"
