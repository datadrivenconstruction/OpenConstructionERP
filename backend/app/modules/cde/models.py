# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CDE (Common Data Environment) ORM models.

Tables:
    oe_cde_container         - ISO 19650 document containers
    oe_cde_revision          - document revisions within containers
    oe_cde_state_transition  - audit log of every CDE state transition
    oe_cde_settings          - one-row-per-project CDE setup configuration
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# ── CDE settings defaults ─────────────────────────────────────────────────
# Module-level defaults so the model, the schema and any lazy get-or-create all
# read from one source (mirrors MATCH_DEFAULT_* in the projects module).

#: Default suitability-code set a new project's CDE uses. Only ISO 19650 today,
#: kept as a field so a future standard can be selected per project.
CDE_DEFAULT_SUITABILITY_SET = "iso19650"

#: Default readiness level the go-live gate requires before the whole team can
#: be invited onto the CDE. "operational" means the workflow has actually been
#: exercised end to end, not just configured on paper.
CDE_DEFAULT_MIN_READINESS_LEVEL = "operational"


class DocumentContainer(Base):
    """An ISO 19650 document container with CDE state management."""

    __tablename__ = "oe_cde_container"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    container_code: Mapped[str] = mapped_column(String(255), nullable=False)
    originator_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    functional_breakdown: Mapped[str | None] = mapped_column(String(50), nullable=True)
    spatial_breakdown: Mapped[str | None] = mapped_column(String(50), nullable=True)
    form_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discipline_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sequence_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    classification_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cde_state: Mapped[str] = mapped_column(String(50), nullable=False, default="wip", index=True)
    suitability_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    current_revision_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_classification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DocumentContainer {self.container_code} ({self.cde_state})>"


class DocumentRevision(Base):
    """A revision of a document within a CDE container."""

    __tablename__ = "oe_cde_revision"

    container_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cde_container.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_code: Mapped[str] = mapped_column(String(20), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_preliminary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    approved_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cross-link to the Documents hub row materialised when a revision carries a file.
    # Kept as a String(36) so it is nullable + safe across PG/SQLite without a FK.
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DocumentRevision {self.revision_code} ({self.status})>"


class StateTransition(Base):
    """Persistent audit log of every CDE state transition.

    One row is written inline inside ``CDEService.transition_state`` for every
    valid gate crossing - so a rolled-back transaction never leaves an orphan
    audit row (event-bus consumers can't guarantee that).
    """

    __tablename__ = "oe_cde_state_transition"

    container_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cde_container.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    gate_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<StateTransition {self.from_state}->{self.to_state} container={self.container_id}>"


class CdeSettings(Base):
    """One-row-per-project CDE setup configuration.

    Persists what the CDE setup wizard captures for a single project: the naming
    convention, which suitability-code set is in force, which functional role is
    assigned to which user, the chosen review preset, and the go-live gate that
    protects the CDE from being opened to the whole team before the workflow has
    actually been exercised. Mirrors the ``MatchProjectSettings`` 1:1-per-project
    precedent - a ``UniqueConstraint`` on ``project_id`` enforces the single row,
    and a lazy get-or-create in the service seeds defaults on first read.
    """

    __tablename__ = "oe_cde_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_cde_settings_project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Free-text ISO 19650 naming convention / pattern the project agreed (e.g.
    # "Project-Originator-Functional-Spatial-Form-Discipline-Number"). Empty
    # until the wizard sets it.
    naming_convention: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    # Which suitability-code set drives the container status picker.
    suitability_set: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=CDE_DEFAULT_SUITABILITY_SET,
        server_default=CDE_DEFAULT_SUITABILITY_SET,
    )
    # The chosen review preset - an approval-route ``system_key`` (e.g.
    # "cde_review_and_publish") or NULL when the project has not picked one.
    # Kept even after adoption below as a label/audit trail of which preset the
    # project started from.
    review_preset_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The project's own EDITABLE review route, cloned from ``review_preset_key``
    # by ``CDEService.apply_approval_preset`` (see approval_routes.clone_route).
    # A soft cross-module reference (no FK, mirrors ``DocumentRevision.document_id``)
    # so the CDE module stays decoupled from approval_routes' table lifecycle;
    # NULL until a preset has actually been adopted into this project.
    review_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Functional-role assignment: {role_key: user_id}, e.g.
    # {"author": "<uuid>", "reviewer": "<uuid>", ...}. Free-form so a role can be
    # left unassigned; validated against the four ISO 19650 roles in the schema.
    role_assignments: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Anti-"showroom" protection: when on, the whole team cannot be invited onto
    # the CDE until readiness reaches ``min_readiness_level``.
    go_live_gate_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    min_readiness_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=CDE_DEFAULT_MIN_READINESS_LEVEL,
        server_default=CDE_DEFAULT_MIN_READINESS_LEVEL,
    )
    # Wizard progress: whether the guided setup was finished, and the last step
    # reached so the wizard can resume where the user left off.
    setup_completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    setup_step: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    def __repr__(self) -> str:
        return f"<CdeSettings project={self.project_id} completed={self.setup_completed}>"
