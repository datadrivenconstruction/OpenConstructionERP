"""‌⁠‍BCF (BIM Collaboration Format) ORM models.

Tables:
    oe_bcf_topic      — a BCF Topic (issue) scoped to a project
    oe_bcf_comment    — a comment on a topic
    oe_bcf_viewpoint  — a viewpoint (camera + selection/visibility) on a topic

These tables are the *source of truth* for BCF issues. The legacy
``opencde_api`` service maps the generic ``collaboration`` comment table to
the BCF API 3.0 REST surface; this module instead persists BCF natively so
that the ``.bcfzip`` import/export roundtrip is lossless (TopicGuid /
CommentGuid / ViewpointGuid are stored verbatim, not regenerated).

The viewpoint ``snapshot`` (PNG) is **not** stored inline — only its
storage key is. The binary lives behind :func:`app.core.storage.
get_storage_backend` under the ``bcf/<project_id>/...`` prefix, the same
abstraction BIM geometry and takeoff PDFs already use.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BCFTopic(Base):
    """‌⁠‍A BCF Topic (issue) attached to a project.

    Maps to ``<Topic>`` inside ``markup.bcf``. ``guid`` is the canonical
    BCF ``Topic/@Guid``; we keep it distinct from the surrogate ``id`` so
    an imported topic preserves its original GUID across roundtrips while
    still benefiting from the platform's ``GUID`` primary-key convention.
    """

    __tablename__ = "oe_bcf_topic"
    __table_args__ = (
        Index("ix_bcf_topic_project", "project_id"),
        # A BCF Topic GUID is unique *within a project*, not globally —
        # exporting from one project and importing into another must
        # preserve the GUID, so two projects can carry the same GUID.
        UniqueConstraint("project_id", "guid", name="uq_bcf_topic_project_guid"),
        Index("ix_bcf_topic_guid", "guid"),
    )

    guid: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional link to a BIM model (no hard FK — bim_hub may be disabled).
    bim_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    topic_status: Mapped[str] = mapped_column(String(100), nullable=False, default="Open", server_default="Open")
    priority: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    topic_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    reference_links: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    creation_author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modified_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    comments: Mapped[list["BCFComment"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BCFComment.date",
    )
    viewpoints: Mapped[list["BCFViewpoint"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BCFViewpoint.vp_index",
    )

    def __repr__(self) -> str:
        return f"<BCFTopic {self.guid} '{self.title}' ({self.topic_status})>"


class BCFComment(Base):
    """‌⁠‍A comment on a BCF topic.

    Maps to ``<Comment>`` inside ``markup.bcf``. ``viewpoint_guid``
    optionally references a sibling :class:`BCFViewpoint`'s ``guid``.
    """

    __tablename__ = "oe_bcf_comment"
    __table_args__ = (
        Index("ix_bcf_comment_topic", "topic_id"),
        UniqueConstraint("topic_id", "guid", name="uq_bcf_comment_topic_guid"),
        Index("ix_bcf_comment_guid", "guid"),
    )

    guid: Mapped[str] = mapped_column(String(36), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bcf_topic.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    comment_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modified_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewpoint_guid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    topic: Mapped[BCFTopic] = relationship(back_populates="comments")

    def __repr__(self) -> str:
        return f"<BCFComment {self.guid} on topic {self.topic_id}>"


class BCFViewpoint(Base):
    """A BCF viewpoint (camera + component selection/visibility).

    Maps to ``<ViewPoint>`` (markup) + the referenced ``*.bcfv``
    (``VisualizationInfo``). Camera, selection/visibility component GUIDs
    and clipping planes are stored in the ``camera`` / ``components`` /
    ``lines`` / ``clipping_planes`` JSON columns. The PNG ``snapshot`` is
    stored via the storage backend; only ``snapshot_key`` lives in the DB.
    """

    __tablename__ = "oe_bcf_viewpoint"
    __table_args__ = (
        Index("ix_bcf_viewpoint_topic", "topic_id"),
        UniqueConstraint("topic_id", "guid", name="uq_bcf_viewpoint_topic_guid"),
        Index("ix_bcf_viewpoint_guid", "guid"),
    )

    guid: Mapped[str] = mapped_column(String(36), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bcf_topic.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vp_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # "perspective" | "orthogonal" | "" (no camera).
    camera_type: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    camera: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Selection / visibility / coloring component GUID lists + view setup
    # hints, shaped after the BCF VisualizationInfo/Components element.
    components: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    lines: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    clipping_planes: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Stable canonical-format element ids this viewpoint highlights — a
    # platform extension carried in metadata so an IFC GUID can be mapped
    # back to a DDC canonical element without re-parsing the model.
    element_stable_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    snapshot_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snapshot_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    field_of_view: Mapped[float | None] = mapped_column(Float, nullable=True)
    view_to_world_scale: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    topic: Mapped[BCFTopic] = relationship(back_populates="viewpoints")

    def __repr__(self) -> str:
        return f"<BCFViewpoint {self.guid} idx={self.vp_index} on topic {self.topic_id}>"
