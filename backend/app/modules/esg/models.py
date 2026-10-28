# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ESG Site Performance ORM models.

Tables:
    oe_esg_entry - one operational ESG reading for a metric in a period.

The set of metrics itself is a code-defined catalogue (see
``app.modules.esg.catalogue``), not a table, so only the readings are persisted.
Each reading is scoped to a project and a ``YYYY-MM`` period; the service keeps
at most one reading per (project, metric, period).
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EsgEntry(Base):
    """A single operational ESG reading for one metric in one period.

    ``value`` and ``target`` are stored as ``Numeric`` so the figures stay exact
    (no binary-float drift); they serialise to JSON as strings. ``metric_key``
    references the code catalogue rather than a foreign-key table.
    """

    __tablename__ = "oe_esg_entry"
    __table_args__ = (
        # One reading per metric per period per project; the service enforces
        # this with a pre-check (409), and the composite index also makes the
        # per-metric period lookups the summary runs cheap.
        Index(
            "ix_oe_esg_entry_project_metric_period",
            "project_id",
            "metric_key",
            "period",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Catalogue key, e.g. "energy_diesel_l". Validated against the catalogue in
    # the service, so kept as a plain indexed string (no cross-table FK).
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Reporting period as an ISO year-month, e.g. "2026-06".
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    target: Mapped[str | None] = mapped_column(Numeric(18, 4), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EsgEntry {self.metric_key} {self.period}={self.value}>"
