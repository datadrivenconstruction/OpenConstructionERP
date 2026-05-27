"""‌⁠‍QMS ORM models.

Tables (all prefixed ``oe_qms_``):
    oe_qms_itp_plan              — Inspection & Test Plan header
    oe_qms_itp_item              — line within an ITP
    oe_qms_itp_template          — tenant-level reusable ITP template
    oe_qms_inspection            — actual inspection event
    oe_qms_inspection_signature  — multi-signature on an inspection
    oe_qms_ncr                   — non-conformance report (QMS variant)
    oe_qms_ncr_action            — corrective action against an NCR
    oe_qms_punch_item            — rolling punch list entry
    oe_qms_audit                 — quality audit (ISO 9001 style)
    oe_qms_audit_finding         — finding within an audit
    oe_qms_audit_log             — append-only FSM transition audit trail
    oe_qms_calibration           — instrument calibration tracking

External entity FKs (``project_id``, ``inspector_user_id``,
``raised_by``, ``assigned_to``, ``verified_by``, ``signer_user_id``,
``auditor_user_id``, ``linked_variation_id``, ``linked_inspection_id``)
are stored as :class:`GUID` without an ORM-level
``ForeignKey(...)`` wrapper. This avoids breaking minimal-model test
fixtures that do not import the ``projects`` / ``users`` modules. The
referential constraint is still expressed in the Alembic migration
where the external table is guaranteed to exist.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ITPPlan(Base):
    """‌⁠‍Inspection & Test Plan header.

    An ITP is the project's checklist of control points (hold points,
    witness points, document reviews) for a specific work type — e.g.
    "Concrete pour — slab on grade". It is the QA template against
    which inspections are scheduled and signed off.
    """

    __tablename__ = "oe_qms_itp_plan"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_type: Mapped[str] = mapped_column(String(100), nullable=False)
    wbs_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ITPPlan {self.name} ({self.work_type}/{self.status})>"


class ITPItem(Base):
    """‌⁠‍A control point inside an :class:`ITPPlan`."""

    __tablename__ = "oe_qms_itp_item"

    itp_plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_qms_itp_plan.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    control_point_name: Mapped[str] = mapped_column(String(255), nullable=False)
    criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    hold_witness_point: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="review",
    )
    responsible_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signatories_required: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    def __repr__(self) -> str:
        return f"<ITPItem {self.sequence}: {self.control_point_name} ({self.hold_witness_point})>"


class QMSInspection(Base):
    """A scheduled / performed inspection against an :class:`ITPItem`."""

    __tablename__ = "oe_qms_inspection"

    itp_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_qms_itp_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    location_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inspector_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        # Use String(32) ISO timestamp to stay portable with SQLite tests;
        # production migration uses TIMESTAMPTZ for ordering.
        String(32),
        nullable=True,
    )
    performed_at: Mapped[datetime | None] = mapped_column(
        String(32),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="scheduled",
        index=True,
    )
    bim_element_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drawing_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    def __repr__(self) -> str:
        return f"<QMSInspection {self.id} ({self.status})>"


class QMSInspectionSignature(Base):
    """Signature against a :class:`QMSInspection` event."""

    __tablename__ = "oe_qms_inspection_signature"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_qms_inspection.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signer_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    signer_role: Mapped[str] = mapped_column(String(64), nullable=False)
    signed_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    signature_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="electronic",
    )
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<QMSInspectionSignature {self.signer_role} on {self.inspection_id}>"


class QMSNCR(Base):
    """QMS Non-Conformance Report (unified variant).

    Coexists with the legacy ``oe_ncr_ncr`` table. Cross-references to
    a legacy NCR may be carried in metadata if needed.
    """

    __tablename__ = "oe_qms_ncr"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    raised_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    raised_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="minor",
        index=True,
    )
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        index=True,
    )
    cost_impact_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
    )
    cost_impact_amount: Mapped[Decimal | None] = mapped_column(
        # Round 4/5 money convention: Numeric(18, 2). Original schema used
        # Numeric(15, 2); upgraded so very-large infrastructure NCRs no
        # longer truncate at 13 digits of integer precision.
        Numeric(18, 2),
        nullable=True,
    )
    linked_variation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    linked_inspection_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<QMSNCR {self.title[:32]} ({self.severity}/{self.status})>"


class QMSNCRAction(Base):
    """Corrective action against a :class:`QMSNCR`."""

    __tablename__ = "oe_qms_ncr_action"

    ncr_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_qms_ncr.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    due_date: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="assigned",
        index=True,
    )
    verification_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:
        return f"<QMSNCRAction {self.description[:32]} ({self.status})>"


class QMSPunchItem(Base):
    """Rolling punch list entry (QMS-managed)."""

    __tablename__ = "oe_qms_punch_item"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    raised_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    raised_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    room_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drawing_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bim_element_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="minor")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    photos_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<QMSPunchItem {self.title[:32]} ({self.status})>"


class QMSAudit(Base):
    """ISO 9001 style quality audit."""

    __tablename__ = "oe_qms_audit"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    audit_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="internal",
    )
    planned_date: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    performed_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    auditor_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    audit_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    standard_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="planned",
        index=True,
    )
    overall_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<QMSAudit {self.audit_type} ({self.status})>"


class QMSAuditFinding(Base):
    """A finding inside a :class:`QMSAudit`."""

    __tablename__ = "oe_qms_audit_finding"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_qms_audit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    finding_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="observation",
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    clause_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corrective_action_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        index=True,
    )
    due_date: Mapped[datetime | None] = mapped_column(String(32), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:
        return f"<QMSAuditFinding {self.finding_type} ({self.status})>"


class ITPTemplate(Base):
    """Reusable ITP template, scoped tenant-wide (no project_id).

    Used to seed project-level :class:`ITPPlan` rows. The template stores
    items inline as JSON so the entire library lives in a single row per
    template — easier to import/export across tenants.
    """

    __tablename__ = "oe_qms_itp_template"

    csi_division: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    work_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    standard_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # items: [{sequence, control_point_name, criteria, frequency, method,
    #          acceptance_criteria, hold_witness_point, responsible_role,
    #          signatories_required}]
    items_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ITPTemplate {self.csi_division}/{self.work_type} v{self.version}>"


class QMSAuditLog(Base):
    """Append-only audit trail for QMS FSM transitions.

    Every status change on an NCR, inspection, punch item, audit, or ITP
    plan should land one row here so dispute timelines (FIDIC, ISO 9001
    §9.3, SCL Protocol) can be reproduced offline. Schema mirrors the
    older ``oe_activity_log`` (v3033) but is QMS-scoped so a per-tenant
    GDPR purge can wipe quality records without touching cross-module
    activity.

    Fields:
        tenant_id        — caller's tenant for GDPR / multi-tenant scoping
        entity_type      — "ncr" / "inspection" / "punch" / "audit" /
                            "itp_plan" / "calibration"
        entity_id        — UUID of the row that transitioned
        action           — short verb ("created", "status_change",
                            "closed", "escalated", "signed", ...)
        actor_user_id    — caller; may be NULL for system-driven events
        old_status       — prior status; NULL on first creation
        new_status       — new status; NULL for non-FSM events (e.g. note)
        reason           — free-text justification (optional)
        before_state     — JSON snapshot of changed fields before the hop
        after_state      — JSON snapshot of the same fields after the hop

    Index strategy:
        ix_qms_audit_log_entity            (entity_type, entity_id)
        ix_qms_audit_log_tenant_created    (tenant_id, created_at)
    """

    __tablename__ = "oe_qms_audit_log"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    after_state: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<QMSAuditLog {self.entity_type}/{self.entity_id} {self.old_status or '-'}->{self.new_status or '-'}>"


class QMSCalibration(Base):
    """Instrument / equipment calibration certificate.

    Tracks calibration certificates with expiry windows. The notifications
    module subscribes to ``qms.calibration.expiring`` to alert owners.
    """

    __tablename__ = "oe_qms_calibration"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    instrument_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    instrument_name: Mapped[str] = mapped_column(String(255), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(100), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calibration_date: Mapped[date] = mapped_column(Date(), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    calibrated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    certificate_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reference_standard: Mapped[str | None] = mapped_column(String(255), nullable=True)
    measurement_uncertainty: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="valid",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<QMSCalibration {self.instrument_id} valid_until={self.valid_until}>"
