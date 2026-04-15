"""DWG Takeoff ORM models.

Tables:
    oe_dwg_takeoff_drawing          — uploaded DWG/DXF drawing files
    oe_dwg_takeoff_drawing_version  — parsed versions with layer/entity data
    oe_dwg_takeoff_annotation       — user annotations on drawings
"""

import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DwgDrawing(Base):
    """Uploaded DWG/DXF drawing file."""

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
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (
        Index("ix_dwg_drawing_project_status", "project_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<DwgDrawing {self.name} ({self.file_format}) [{self.status}]>"


class DwgDrawingVersion(Base):
    """Parsed version of a DWG/DXF drawing with extracted layers and entities."""

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
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
