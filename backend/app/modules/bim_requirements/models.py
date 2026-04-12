"""BIM Requirements ORM models.

Tables:
    oe_bim_requirement_set -- container for an imported requirement file
    oe_bim_requirement     -- individual requirement row (5-column universal model)
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BIMRequirementSet(Base):
    """Container for a group of BIM requirements from a single import."""

    __tablename__ = "oe_bim_requirement_set"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    requirements: Mapped[list["BIMRequirement"]] = relationship(
        back_populates="requirement_set",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BIMRequirement.created_at",
    )

    def __repr__(self) -> str:
        return f"<BIMRequirementSet {self.name} ({self.source_format})>"


class BIMRequirement(Base):
    """Individual BIM requirement -- 5-column universal model.

    Columns:
        element_filter  -- which element (JSONB: ifc_class, classification, ...)
        property_group  -- property set name (nullable for direct IFC attributes)
        property_name   -- property/attribute name
        constraint_def  -- constraint definition (JSONB: datatype, cardinality, enum, ...)
        context         -- when/who/why (JSONB: phase, actor, use_case, ...)
    """

    __tablename__ = "oe_bim_requirement"

    requirement_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_requirement_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element_filter: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    property_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    property_name: Mapped[str] = mapped_column(String(255), nullable=False)
    constraint_def: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    context: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    source_format: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    source_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    requirement_set: Mapped[BIMRequirementSet] = relationship(
        back_populates="requirements",
    )

    def __repr__(self) -> str:
        return f"<BIMRequirement {self.property_group}.{self.property_name}>"
