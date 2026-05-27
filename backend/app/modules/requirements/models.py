"""‌⁠‍Requirements & Quality Gates ORM models.

Tables:
    oe_requirements_set — container linking requirements to a project
    oe_requirements_item — individual EAC (Entity-Attribute-Constraint) triplets
    oe_requirements_gate_result — results of running quality gates
    oe_requirement_deliverable — ISO 19650 EIR deliverable rows per requirement
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class RequirementSet(Base):
    """‌⁠‍Container for a group of requirements linked to a project."""

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
    """‌⁠‍Individual requirement expressed as an EAC (Entity-Attribute-Constraint) triplet.

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
    )
    deliverables: Mapped[list["RequirementDeliverable"]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RequirementDeliverable.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Requirement {self.entity}.{self.attribute} "
            f"{self.constraint_type}={self.constraint_value} ({self.status})>"
        )


class GateResult(Base):
    """Result of executing a quality gate on a requirement set.

    Gates:
        1 — Completeness: all requirements have entity+attribute+constraint
        2 — Consistency: no conflicting constraints for the same entity+attribute
        3 — Coverage: requirements cover all BOQ positions
        4 — Compliance: requirements align with project standard (DIN 276, NRM, etc.)
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
    )

    def __repr__(self) -> str:
        return f"<GateResult gate={self.gate_number} ({self.status})>"


class RequirementDeliverable(Base):
    """‌⁠‍ISO 19650 Employer Information Requirements (EIR) deliverable row.

    Each requirement may demand one or more information deliverables —
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
    due_milestone_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Relationships
    requirement: Mapped[Requirement] = relationship(
        back_populates="deliverables",
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
