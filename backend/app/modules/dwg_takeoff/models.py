"""‌⁠‍DWG Takeoff ORM models.

Tables:
    oe_dwg_takeoff_drawing          — uploaded DWG/DXF drawing files
    oe_dwg_takeoff_drawing_version  — parsed versions with layer/entity data
    oe_dwg_takeoff_annotation       — user annotations on drawings
    oe_dwg_entity_group             — saved multi-entity selections (RFC 11)
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Quantity-precision columns use Numeric instead of Float so DXF-derived
# measurements survive the round-trip into BOQ totals without accumulating
# binary float drift (flagged in the Round-3 Wave-A audit, 2026-05-21).
# Numeric(18, 6) covers every realistic takeoff measurement (km of pipe,
# m² of slab, kg of rebar) with 6 fractional digits — well past the
# precision DXF itself stores. Scales/thickness use Numeric(10, 6).
_MEASURE_NUMERIC = Numeric(18, 6)
_SCALE_NUMERIC = Numeric(10, 6)


class DwgDrawing(Base):
    """‌⁠‍Uploaded DWG/DXF drawing file."""

    __tablename__ = "oe_dwg_takeoff_drawing"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False, default="dxf")
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploaded")
    discipline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sheet_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    thumbnail_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Scale denominator for this drawing. 1.0 = raw DXF units (treated as
    # metres). 50.0 = 1:50 architectural scale. Calibrated values from the
    # two-point tool land here too, so the server has a single source of
    # truth instead of scattering ratios across client localStorage.
    scale_denominator: Mapped[Decimal] = mapped_column(
        _SCALE_NUMERIC,
        nullable=False,
        default=Decimal("1.0"),
        server_default="1.0",
    )
    # Which scale mode the user last used. Kept so the UI returns to
    # the same tab on reload instead of defaulting back to presets.
    # Values: "preset" | "calibrated" | "per_annotation".
    scale_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="preset",
        server_default="preset",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (Index("ix_dwg_drawing_project_status", "project_id", "status"),)

    def __repr__(self) -> str:
        return f"<DwgDrawing {self.name} ({self.file_format}) [{self.status}]>"


class DwgDrawingVersion(Base):
    """‌⁠‍Parsed version of a DWG/DXF drawing with extracted layers and entities."""

    __tablename__ = "oe_dwg_takeoff_drawing_version"

    drawing_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_dwg_takeoff_drawing.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    layers: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    entities_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    entity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extents: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    units: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="processing")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DwgDrawingVersion drawing={self.drawing_id} v{self.version_number} [{self.status}]>"


class DwgAnnotation(Base):
    """User annotation on a DWG/DXF drawing."""

    __tablename__ = "oe_dwg_takeoff_annotation"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drawing_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_dwg_takeoff_drawing.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drawing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_dwg_takeoff_drawing_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    annotation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    geometry: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3b82f6")
    line_width: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Stroke thickness in logical pixels. Separate from line_width so the
    # frontend can send fractional values (e.g. 1.5) without coercing to int.
    thickness: Mapped[Decimal] = mapped_column(
        _SCALE_NUMERIC,
        nullable=False,
        default=Decimal("2.0"),
        server_default="2.0",
    )
    # Virtual layer name used to group user-drawn markups. Defaults to
    # ``USER_MARKUP`` for primitive tools so estimators can toggle all
    # hand-drawn shapes on/off via the LayerPanel.
    layer_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="USER_MARKUP",
        server_default="USER_MARKUP",
    )
    measurement_value: Mapped[Decimal | None] = mapped_column(_MEASURE_NUMERIC, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Optional scale override for this annotation. When set, the frontend
    # divides raw measurements by this instead of the drawing-level scale
    # — used when one legend/detail view on the same sheet has a different
    # scale than the rest of the drawing (e.g. 1:100 plan + 1:20 detail).
    scale_override: Mapped[Decimal | None] = mapped_column(_SCALE_NUMERIC, nullable=True)
    linked_boq_position_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_punch_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    __table_args__ = (
        Index("ix_dwg_annotation_drawing_type", "drawing_id", "annotation_type"),
        Index("ix_dwg_annotation_linked_task", "linked_task_id"),
        Index("ix_dwg_annotation_linked_punch", "linked_punch_item_id"),
    )

    def __repr__(self) -> str:
        return f"<DwgAnnotation {self.annotation_type} drawing={self.drawing_id}>"


class DwgEntityGroup(Base):
    """Saved multi-entity selection on a DWG drawing (RFC 11).

    A group is a named bag of entity ids that can be linked as a single
    unit to a BOQ position. Stored as a separate table so groups have
    their own lifecycle (rename, delete, audit) independent of the
    underlying annotations.
    """

    __tablename__ = "oe_dwg_entity_group"

    drawing_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_dwg_takeoff_drawing.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (Index("ix_dwg_entity_group_drawing", "drawing_id"),)

    def __repr__(self) -> str:
        return f"<DwgEntityGroup {self.name} drawing={self.drawing_id} n={len(self.entity_ids or [])}>"
