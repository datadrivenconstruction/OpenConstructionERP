# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost item ORM models.

Tables:
    oe_costs_item - cost database entries (CWICR, regional indices, custom)
    oe_costs_catalog - user-owned named cost catalogs (manual or imported)
    oe_regional_indices - region × category cost-factor matrix (v3.12.0)
    oe_cost_item_usage - append-only usage ledger backing the certainty
        badge (v3.12.0)
    oe_resource_price - per-region resource price sheet
    oe_costs_base_state - active market and text language per loaded base
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
    """A single cost database entry (rate, unit price, assembly component)."""

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
    # Money is stored as a string so JSON's float bridge cannot round a rate:
    # see the DecimalMoney note in schemas.py. This comment used to give SQLite
    # compatibility as the reason. SQLite left in v6.6.0 and the reason left with
    # it, while the decision stayed correct for the other one.
    rate: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="cwicr", index=True
    )  # cwicr, commercial, benchmark, custom
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
    # ── Mass-based (per-tonne / per-kg) pricing for structural members ────
    # A steel section (e.g. a "360UB" universal beam) is priced by mass:
    # its linear mass (kg per metre) times its length gives a mass, and the
    # rate is quoted per tonne (or per kg). To support that on a normal
    # length-based BOQ line WITHOUT a second unit system, an item keeps its
    # length ``unit`` (m / lm) and its ``rate`` is interpreted as the
    # mass-basis rate when ``mass_basis`` is set:
    #   * ``mass_per_unit`` - linear mass in kg per ONE ``unit`` (e.g. 44.7
    #     for a 360UB at 44.7 kg/m). Stored as a Decimal-string for the same
    #     JSON precision reason as ``rate``. Empty / NULL = not set.
    #   * ``mass_basis`` - the denominator the ``rate`` is quoted against:
    #     ``"t"`` (rate is per tonne) or ``"kg"`` (rate is per kg). An empty
    #     string means mass pricing is OFF and the item behaves exactly as a
    #     normal per-unit rate (full backwards compatibility).
    # The effective per-length rate is then
    #   ``mass_per_unit * rate / (1000 if mass_basis == "t" else 1)``
    # computed at apply time (see ``service.mass_effective_unit_rate``); the
    # stored ``rate`` is never mutated. Both columns are additive and
    # default to empty so every existing row is unaffected.
    mass_per_unit: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    mass_basis: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # ── Price-date freshness (re-price-due flag) ──────────────────────────
    # The day this item's ``rate`` was last set or verified. This is a
    # DIFFERENT signal from the usage-ledger recency behind the certainty
    # badge: a rate can be applied constantly yet still carry a unit price
    # that was fixed years ago. Recording the price date lets the platform
    # flag an item "re-price due" once the date ages past a configurable
    # staleness horizon, regardless of how often it is used (see
    # ``service.price_freshness``). NULL means no price date is on record -
    # read as "unknown", never as fresh - so every existing row is
    # unaffected. Stored as a plain ``Date``: a price is verified on a day,
    # not at a second.
    price_as_of: Mapped[date | None] = mapped_column(Date(), nullable=True)
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
    """A user-owned, named cost catalog ("my catalog of works and rates").

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
    """Regional cost-factor row (region × category × effective_date).

    Backs ``GET /v1/costs/regional-adjust`` - given a base rate, the
    service multiplies by ``factor`` to estimate the same line item's
    cost in a different region (a regional city cost index).

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
    """Append-only usage ledger for a single ``CostItem``.

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


class ResourcePrice(Base):
    """A per-region unit price for one resource (labour, material, machine).

    Backs the resource price sheet that makes coefficient bases calculable
    locally. Bases such as Vietnam Dinh Muc or Indonesia AHSP ship the full
    labour / material / machine breakdown as norm quantities but carry NO
    prices (they are priced regionally), so a work item's rate cannot be
    computed until someone supplies local resource prices. This table holds one
    editable price per resource per region; a work item's rate is then
    ``sum(component.quantity x unit_price)`` over its components.

    Priced bases seed their observed unit prices here on import
    (``source = cwicr_import``); a user edits any row (``source = user``) and
    re-prices the region. Codeless bases (no ``resource_code``) key on
    ``resource_key`` = a normalized resource name, so the sheet works uniformly
    for coded and codeless bases. ``unit_price`` is a Decimal-as-string like
    every other money column in the schema, for the JSON precision reason
    given on ``CostItem.rate``.
    """

    __tablename__ = "oe_resource_price"
    __table_args__ = (
        UniqueConstraint("region", "resource_key", name="uq_oe_resource_price_region_key"),
        Index("ix_oe_resource_price_region_active", "region", "is_active"),
    )

    region: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # ``resource_code`` when the base carries one, else a normalized name key.
    resource_key: Mapped[str] = mapped_column(String(300), nullable=False)
    resource_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    resource_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # labor | material | equipment | operator | electricity | other
    resource_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="material", server_default="material"
    )
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="", server_default="")
    # Decimal-as-string (see CostItem.rate). "0" means unpriced (the default for
    # coefficient bases until a user fills it in).
    unit_price: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    effective_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    # cwicr_import (seeded from the base) | user (hand-edited) | regional
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="cwicr_import", server_default="cwicr_import"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<ResourcePrice {self.region}/{self.resource_key} = {self.unit_price} {self.currency}>"


class CostBaseState(Base):
    """Which market and language a loaded cost base's rows are in right now.

    One row per base region. A national base can be priced into another market
    (``/base-market``) and its work-item text switched to another language, and
    both changes rewrite the shared ``oe_costs_item`` rows of that region for
    every user on the deployment. This record is what remembers the result, so
    a restart, a second worker or another browser reads the same answer the
    rows hold. It used to live in a process-local dict and in browser storage,
    and both forgot it.

    ``active_market`` is the market token the base is priced into, or ``None``
    for the base's own home market. ``text_language`` is the language the rows
    are in, or ``None`` when that is not known: a switch that was interrupted,
    or a base loaded before this record existed. ``switching_to`` is set while
    a market switch or a return to the home market runs and cleared when it
    finishes, so a switch that died half way is reported, not hidden.
    """

    __tablename__ = "oe_costs_base_state"
    __table_args__ = (UniqueConstraint("region", name="uq_oe_costs_base_state_region"),)

    region: Mapped[str] = mapped_column(String(100), nullable=False)
    text_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    active_market: Mapped[str | None] = mapped_column(String(100), nullable=True)
    switching_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CostBaseState {self.region} market={self.active_market or 'home'} "
            f"text={self.text_language} switching_to={self.switching_to}>"
        )
