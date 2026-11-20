"""Design module tables. Secrets (link codes, tokens) are stored only as sha256 hashes.

Tables are built by the ERP's create_all at boot (every app.modules.*.models is imported).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DesignRevision(Base):
    """One accepted-or-pending package ``ddc-revision/1``. ``id`` = manifest ``revision_id``."""

    __tablename__ = "oe_design_revision"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_design_revision_project_number"),
        Index("ix_design_revision_project_status", "project_id", "status"),
        # At most one published revision per project; concurrent accepts lose here.
        Index(
            "uq_design_revision_one_published",
            "project_id",
            unique=True,
            sqlite_where=text("status = 'published'"),
            postgresql_where=text("status = 'published'"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # CDE states: shared (awaiting acceptance) -> published | rejected; published -> archived.
    # "uploading" marks a claimed row whose files are still being stored; never shown.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="shared", server_default="shared")
    # generated | edited | imported; an imported row without a package carries a ddc-import/1 record (R16).
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    depth_level: Mapped[str] = mapped_column(String(4), nullable=False)  # "" = wrapped import, not stated
    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[assignment]
    storage_prefix: Mapped[str] = mapped_column(String(255), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bim_model_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class DesignLinkCode(Base):
    """Single-use code inside a ``.ddclink`` file; lives 5 minutes."""

    __tablename__ = "oe_design_link_code"

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesignLinkToken(Base):
    """Project-scoped bearer token held by one editor installation."""

    __tablename__ = "oe_design_link_token"

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    client_version: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    client_os: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesignEstimate(Base):
    """The cost estimate (one BOQ) that the rules of a project keep in step with its accepted revisions."""

    __tablename__ = "oe_design_estimate"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    boq_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    use: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    aggregate_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    # Revision whose model the positions currently follow (the last accepted one, or the first run).
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignEstimateRule(Base):
    """One ``ddc-rules/1`` rule of a project; the body is the rule object as validated."""

    __tablename__ = "oe_design_estimate_rule"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_design_rule_project_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    body: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[assignment]
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class DesignEstimateBinding(Base):
    """Position <-> rule, with what the model says beside what a person set."""

    __tablename__ = "oe_design_estimate_binding"
    __table_args__ = (UniqueConstraint("project_id", "rule_code", name="uq_design_binding_project_rule"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    boq_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    position_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    link_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # What the rules computed from the revision, as a decimal string; None before the first run.
    model_quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # What the rules last wrote to the position. A position quantity that differs from it is an override.
    last_applied_quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    element_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    # no_match, override, unpriced, rate_missing, input_missing
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    # Formula, aggregates used, sources: shown with the position.
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]


class DesignProjectOption(Base):
    """Per-project choices of the module. ``change_orders``: off | ask | always (R9)."""

    __tablename__ = "oe_design_project_option"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    change_orders: Mapped[str] = mapped_column(String(8), nullable=False, default="ask", server_default="ask")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignChangeOrder(Base):
    """The cost snapshot of one accepted revision and the change order made from it (at most one per revision)."""

    __tablename__ = "oe_design_change_order"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    # Plain UUID: the change order may be deleted in its own register; that shows as state "deleted".
    change_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Impact (ddc-impact/1) and element diff taken before the accept moved the positions.
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[assignment]
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignSchedule(Base):
    """The ERP schedule that sourced productivity rates keep in step with accepted revisions (R10)."""

    __tablename__ = "oe_design_schedule"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    use: Mapped[str] = mapped_column(String(40), nullable=False)
    # Crew per rule a person set: {"wall_ext": 4}. Absent rules use the source crew, else the ERP default gang.
    crews: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignScheduleBinding(Base):
    """Activity <-> (rule, storey), with the duration the rates give beside what a person set."""

    __tablename__ = "oe_design_schedule_binding"
    __table_args__ = (UniqueConstraint("project_id", "rule_code", "storey", name="uq_design_sched_rule_storey"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    storey: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # "" = whole building
    activity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    model_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_applied_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # no_match, override, rate_missing, estimate_override
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]


from .brief_models import DesignBrief, DesignBriefVersion  # noqa: E402,F401  (create_all imports models only)


class DesignJob(Base):
    """One server-side generation run (ddc-job/1). The ERP job queue only carries it; this row is the truth."""

    __tablename__ = "oe_design_job"
    __table_args__ = (
        # ``slot`` is "1" while the job is active and NULL afterwards: one active job per project.
        UniqueConstraint("project_id", "slot", name="uq_design_job_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    brief_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    slot: Mapped[str | None] = mapped_column(String(1), nullable=True, default="1")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    log: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    job_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    lock_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


from .procurement_models import (  # noqa: E402,F401  (create_all imports models only)
    DesignProcurement,
    DesignTakeoffLine,
    DesignTakeoffSection,
)


class DesignDraft(Base):
    """The browser editor's autosaved work of one person on one project: a ``.ddcrev`` package not yet a revision.

    Its quantities and estimate are computed on every save (``draft_estimate``) so the ERP shows them at once;
    ``POST /projects/{id}/draft/revision`` turns it into a revision through the normal intake."""

    __tablename__ = "oe_design_draft"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_design_draft_project_user"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    package: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    element_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimate: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[assignment]


class DesignEditRights(Base):
    """Who may edit drafts and create revisions on a project: ``members`` (anyone who may publish, the default)
    or ``managers`` (those who may accept). Accepting stays with managers either way."""

    __tablename__ = "oe_design_edit_rights"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    edit: Mapped[str] = mapped_column(String(10), nullable=False, default="members", server_default="members")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignAiChoice(Base):
    """The editor's own AI choice of one person; no row = the same as their ERP AI settings."""

    __tablename__ = "oe_design_ai_choice"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    preferred_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
