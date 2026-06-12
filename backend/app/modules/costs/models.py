"""‌⁠‍Cost item ORM models.

Tables:
    oe_costs_item - cost database entries (CWICR, RSMeans, BKI, custom)
    oe_costs_catalog - user-owned named cost catalogs (manual or imported)
    oe_regional_indices - region × category cost-factor matrix (v3.12.0)
    oe_cost_item_usage - append-only usage ledger backing the certainty
        badge (v3.12.0)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CostItem(Base):
    """‌⁠‍A single cost database entry (rate, unit price, assembly component)."""

    __tablename__ = "oe_costs_item"
    __table_args__ = (
        UniqueConstraint("code", "region", name="uq_costs_code_region"),
        # Indexes for common filter combinations in search()
        Index("ix_costs_source_region", "source", "region"),
        Index("ix_costs_is_active", "is_active"),
        # Covers the per-region keyset-paginated search hot path:
        # ``WHERE region=? AND is_active=? ORDER BY code, id LIMIT N``.
        # Without this composite the planner picks ix_costs_is_active and
        # sorts 55K rows in a temp B-tree - 6 s vs 1 ms with the index.
        Index("ix_costs_region_active_code", "region", "is_active", "code"),
        # Mirrors the above for the all-regions search ("region" filter
        # absent). The leading-column rule means ``ix_costs_region_active_code``
        # cannot satisfy ``WHERE is_active=? ORDER BY code`` without a
        # region predicate, so on a 111 k-row catalogue the planner falls
        # back to ``ix_costs_is_active`` + temp B-tree sort (15 s). With
        # this composite the same query is ~1 ms.
        Index("ix_costs_active_code", "is_active", "code"),
    )

    code: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    descriptions: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    rate: Mapped[str] = mapped_column(String(50), nullable=False)  # Stored as string for SQLite compatibility
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="cwicr", index=True
    )  # cwicr, rsmeans, bki, custom
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    components: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    region: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Owning user catalog (oe_costs_catalog.id). Kept as a bare indexed UUID
    # column (no FK constraint) following the cross-table convention used by
    # ``CostItemUsage.project_id``; detach/delete semantics live in the
    # service layer so a catalog delete can choose keep-vs-soft-delete.
    catalog_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CostItem {self.code} ({self.unit} @ {self.rate} {self.currency})>"


class CostCatalog(Base):
    """‌⁠‍A user-owned, named cost catalog ("my catalog of works and rates").

    Groups :class:`CostItem` rows under one named entity with a REQUIRED
    catalog currency. Items reference the catalog through the bare
    ``CostItem.catalog_id`` column; rows without a currency of their own
    inherit ``currency`` at ingestion time. ``source`` records how the
    catalog came to exist ("manual" via the API, "import" via file upload).
    """

    __tablename__ = "oe_costs_catalog"
    __table_args__ = (Index("ix_oe_costs_catalog_created_by", "created_by"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # "manual" | "import"
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<CostCatalog {self.name} ({self.currency})>"


class RegionalIndex(Base):
    """‌⁠‍Regional cost-factor row (region × category × effective_date).

    Backs ``GET /v1/costs/regional-adjust`` - given a base rate, the
    service multiplies by ``factor`` to estimate the same line item's
    cost in a different region (RSMeans-style city cost index).

    Multiple rows per (region_code, category) are allowed when
    ``effective_date`` differs so escalation feeds (v3.13.0) can append
    quarter-on-quarter snapshots without losing history. The lookup
    always picks the row with the largest ``effective_date`` that is
    not in the future.
    """

    __tablename__ = "oe_regional_indices"
    __table_args__ = (
        UniqueConstraint(
            "region_code",
            "category",
            "subcategory",
            "effective_date",
            name="uq_oe_regional_indices_region_cat_sub_date",
        ),
        Index(
            "ix_oe_regional_indices_region_category",
            "region_code",
            "category",
        ),
    )

    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    factor: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("1.0"))
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    effective_date: Mapped[date] = mapped_column(Date(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<RegionalIndex {self.region_code}/{self.category}"
            f"{('/' + self.subcategory) if self.subcategory else ''} ="
            f" {self.factor} as-of {self.effective_date}>"
        )


class CostItemUsage(Base):
    """‌⁠‍Append-only usage ledger for a single ``CostItem``.

    One row per "rate was applied to a BOQ position / assembly /
    tender". The certainty badge reads ``count(*) + max(used_at)`` from
    this table to grade rate freshness:

    * green  - used ≥ 10× AND last use < 365 days ago
    * yellow - used 3..9× OR last use 365..1095 days ago
    * red    - everything else (never used, or very old)

    Pure append: no updates, no deletes (CASCADE wipes rows when the
    parent cost item is deleted). Index on ``(cost_item_id,
    used_at DESC)`` matches the badge's "latest N rows" query.
    """

    __tablename__ = "oe_cost_item_usage"
    __table_args__ = (
        Index(
            "ix_oe_cost_item_usage_item_time",
            "cost_item_id",
            "used_at",
        ),
        Index("ix_oe_cost_item_usage_project_id", "project_id"),
    )

    cost_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costs_item.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    used_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    unit_rate_at_use: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    # "boq" | "assembly" | "tender"
    context: Mapped[str] = mapped_column(String(32), nullable=False, default="boq", server_default="boq")

    def __repr__(self) -> str:
        return f"<CostItemUsage item={self.cost_item_id} project={self.project_id} at={self.used_at}>"
