# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM Hub ORM models.

Tables:
    oe_bim_model        — imported BIM/CAD model metadata
    oe_bim_element      — individual elements extracted from a model
    oe_bim_boq_link     — links between BIM elements and BOQ positions
    oe_bim_quantity_map  — rules for mapping BIM quantities to BOQ items
    oe_bim_model_diff   — diff results between two model versions
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BIMModel(Base):
    """Imported BIM/CAD model — one record per uploaded file version."""

    __tablename__ = "oe_bim_model"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1")
    import_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="processing")
    element_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storey_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bounding_box: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    original_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    canonical_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_model_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_model.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    elements: Mapped[list["BIMElement"]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<BIMModel {self.name} ({self.status})>"


class BIMElement(Base):
    """Single element extracted from a BIM model."""

    __tablename__ = "oe_bim_element"
    __table_args__ = (
        Index("ix_bim_element_model_stable", "model_id", "stable_id"),
    )

    model_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stable_id: Mapped[str] = mapped_column(String(255), nullable=False)
    element_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storey: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    properties: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    quantities: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    geometry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bounding_box: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mesh_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lod_variants: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    model: Mapped[BIMModel] = relationship(back_populates="elements")
    boq_links: Mapped[list["BOQElementLink"]] = relationship(
        back_populates="bim_element",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<BIMElement {self.stable_id} ({self.element_type})>"


class BOQElementLink(Base):
    """Link between a BOQ position and a BIM element."""

    __tablename__ = "oe_bim_boq_link"
    __table_args__ = (
        UniqueConstraint("boq_position_id", "bim_element_id", name="uq_bim_boq_link_pos_elem"),
    )

    boq_position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    bim_element_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_element.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    link_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    bim_element: Mapped[BIMElement] = relationship(back_populates="boq_links")

    def __repr__(self) -> str:
        return f"<BOQElementLink pos={self.boq_position_id} elem={self.bim_element_id}>"


class BIMQuantityMap(Base):
    """Rule for mapping BIM element quantities to BOQ items."""

    __tablename__ = "oe_bim_quantity_map"

    org_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_translations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    element_type_filter: Mapped[str | None] = mapped_column(String(100), nullable=True)
    property_filter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quantity_source: Mapped[str] = mapped_column(String(100), nullable=False)
    multiplier: Mapped[str] = mapped_column(String(20), nullable=False, default="1")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    waste_factor_pct: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    boq_target: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BIMQuantityMap {self.name} ({self.quantity_source})>"


class BIMModelDiff(Base):
    """Diff result between two BIM model versions."""

    __tablename__ = "oe_bim_model_diff"
    __table_args__ = (
        UniqueConstraint("old_model_id", "new_model_id", name="uq_bim_model_diff_pair"),
    )

    old_model_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    new_model_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    diff_summary: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
    )
    diff_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BIMModelDiff old={self.old_model_id} new={self.new_model_id}>"
