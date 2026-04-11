"""Requirements & Quality Gates ORM models.

Tables:
    oe_requirements_set — container linking requirements to a project
    oe_requirements_item — individual EAC (Entity-Attribute-Constraint) triplets
    oe_requirements_gate_result — results of running quality gates
"""

import uuid

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


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
    score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
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
