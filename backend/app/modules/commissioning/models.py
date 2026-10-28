# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commissioning (Cx) ORM models.

Tables (all prefixed ``oe_commissioning_``):
    oe_commissioning_system          - a commissionable building system
    oe_commissioning_checklist       - prefunctional / functional checklist
    oe_commissioning_checklist_item  - a single line within a checklist
    oe_commissioning_issue           - a deficiency / issue against a system

External references (``project_id``, ``created_by``, ``verified_by`` ...) are
stored as :class:`GUID` / ``String`` without an ORM ``ForeignKey`` wrapper to
keep the module loadable in minimal test fixtures that do not import the
``projects`` / ``users`` modules. The intra-module hierarchy
(system -> checklist -> item, system -> issue) *does* use real foreign keys
with ``ondelete="CASCADE"`` so deleting a system tears down its children.
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CxSystem(Base):
    """A commissionable system (e.g. an HVAC, electrical or fire system).

    Lifecycle status flows ``not_started -> in_progress -> tests_complete ->
    commissioned``. The final ``commissioned`` transition is gated by the
    commission-readiness rules in :mod:`app.modules.commissioning.validators`
    (no open functional checklist item, no open critical issue).
    """

    __tablename__ = "oe_commissioning_system"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="hvac",
        index=True,
    )
    tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_started",
        index=True,
    )
    # ISO-8601 timestamp string, populated when the system is commissioned.
    # Kept as String(32) for the same PG/SQLite portability reason the QMS
    # module uses (see app.modules.qms.models).
    commissioned_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    commissioned_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Plant item (soft id) this system is built from, for delivery-state preconditions.
    plant_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CxSystem {self.name} ({self.system_type}/{self.status})>"


class CxChecklist(Base):
    """A commissioning checklist attached to a :class:`CxSystem`.

    ``kind`` is ``prefunctional`` (static/installation checks done before
    energising) or ``functional`` (dynamic performance tests). Only
    ``functional`` items count toward system readiness and the commission gate.
    """

    __tablename__ = "oe_commissioning_checklist"

    system_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_commissioning_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="prefunctional",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Commissioning stage of a quality concept this checklist is run for (stage code).
    stage_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CxChecklist {self.title} ({self.kind})>"


class CxChecklistItem(Base):
    """A single check within a :class:`CxChecklist`.

    ``status`` is ``pending`` (not yet checked), ``pass``, ``fail`` or ``na``
    (not applicable). An item is "open" for commissioning purposes when it is
    neither ``pass`` nor ``na``.
    """

    __tablename__ = "oe_commissioning_checklist_item"

    checklist_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_commissioning_checklist.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        index=True,
    )
    result_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # ISO-8601 timestamp string, set whenever a pass/fail/na result is recorded.
    verified_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CxChecklistItem {self.description[:32]} ({self.status})>"


class CxIssue(Base):
    """A deficiency / issue raised against a :class:`CxSystem`.

    A ``critical`` issue that is still ``open`` blocks the system from being
    commissioned (see the commission gate in the service layer).
    """

    __tablename__ = "oe_commissioning_issue"

    system_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_commissioning_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="medium",
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="open",
        index=True,
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    raised_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CxIssue {self.description[:32]} ({self.severity}/{self.status})>"
