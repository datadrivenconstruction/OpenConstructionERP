# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠External-review-authority ORM models.

Tables
======
``oe_review_authority_cycle``
    One review cycle a project runs with an external approving authority
    (state expertise, building control, an AHJ, a technical review board). It
    carries the submission reference, the SLA clock, the document version
    pinned at submission, the current document version, and the FSM status of
    the cycle. The pinned/current split is the heart of the module: an
    authority reviews the *submitted* version, so remarks issued against it are
    "stale" once the live document has moved on, and the platform must surface
    that rather than silently re-map remarks onto a newer drawing set.

``oe_review_authority_remark``
    One remark the authority raised against the submitted version, its
    contestability classification, severity, response and per-remark decision.
    ``repeat_of_id`` is the self-link the repeat-remark radar sets when a new
    remark matches a prior accepted one, so a reviewer can see the authority is
    re-raising a point already settled.

Design
======
- Tenancy is by ``project_id`` (non-null, cascade delete). The remark carries
  its own ``project_id`` (denormalised from the cycle) so the same
  ``verify_project_access`` guard applies to a remark id without a join, and a
  cross-project id surfaces as 404.
- All code fields are open-ended ``String`` (never DB enums) so a regional pack
  can introduce a new authority kind or classification without a migration; the
  API validates against the built-in whitelist so the UI pickers stay honest.
- Document versions are opaque ``String`` labels (``"A"``, ``"Rev 3"``,
  ``"2026-07-01"``) - the module compares them for equality, never parses them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ReviewCycle(Base):
    """One external review cycle a project runs with an approving authority."""

    __tablename__ = "oe_review_authority_cycle"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Authority & submission ─────────────────────────────────────────
    authority_name: Mapped[str] = mapped_column(String(255), nullable=False)
    authority_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="other",
        server_default="other",
        index=True,
    )
    submission_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ── Document version tracking ──────────────────────────────────────
    # ``pinned_document_version`` is frozen when the cycle moves to submitted:
    # it is the version the authority actually reviews. ``current_document_version``
    # follows the live document; when the two diverge, remarks against the
    # pinned version are flagged stale.
    pinned_document_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_document_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )

    # ── FSM status ─────────────────────────────────────────────────────
    # draft -> submitted -> under_review -> remarks_issued -> responding
    #       -> resubmitted -> approved | rejected | withdrawn
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )

    # ── SLA clock ──────────────────────────────────────────────────────
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=42,
        server_default="42",
    )

    # ── Context ────────────────────────────────────────────────────────
    # ISO country / region code, a plain tag for filtering and pack lookups -
    # never a rule. NULL = unspecified / global.
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<ReviewCycle {self.authority_kind} authority={self.authority_name[:30]!r} "
            f"status={self.status} pinned={self.pinned_document_version}>"
        )


class Remark(Base):
    """One remark the authority raised against the submitted version."""

    __tablename__ = "oe_review_authority_remark"

    cycle_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_review_authority_cycle.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the cycle so verify_project_access guards a remark id
    # without a join.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    section: Mapped[str | None] = mapped_column(String(120), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # ── Contestability ─────────────────────────────────────────────────
    # A remark with a norm reference is grounded; one without is contestable and
    # must be surfaced for human confirmation - the classifier never silently
    # decides it is contestable, it flags the missing reference.
    norm_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classification: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="no_norm_ref_contestable",
        server_default="no_norm_ref_contestable",
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="major",
        server_default="major",
    )

    # ── FSM status ─────────────────────────────────────────────────────
    # open -> responded -> accepted | contested | withdrawn
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Self-link the repeat radar sets: this remark repeats a prior accepted one.
    repeat_of_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_review_authority_remark.id", ondelete="SET NULL"),
        nullable=True,
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Remark #{self.ordinal} cycle={self.cycle_id} class={self.classification} status={self.status}>"


__all__ = ["Remark", "ReviewCycle"]
