# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Coordination Hub — persisted ORM models.

The hub remains a *thin* aggregator across the sibling BIM modules; the
only state it owns is the per-project alert threshold configuration that
drives "this project is in trouble" signalling on top of the dashboard.

Thresholds default-seed on first read for any project (see
:meth:`CoordinationHubService.get_or_seed_thresholds`); the defaults pin
the BIMcollab / BIM Track / Navisworks "open coordination debt" rules of
thumb to OCERP's own numbers (open clashes total, severity breach,
cost-impact as % of budget, model-age staleness).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Boolean

from app.database import GUID, Base


class CoordinationThreshold(Base):
    """‌⁠‍Per-project warn / error threshold for one named coordination metric.

    A single project may carry one row per ``metric`` value (the
    ``(project_id, metric)`` pair is unique). Rows are seeded the first
    time the project's thresholds endpoint is hit so the API never
    returns an empty payload — the operator gets sensible defaults they
    can then edit.

    The values are :class:`~decimal.Decimal` (persisted as ``NUMERIC``)
    rather than ``float`` because some metrics (``open_cost_impact_pct_of_budget``)
    are user-facing percentages and silent float drift in the threshold
    column would surface as confusing "off-by-0.00001" alerts.
    """

    __tablename__ = "oe_coordination_threshold"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "metric",
            name="uq_coordination_threshold_project_metric",
        ),
        Index(
            "ix_coordination_threshold_project",
            "project_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: The canonical metric key — one of the values returned by
    #: :func:`default_thresholds` (extended over time by add-on modules).
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    warn_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    error_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"<CoordinationThreshold project={self.project_id} "
            f"metric={self.metric} warn={self.warn_value} "
            f"error={self.error_value} enabled={self.enabled}>"
        )


#: Default warn/error values per metric. The hub seeds these the first
#: time a project's thresholds endpoint is touched. Editing a default
#: persists the new row; un-edited metrics never need a DB row.
DEFAULT_THRESHOLDS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("open_clashes_total", Decimal("50"), Decimal("200")),
    ("high_severity_clashes", Decimal("5"), Decimal("20")),
    ("open_cost_impact_pct_of_budget", Decimal("2.0"), Decimal("5.0")),
    ("model_age_days_max", Decimal("14"), Decimal("30")),
)

#: Set of every metric the hub knows how to evaluate. PUT endpoints
#: 422 on any key not in this set so a typo'd metric can't ghost-write
#: a row no evaluator ever reads.
KNOWN_METRICS: frozenset[str] = frozenset(m for m, _w, _e in DEFAULT_THRESHOLDS)
