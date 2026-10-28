# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Markups & Annotations ORM models.

Tables:
    oe_markups_markup          - drawing markups (cloud, arrow, text, etc.)
    oe_markups_scale_config    - scale calibration per document page
    oe_markups_stamp_template  - reusable stamp templates (Approved, Rejected, etc.)
    oe_markups_comment         - threaded comments attached to a markup
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Calibration & measurement values land in BOQ quantities → keep DECIMAL precision.
# Scale=6 matches the platform takeoff/finance convention (Phase 2e money_numeric).
_MEASUREMENT = Numeric(precision=18, scale=6)


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
    # Epic C: which version of ``document_id`` this markup was authored
    # against. The viewer fades markups whose ``file_version_id`` is
    # NOT the current version so users see at a glance that the markup
    # was drawn on an older revision. NULL = legacy markup (treat as
    # current; the viewer renders at full opacity). Set on create from
    # the chain head - see ``MarkupsService.create_markup``.
    file_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_file_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=None,
    )
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
    # M3: optional assignee for follow-up. Nullable because most markups
    # are anonymous review notes - only the ones that need owner-style
    # tracking get an assignee. ON DELETE SET NULL so deleting a user
    # does not destroy their pending markup queue.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=None,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    measurement_value: Mapped[Decimal | None] = mapped_column(_MEASUREMENT, nullable=True)
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
    pixels_per_unit: Mapped[Decimal] = mapped_column(_MEASUREMENT, nullable=False)
    unit_label: Mapped[str] = mapped_column(String(20), nullable=False, default="m")
    calibration_points: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    real_distance: Mapped[Decimal] = mapped_column(_MEASUREMENT, nullable=False)
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


class MarkupComment(Base):
    """Threaded comment attached to a markup.

    Comments are flat per markup (no nested replies in v1). Authorisation
    is delegated to the parent markup's project - anyone with project
    read access can list/post; deletion is restricted to the author or
    project owner via the router layer.
    """

    __tablename__ = "oe_markups_comment"

    markup_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_markups_markup.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<MarkupComment markup={self.markup_id} user={self.user_id}>"
