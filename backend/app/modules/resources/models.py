"""‌⁠‍Resources ORM models.

Tables:
    oe_resources_resource             — people / crews / equipment / subcontractors
    oe_resources_skill                — skill catalogue (trade / cert / language / other)
    oe_resources_resource_skill       — resource ↔ skill assignment with level
    oe_resources_certification        — certifications/licenses with expiry tracking
    oe_resources_availability_window  — availability / unavailability windows (RRULE-capable)
    oe_resources_assignment           — assignment to project/task/work order with allocation
    oe_resources_resource_request     — open request for a resource with required skills
    oe_resources_resource_link        — link between resources (operator <-> equipment, etc.)

NB: Per Wave 1 lessons, this module uses column-level ``index=True`` for single-
column indexes and ``__table_args__`` Index only for composite indexes. No
SQLAlchemy ``ForeignKey`` to ``oe_contacts_contact`` — declared only in the
Alembic migration (ORM keeps a plain UUID column).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Resource(Base):
    """‌⁠‍A resource that can be assigned to projects / tasks / work orders.

    resource_type controls behaviour:
        person          — individual worker
        crew            — predefined group (foreman + members)
        equipment       — machine/tool tracked in equipment module
        subcontractor   — external company
    """

    __tablename__ = "oe_resources_resource"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="person",
        server_default="person",
        index=True,
    )
    # Home project for project-local resources (e.g. site labour). NULL ⇒ shared
    # across the org / floating pool.
    home_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # NB: ``contact_id`` is a plain UUID — declared with a real FK only in the
    # Alembic migration so test fixtures (which don't load contacts) still work.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    default_cost_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active", index=True
    )
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<Resource {self.code} {self.name} ({self.resource_type}/{self.status})>"


class Skill(Base):
    """‌⁠‍A skill / qualification / language tag.

    category values: trade, certification, language, other
    """

    __tablename__ = "oe_resources_skill"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="trade",
        server_default="trade",
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<Skill {self.code} ({self.category})>"


class ResourceSkill(Base):
    """Link table: Resource has Skill at a given Level."""

    __tablename__ = "oe_resources_resource_skill"
    __table_args__ = (Index("ix_oe_resources_resource_skill_resource_skill", "resource_id", "skill_id"),)

    resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_skill.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="competent", server_default="competent")
    acquired_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<ResourceSkill r={self.resource_id} s={self.skill_id} lvl={self.level}>"


class Certification(Base):
    """Certification / license attached to a resource with expiry tracking."""

    __tablename__ = "oe_resources_certification"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cert_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    cert_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_until: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    document_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="valid", server_default="valid", index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<Certification {self.cert_type} ({self.status}) for {self.resource_id}>"


class AvailabilityWindow(Base):
    """Availability / unavailability window for a resource.

    window_type: available, unavailable, holiday, sick
    recurrence_rule: optional RFC-5545 RRULE string (None => single occurrence)
    """

    __tablename__ = "oe_resources_availability_window"
    __table_args__ = (
        Index(
            "ix_oe_resources_availability_window_resource_start",
            "resource_id",
            "start_at",
        ),
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="available",
        server_default="available",
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(512), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<AvailabilityWindow r={self.resource_id} {self.window_type} {self.start_at}→{self.end_at}>"


class Assignment(Base):
    """Assignment of a Resource to a project/task/work order over a time window."""

    __tablename__ = "oe_resources_assignment"
    __table_args__ = (
        Index("ix_oe_resources_assignment_resource_start", "resource_id", "start_at"),
        Index("ix_oe_resources_assignment_project_start", "project_id", "start_at"),
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FK to oe_tasks_task declared only in alembic migration; ORM-level
    # ForeignKey omitted to keep test fixtures lean (tasks model not always loaded).
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    # String-typed reference to either oe_service_work_order or
    # oe_equipment_work_order — no FK because the target table is not
    # known at model-definition time and may be created by a different
    # parallel agent.
    work_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    allocation_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default="100",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="proposed",
        server_default="proposed",
        index=True,
    )
    cost_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<Assignment r={self.resource_id} p={self.project_id} {self.start_at}→{self.end_at} {self.status}>"


class ResourceRequest(Base):
    """A request opened by a project to obtain a resource matching skills.

    Fulfilled by a Site Operations Manager who picks a resource and creates an
    Assignment linked back via fulfilled_assignment_id.
    """

    __tablename__ = "oe_resources_resource_request"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # JSON list of skill IDs (UUID strings)
    required_skills: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="med",
        server_default="med",
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    fulfilled_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_assignment.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<ResourceRequest {self.title[:40]} ({self.status}/{self.priority})>"


class ResourceLink(Base):
    """Link between two resources (e.g. operator <-> crane, buddy pair, crew member)."""

    __tablename__ = "oe_resources_resource_link"
    __table_args__ = (
        Index(
            "ix_oe_resources_resource_link_primary_secondary",
            "primary_resource_id",
            "secondary_resource_id",
        ),
    )

    primary_resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
    )
    secondary_resource_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="buddy",
        server_default="buddy",
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<ResourceLink {self.primary_resource_id}<->{self.secondary_resource_id} ({self.link_type})>"
