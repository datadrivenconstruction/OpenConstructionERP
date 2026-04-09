"""Markups & Annotations ORM models.

Tables:
    oe_markups_markup          — drawing markups (cloud, arrow, text, etc.)
    oe_markups_scale_config    — scale calibration per document page
    oe_markups_stamp_template  — reusable stamp templates (Approved, Rejected, etc.)
"""

import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Markup(Base):
    """Drawing markup annotation on a project document page."""

    __tablename__ = "oe_markups_markup"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    geometry: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3b82f6")
    line_width: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    opacity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stamp_template_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_markups_stamp_template.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_boq_position_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    layer: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<Markup {self.type} page={self.page} layer={self.layer} ({self.status})>"


class ScaleConfig(Base):
    """Scale calibration for a document page (pixels-to-real-world mapping)."""

    __tablename__ = "oe_markups_scale_config"

    document_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pixels_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    unit_label: Mapped[str] = mapped_column(String(20), nullable=False, default="m")
    calibration_points: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    real_distance: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ScaleConfig doc={self.document_id} page={self.page} {self.pixels_per_unit} px/{self.unit_label}>"


class StampTemplate(Base):
    """Reusable stamp template for document annotations."""

    __tablename__ = "oe_markups_stamp_template"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="custom")
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#22c55e")
    background_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    include_date: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<StampTemplate {self.name} ({self.category})>"
