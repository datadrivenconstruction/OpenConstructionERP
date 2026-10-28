# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design-side site-supervision ORM models.

Tables:
    oe_site_supervision_visit - a supervision visit to a project by a member of
        the design team, planned and/or conducted, reported once written up. This
        is the "design-side inspection" that exists in most delivery frameworks
        under different names (author supervision / ЖАН in the CIS, contract
        administration inspection in the UK, construction administration in the
        US, Objektüberwachung / HOAI LP8 in Germany). The register is deliberately
        jurisdiction-neutral: it records that a visit happened, by whom, in which
        discipline, and what was observed - never a country's rule.
    oe_site_supervision_entry - a single observation raised on a visit: a
        conformance note, a deviation, a hidden-works acceptance item, an
        instruction, or a motivated refusal. Each entry carries a structured
        record that can serialise to a supervision-log XML and an optional link
        to a change / MOC record this observation feeds.

Design
======
- Tenancy is by ``project_id`` (non-null, cascade delete), mirroring
  :mod:`app.modules.credentials` so the same ``verify_project_access`` guard
  applies and cross-project reads surface as 404.
- An entry also carries ``project_id`` (denormalised from its visit) so a
  project-scoped access check and index need not join through the visit.
- Open-ended ``String`` code fields (never DB enums) so a regional pack can
  introduce a new discipline or category without a migration.
- ``status`` is stored, not computed, so list filters hit an index.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime as _datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SupervisionVisit(Base):
    """A design-side supervision visit to a project."""

    __tablename__ = "oe_site_supervision_visit"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── When ───────────────────────────────────────────────────────────
    # A visit may be planned (planned_date set, actual_date null), conducted
    # ad hoc (actual_date set, planned_date null), or both.
    planned_date: Mapped[_date | None] = mapped_column(Date, nullable=True, index=True)
    actual_date: Mapped[_date | None] = mapped_column(Date, nullable=True, index=True)

    # ── Who & what ─────────────────────────────────────────────────────
    visitor: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    discipline: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="general",
        server_default="general",
        index=True,
    )

    # planned | conducted | reported
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="planned",
        server_default="planned",
        index=True,
    )

    summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    photo_refs: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Audit ──────────────────────────────────────────────────────────
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<SupervisionVisit {self.discipline} visitor={self.visitor[:24]!r} "
            f"planned={self.planned_date} actual={self.actual_date} status={self.status}>"
        )


class SupervisionEntry(Base):
    """A single observation raised on a supervision visit."""

    __tablename__ = "oe_site_supervision_entry"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_supervision_visit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the visit so the project-scoped guard and filters need
    # not join through the visit.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ordinal: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    observation: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # conformance | deviation | hidden_works | instruction | motivated_refusal
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="conformance",
        server_default="conformance",
        index=True,
    )

    # A structured record that can serialise to a supervision-log XML. Neutral
    # keys: element / location / norm_ref / required_action (plus pack extras).
    structured_fields: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Optional id of a change / MOC record this observation feeds. A plain
    # reference string, never a hard FK, so the two modules stay decoupled.
    links_to_change_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # open | addressed | refused_motivated | closed
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    resolved_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<SupervisionEntry {self.ordinal} category={self.category} status={self.status} visit={self.visit_id}>"


__all__ = ["SupervisionEntry", "SupervisionVisit"]
