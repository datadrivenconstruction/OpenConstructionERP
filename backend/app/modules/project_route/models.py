# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Work-type route classifier ORM model.

Table:
    oe_project_route_assessment - a project-scoped record of a work-type
        classification and the delivery / permit route it resolved to. Each row
        stores the raw classifier answers (``criteria``), the route the decision
        tree determined, a human-readable rationale, a confidence score and a
        ``draft`` / ``confirmed`` status. A confirmed assessment is the gate the
        ``route_determined`` validation rule checks before a project proceeds.

Design
======
- Tenancy is by ``project_id`` (non-null, cascade delete), mirroring
  :mod:`app.modules.credentials` so the same ``verify_project_access`` guard
  applies and cross-project reads surface as 404.
- ``work_type`` and ``determined_route`` are open-ended ``String`` code fields
  (never DB enums) so a regional pack can introduce a new work type or route
  without a migration; the API validates against the built-in whitelists.
- ``criteria`` keeps the classifier answers verbatim so a re-classification (or
  an audit) can reproduce exactly why a route was chosen.
- ``confidence`` is the decision tree's self-reported certainty in ``0.0-1.0``;
  a low value on an ``undetermined`` route tells the UI to ask for manual
  assessment.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RouteAssessment(Base):
    """A work-type classification resolved to a delivery / permit route."""

    __tablename__ = "oe_project_route_assessment"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Classification input ───────────────────────────────────────────
    work_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    # The classifier answers verbatim (e.g. affects_structure, scale,
    # changes_use, within_permitted_limits, heritage_protected). Kept as data so
    # a re-classification or audit can reproduce the decision.
    criteria: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Classification output ──────────────────────────────────────────
    # One of: full_permit | notification | permitted_development | exempt |
    # expertise_required | undetermined.
    determined_route: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="undetermined",
        server_default="undetermined",
        index=True,
    )
    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )

    # ── Gate status ────────────────────────────────────────────────────
    # draft = classified but not yet accepted; confirmed = the route the
    # project proceeds under. Only a confirmed row satisfies route_determined.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )

    # ── Audit ──────────────────────────────────────────────────────────
    # ``timezone=True`` is not decoration: the service stamps this with an
    # aware ``datetime.now(UTC)``, and asyncpg refuses an aware value on a
    # naive ``timestamp`` column ("can't subtract offset-naive and
    # offset-aware datetimes"). Every other timestamp in the platform,
    # including ``created_at`` / ``updated_at`` on the Base, is aware.
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classified_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<RouteAssessment {self.work_type} -> {self.determined_route} "
            f"status={self.status} confidence={self.confidence}>"
        )


__all__ = ["RouteAssessment"]
