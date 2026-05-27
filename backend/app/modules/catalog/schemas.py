"""‌⁠‍Catalog resource Pydantic schemas for request/response validation.

The catalog stores **resources** — single material / labour / equipment /
operator items with one price per region. Each resource can be referenced
by many cost positions (work compositions) in the ``oe_costs_item`` table
(exposed at ``/api/v1/costs/``). The link is by ``resource_code``: a cost
position's ``components[]`` array names the resources it consumes.

The legacy field ``specifications.used_in_work_items`` is the *count* of
distinct cost positions that reference this resource — equivalent to
``usage_count``. The "work_items" name is misleading because there is no
``work_items`` entity in this codebase; cost positions are the work items.
``CatalogResourceResponse`` mirrors the value into ``used_in_cost_items``
so new integrations can use the unambiguous name. The old key stays in
``specifications`` for backwards compatibility.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py — money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── Create ────────────────────────────────────────────────────────────────


class CatalogResourceCreate(BaseModel):
    """‌⁠‍Create a new catalog resource."""

    resource_code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=500)
    resource_type: str = Field(..., min_length=1, max_length=20, description="material, equipment, labor, operator")
    category: str = Field(..., min_length=1, max_length=100)
    unit: str = Field(..., min_length=1, max_length=20)
    # v3 §10 — money is Decimal-in / Decimal-as-string out.
    base_price: Decimal = Field(..., ge=0)
    min_price: Decimal = Field(default=Decimal("0"), ge=0)
    max_price: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="EUR", max_length=10)
    source: str = Field(default="manual", max_length=50)
    region: str | None = Field(default=None, max_length=50)
    specifications: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("base_price", "min_price", "max_price", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)

    @model_validator(mode="after")
    def _check_price_band(self) -> "CatalogResourceCreate":
        """CAT-001: enforce price-band integrity.

        A resource with ``min_price > max_price`` (or ``base_price``
        outside ``[min_price, max_price]``) makes every downstream
        price-range filter and "is rate within band" check meaningless.
        This is a data-integrity invariant, not a regional/currency
        policy, so it is a hard reject.

        A band is only checked when it is *meaningful*: both ``min_price``
        and ``max_price`` must be > 0. The model defaults them to 0,
        which is the documented "no band specified" sentinel — leaving
        them at 0 keeps single-price resources (the common case) valid.
        """
        has_band = self.min_price > 0 and self.max_price > 0
        if has_band:
            if self.min_price > self.max_price:
                raise ValueError(f"min_price ({self.min_price}) must not exceed max_price ({self.max_price})")
            if not (self.min_price <= self.base_price <= self.max_price):
                raise ValueError(
                    f"base_price ({self.base_price}) must lie within "
                    f"[min_price={self.min_price}, max_price={self.max_price}]"
                )
        return self


# ── Response ──────────────────────────────────────────────────────────────


class CatalogResourceResponse(BaseModel):
    """‌⁠‍Catalog resource in API responses.

    A *resource* is one leaf input — a single material, labour, equipment,
    or operator entry with one price per region. Each resource can be
    referenced by many cost positions (``/api/v1/costs/``); the inverse
    lookup is exposed at ``/api/v1/catalog/{resource_id}/used-by/``.

    Field notes:

    * ``resource_type`` is the kind of input (``material`` / ``labor`` /
      ``equipment`` / ``operator``). A catalog resource has no inner
      material/labour breakdown because **it already is one of those**.
    * ``usage_count`` is the number of cost positions that reference this
      resource by ``resource_code``.
    * ``used_in_cost_items`` is a synonym of ``usage_count`` for
      integrations that prefer the explicit name; both are kept so old
      clients reading ``specifications.used_in_work_items`` still work.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_code: str
    name: str
    resource_type: str
    category: str
    unit: str
    # v3 §10 — money is Decimal-as-string in JSON.
    base_price: Decimal = Decimal("0")
    min_price: Decimal = Decimal("0")
    max_price: Decimal = Decimal("0")
    currency: str
    usage_count: int
    used_in_cost_items: int = Field(
        default=0,
        description=(
            "Number of cost positions that reference this resource. "
            "Synonym of `usage_count`. Replaces the misleading "
            "`specifications.used_in_work_items` field — kept there for "
            "backwards compatibility."
        ),
    )
    source: str
    region: str | None
    specifications: dict[str, Any]
    is_active: bool
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("base_price", "min_price", "max_price", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)

    @model_validator(mode="after")
    def _populate_used_in_cost_items(self) -> "CatalogResourceResponse":
        """Mirror ``specifications.used_in_work_items`` to the new field.

        The legacy CSV importer writes the count under the misleading name
        ``used_in_work_items`` inside the JSON ``specifications`` blob.
        Surface it as a top-level ``used_in_cost_items`` so API consumers
        don't have to dig into a free-form dict (or guess at the name).
        Falls back to ``usage_count`` when the spec key is absent.
        """
        if self.used_in_cost_items:
            return self
        spec_val = self.specifications.get("used_in_work_items") if self.specifications else None
        try:
            self.used_in_cost_items = int(spec_val) if spec_val is not None else self.usage_count
        except (TypeError, ValueError):
            self.used_in_cost_items = self.usage_count
        return self


# ── Search ────────────────────────────────────────────────────────────────


class CatalogSearchQuery(BaseModel):
    """Query parameters for catalog resource search."""

    q: str | None = Field(default=None, description="Text search on code and name")
    resource_type: str | None = Field(default=None, description="Filter by type: material, equipment, labor, operator")
    category: str | None = Field(default=None, description="Filter by category")
    region: str | None = Field(default=None, description="Filter by region")
    unit: str | None = Field(default=None, description="Filter by unit")
    # v3 §10 — money is Decimal-in / Decimal-as-string out. Query params
    # arrive as strings via FastAPI; Pydantic v2 coerces to Decimal.
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @field_serializer("min_price", "max_price", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class CatalogSearchResponse(BaseModel):
    """Paginated search response for catalog resources."""

    items: list[CatalogResourceResponse]
    total: int
    limit: int
    offset: int


# ── Stats ─────────────────────────────────────────────────────────────────


class CatalogTypeStat(BaseModel):
    """Count of resources by type."""

    resource_type: str
    count: int


class CatalogCategoryStat(BaseModel):
    """Count of resources by category."""

    category: str
    count: int


class CatalogStatsResponse(BaseModel):
    """Aggregated statistics for the catalog."""

    total: int
    by_type: list[CatalogTypeStat]
    by_category: list[CatalogCategoryStat]
