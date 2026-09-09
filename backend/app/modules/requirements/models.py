# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requirements & Quality Gates ORM models.

Tables:
    oe_requirements_set - container linking requirements to a project
    oe_requirements_item - individual EAC (Entity-Attribute-Constraint) triplets
    oe_requirements_gate_result - results of running quality gates
    oe_requirement_deliverable - ISO 19650 EIR deliverable rows per requirement
    oe_requirement_position_link - which priced work a requirement governs
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base
from app.modules.requirements.lifecycle import DEFAULT_VOCABULARY
from app.modules.requirements.lifecycle import cycle_completeness as _cycle_completeness
from app.modules.requirements.lifecycle import unanswered_questions as _unanswered_questions


class RequirementSet(Base):
    """Container for a group of requirements linked to a project."""

    __tablename__ = "oe_requirements_set"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    #: Which wording this set is read in: ``iso19650`` or ``neutral``. A set
    #: belongs to exactly one project, so this is the per-project switch. It
    #: renames concepts and never changes which ones exist, so a project can be
    #: flipped either way at any time without touching a single row.
    vocabulary: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DEFAULT_VOCABULARY,
        server_default=DEFAULT_VOCABULARY,
    )
    gate_status: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="requirement_set",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Requirement.created_at",
    )
    gate_results: Mapped[list["GateResult"]] = relationship(
        back_populates="requirement_set",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GateResult.gate_number",
    )

    def __repr__(self) -> str:
        return f"<RequirementSet {self.name} ({self.status})>"


class Requirement(Base):
    """Individual requirement expressed as an EAC (Entity-Attribute-Constraint) triplet.

    Example:
        entity="exterior_wall", attribute="fire_rating", constraint_type="equals",
        constraint_value="F90"
    """

    __tablename__ = "oe_requirements_item"

    requirement_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_requirements_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity: Mapped[str] = mapped_column(String(255), nullable=False)
    attribute: Mapped[str] = mapped_column(String(255), nullable=False)
    constraint_type: Mapped[str] = mapped_column(String(50), nullable=False, default="equals")
    constraint_value: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="must")
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")

    # ── The five questions the EAC triplet does not answer ──────────────────
    # All five carry ``server_default=""`` beside the Python default, the same
    # DEFAULT ``v3285_requirements_cycle`` declared. ``create_all`` reads the
    # model and never the revision, so without it every embedded and
    # self-hosted install built the five NOT NULL and defaultless, and the boot
    # repair ``requirements_cycle_not_null`` then reported five schema repairs
    # on a database that was seconds old.
    #: Warum. Why this is required at all, in the words of whoever asked. A
    #: requirement without one cannot be negotiated, only obeyed or broken.
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    #: Wer. Who raised it. Free text because the originator is often a document
    #: or an authority rather than a platform user.
    originator: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    #: Wer, as a controlled party role from ``lifecycle.ORIGINATOR_ROLES``.
    originator_role: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    #: Wann. A phase key from ``lifecycle.PHASE_SPINE``, never a display word,
    #: so the same row reads as "LP 5" in Germany and "Stage 4" in Britain.
    phase: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="", index=True)
    #: Wie. How compliance gets proven, from ``lifecycle.VERIFICATION_METHODS``.
    verification_method: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")

    #: A requirement decomposed from another one. Self-referencing, so a client
    #: demand can be broken into the specific constraints that satisfy it while
    #: the trail back to the demand survives.
    parent_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_requirements_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: Womit, kept for the rows written before the link table existed and for
    #: every caller that only ever wanted one position. New work should read
    #: ``position_links``; the migration copied each of these into one.
    linked_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    requirement_set: Mapped[RequirementSet] = relationship(
        back_populates="requirements",
        lazy="raise_on_sql",
    )
    deliverables: Mapped[list["RequirementDeliverable"]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RequirementDeliverable.created_at",
    )
    #: Womit. Every priced position this requirement governs.
    position_links: Mapped[list["RequirementPositionLink"]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RequirementPositionLink.created_at",
    )
    #: Requirements decomposed from this one. Down the tree eagerly, back up by
    #: id, per the platform's loading rule for self-referencing pairs.
    children: Mapped[list["Requirement"]] = relationship(
        back_populates="parent",
        lazy="selectin",
        foreign_keys=[parent_requirement_id],
    )
    parent: Mapped["Requirement | None"] = relationship(
        back_populates="children",
        lazy="raise_on_sql",
        remote_side="Requirement.id",
        foreign_keys=[parent_requirement_id],
    )

    @property
    def linked_position_ids(self) -> list[uuid.UUID]:
        """Every position this requirement governs, single-link one included.

        Reads through both the link table and the older single column, so a
        caller gets the same answer whether the row was written before or after
        the link table arrived.

        Requires ``position_links`` to be loaded. The ``selectin`` strategy
        above does that for a row that was queried, and only for one: it fires
        on a load, and the flush that follows an insert is not a load. A row
        this session has just created therefore arrives here unloaded unless
        something settles it, which is what ``settle_new_row`` in the
        repository is for.
        """
        ids = [link.position_id for link in self.position_links]
        if self.linked_position_id is not None and self.linked_position_id not in ids:
            ids.append(self.linked_position_id)
        return ids

    @property
    def _cycle_answers(self) -> dict[str, object]:
        """This requirement as the six answers, for the lifecycle helpers.

        ``position_links`` is passed as the read-through id list rather than the
        relationship, so a requirement whose only link is the legacy single
        column still counts as having answered "which work".
        """
        return {
            "entity": self.entity,
            "rationale": self.rationale,
            "originator": self.originator,
            "phase": self.phase,
            "verification_method": self.verification_method,
            "position_links": self.linked_position_ids,
        }

    @property
    def unanswered_questions(self) -> list[str]:
        """Which of the six questions this requirement has not answered.

        A property rather than something the router assembles, so every route
        that already serialises a requirement - the set detail, the matrix, the
        Excel export - gets the same answer without being edited one by one.
        """
        return list(_unanswered_questions(self._cycle_answers))

    @property
    def cycle_completeness(self) -> float:
        """Share of the six questions answered, as a percent in [0, 100]."""
        return _cycle_completeness(self._cycle_answers)

    def __repr__(self) -> str:
        return (
            f"<Requirement {self.entity}.{self.attribute} "
            f"{self.constraint_type}={self.constraint_value} ({self.status})>"
        )


