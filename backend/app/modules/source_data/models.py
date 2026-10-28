# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Source-data (prerequisite documents) register ORM models.

Tables:
    oe_source_data_document - a project-scoped register of the prerequisite
        source documents a delivery depends on before work can proceed:
        permits, surveys, geotechnical reports, technical conditions, title
        deeds, approvals and technical specifications (RU: ИРД). Each row
        carries a validity window and a reminder threshold so the platform can
        warn before a document lapses, an optional shelf-life, and a
        ``blocks_schedule`` flag so an expired prerequisite can surface as a
        blocker on the programme.

    oe_source_data_checklist_item - the "what source data do we still need"
        checklist for a project. Each item names a required (or optional)
        prerequisite, the kind of document that satisfies it, and the document
        that actually did (once one is supplied). Completeness of the required
        items is a first-class validation signal.

Why a dedicated register
========================
Prerequisite documents are the gate every construction delivery passes through
before it can start: without the permit, the survey or the technical conditions
in hand and in date, the schedule cannot legitimately begin. This register makes
that explicit - it tracks *what* each prerequisite is, *when* it is valid, and
*whether* its absence or expiry blocks the programme. It is deliberately
jurisdiction-neutral: it stores the document and its validity, never a country's
rule. Per-country vocabularies (which permit, which authority) come from the
regional packs.

Design
======
- Tenancy is by ``project_id`` (non-null, cascade delete), mirroring
  :mod:`app.modules.credentials` so the same ``verify_project_access`` guard
  applies and cross-project reads surface as 404.
- ``status`` is derived from the validity window on every write and stored (not
  computed) so ``status='expiring_soon'`` list filters hit an index. The
  lifecycle states (requested / received / verified) and the terminal
  ``superseded`` state are preserved and never auto-flipped.
- ``superseded_by_id`` is an optional self-FK so a re-issued document can point
  at the version that replaced it.
- Open-ended ``String`` code fields (never DB enums) so a pack can introduce a
  new document type without a migration.
"""

from __future__ import annotations

import uuid
from datetime import date as _date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SourceDocument(Base):
    """A tracked prerequisite source document for a project."""

    __tablename__ = "oe_source_data_document"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Identity ───────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    # The party responsible for procuring / holding the document (e.g. the
    # client, the designer, a statutory body). A plain label, never a user link.
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ── Validity window ────────────────────────────────────────────────
    issued_at: Mapped[_date | None] = mapped_column(Date, nullable=True)
    # NULL valid_until = a perpetual document that never expires; it stays in
    # its in-hand state (received / verified) and never enters an expiry state.
    valid_until: Mapped[_date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )
    # Optional shelf life in days - the period the document stays usable from
    # issue. Advisory metadata; the authoritative expiry is ``valid_until``.
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify_days_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )

    # ── Schedule impact ────────────────────────────────────────────────
    # True when the document is a hard prerequisite whose absence / expiry
    # blocks the programme. Combined with an ``expired`` status this is what the
    # blocking-schedule query surfaces.
    blocks_schedule: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    # ── Derived status (recomputed on every write) ────────────────────
    # One of: requested | received | verified | expiring_soon | expired |
    # superseded. Stored so the index hits without a window function.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="requested",
        server_default="requested",
        index=True,
    )

    # ── Supersession ───────────────────────────────────────────────────
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_source_data_document.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Free-form ──────────────────────────────────────────────────────
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Audit ─────────────────────────────────────────────────────────
    created_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<SourceDocument {self.doc_type} name={self.name[:30]!r} "
            f"valid_until={self.valid_until} status={self.status}>"
        )


class SourceChecklistItem(Base):
    """A single required-or-optional prerequisite on a project's source-data checklist."""

    __tablename__ = "oe_source_data_checklist_item"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # Whether the delivery cannot proceed without this item; required items drive
    # the ``source_data_completeness`` validation rule.
    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    # The kind of document that satisfies this item (open-ended code, may be
    # NULL when any document will do).
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The document that actually satisfied the item, once supplied.
    satisfied_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_source_data_document.id", ondelete="SET NULL"),
        nullable=True,
    )
    # One of: pending | satisfied | waived. ``waived`` is an explicit decision
    # that the item is not needed on this project; it counts as resolved.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<SourceChecklistItem label={self.label[:30]!r} required={self.required} status={self.status}>"


__all__ = ["SourceChecklistItem", "SourceDocument"]