class GateResult(Base):
    """Result of executing a quality gate on a requirement set.

    Gates:
        1 - Completeness: all requirements have entity+attribute+constraint
        2 - Consistency: no conflicting constraints for the same entity+attribute
        3 - Coverage: requirements cover all BOQ positions
        4 - Compliance: requirements align with project standard (DIN 276, NRM, etc.)
    """

    __tablename__ = "oe_requirements_gate_result"

    requirement_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_requirements_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gate_number: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="skipped")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    findings: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    executed_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")

    # Relationships
    requirement_set: Mapped[RequirementSet] = relationship(
        back_populates="gate_results",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<GateResult gate={self.gate_number} ({self.status})>"


class RequirementPositionLink(Base):
    """Womit: one requirement governing one priced BOQ position.

    ``Requirement.linked_position_id`` could only ever name a single position,
    which is not how a requirement behaves. "Every exterior wall is F90" governs
    each wall position in the bill, and a fire rating raised at tender governs
    whatever the contractor prices for it later. One column forced a choice
    between them; this table does not.

    The pair is unique, so linking the same position twice is a no-op rather
    than a duplicate row that inflates every coverage count downstream.
    """

    __tablename__ = "oe_requirement_position_link"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "position_id",
            name="uq_requirement_position_link",
        ),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_requirements_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: How the link was made: ``manual``, ``import``, ``ai`` or ``migrated``.
    #: An AI-proposed link is a suggestion until somebody confirms it, so the
    #: origin has to survive on the row rather than being lost at write time.
    link_source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    confirmed_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Relationships
    requirement: Mapped[Requirement] = relationship(
        back_populates="position_links",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<RequirementPositionLink req={self.requirement_id} pos={self.position_id} ({self.link_source})>"


class RequirementDeliverable(Base):
    """ISO 19650 Employer Information Requirements (EIR) deliverable row.

    Each requirement may demand one or more information deliverables -
    a 3D model at LOD 300, a schedule, a COBie export, a property-set
    submittal. The matrix view (rows = requirements, cols = deliverable
    types) is reconstructed by grouping rows of this table.

    States are derived from the timestamps:
        * ``accepted_at IS NOT NULL`` → ``accepted``
        * ``submitted_at IS NOT NULL`` → ``submitted``
        * else → ``missing``
    """

    __tablename__ = "oe_requirement_deliverable"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_requirements_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # model | drawing | schedule | report | cobie | pset | other
    deliverable_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # BIMForum LOD: 100 | 200 | 300 | 350 | 400 | 500
    lod: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # ISO 19650 LOI: 1 | 2 | 3 | 4 | 5
    loi: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: When it is due. The FK is what makes a deleted milestone clear the date
    #: instead of leaving a deliverable pointing at nothing; before it, this was
    #: a bare id that no constraint ever checked.
    due_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_milestone.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Relationships
    requirement: Mapped[Requirement] = relationship(
        back_populates="deliverables",
        lazy="raise_on_sql",
    )

    @property
    def status(self) -> str:
        """Derived status (accepted → submitted → missing)."""
        if self.accepted_at is not None:
            return "accepted"
        if self.submitted_at is not None:
            return "submitted"
        return "missing"

    def __repr__(self) -> str:
        return f"<RequirementDeliverable {self.deliverable_type} LOD={self.lod} LOI={self.loi} ({self.status})>"
