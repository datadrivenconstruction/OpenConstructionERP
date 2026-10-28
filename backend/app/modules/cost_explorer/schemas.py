# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost Explorer request/response schemas.

Money and quantities cross the wire as strings (the source rows store them as
Decimal-compatible strings), so a JS client parses them with its own decimal
library instead of routing a precision-critical rate through a float.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, field_validator, model_validator

# A unit price above a trillion is nonsense for construction cost data; bounding
# it stops a caller from smuggling a huge-exponent Decimal (e.g. "1E999999")
# into the pricing maths, where the multiply would overflow the Decimal context.
_MAX_ABS_PRICE = Decimal("1e12")

# ── By resources: request ───────────────────────────────────────────────────


class ResourceQuery(BaseModel):
    """One requested resource, optionally weighted.

    ``weight`` lets a caller say a resource matters more (e.g. the headline
    material) than another; it defaults to 1.0 and is floored at 0 by the
    ranking engine so it can never invert the result.
    """

    code: str = Field(..., max_length=64, description="Resource code (CatalogResource.resource_code)")
    weight: float = Field(1.0, ge=0, description="Relative importance, default 1.0")


class ByResourcesRequest(BaseModel):
    """Find priced work items that consume a given set of resources."""

    region: str | None = Field(
        None,
        description="Restrict to one price base (e.g. 'DE_BERLIN'). Omit to search all installed regions.",
    )
    resources: list[ResourceQuery] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The resources to match, best coverage and cost share first.",
    )
    sources: list[str] | None = Field(
        None,
        max_length=20,
        description="Restrict to cost-item sources (e.g. ['cwicr']). Omit for all.",
    )
    limit: int = Field(50, ge=1, le=200, description="Maximum work items to return.")


# ── By resources: response ──────────────────────────────────────────────────


class MatchedResourceOut(BaseModel):
    """A requested resource that the work item consumes, with its line figures."""

    code: str
    name: str = ""
    cost: str = ""
    quantity: str = ""


class ByResourcesMatch(BaseModel):
    """One ranked work item and why it matched."""

    cost_item_id: str
    code: str
    description: str = ""
    unit: str = ""
    rate: str = ""
    currency: str = ""
    region: str | None = None
    source: str = ""
    classification: dict = Field(default_factory=dict)
    # Scoring, all 0..1.
    score: float = 0.0
    coverage: float = 0.0
    cost_weight: float = 0.0
    # The matched resources (highlighted) and the ones the item does not use.
    matched: list[MatchedResourceOut] = Field(default_factory=list)
    missing_codes: list[str] = Field(default_factory=list)


class ByResourcesResponse(BaseModel):
    """The ranked result of a by-resources search."""

    requested_count: int
    result_count: int
    results: list[ByResourcesMatch] = Field(default_factory=list)
    # Plain-language guidance when the search returns nothing to act on.
    # ``hint`` is a ready English message; ``hint_code`` is a stable key a
    # localized UI can map to a translated string. Both are null when the
    # result needs no explanation.
    hint: str | None = None
    hint_code: str | None = None


# ── Find work: text / semantic work search ──────────────────────────────────


class FindWorkRequest(BaseModel):
    """Search priced work items by free text over code and description."""

    q: str = Field(..., min_length=1, max_length=200, description="Search text.")
    region: str | None = Field(None, description="Restrict to one price base.")
    sources: list[str] | None = Field(None, max_length=20, description="Restrict to cost-item sources.")
    limit: int = Field(30, ge=1, le=200)


class FindWorkItem(BaseModel):
    """A matched work item for the text search."""

    cost_item_id: str
    code: str
    description: str = ""
    unit: str = ""
    rate: str = ""
    currency: str = ""
    region: str | None = None
    source: str = ""
    classification: dict = Field(default_factory=dict)
    score: float = 0.0


class FindWorkResponse(BaseModel):
    """Ranked text-search result."""

    query: str
    result_count: int
    mode: str = Field("lexical", description="Ranking mode actually used (lexical when no vector backend).")
    results: list[FindWorkItem] = Field(default_factory=list)
    # Plain-language guidance shown when a search returns nothing or only weak
    # matches. ``hint`` is a ready English message; ``hint_code`` is a stable key
    # a localized UI can map to a translated string. Both are null when the top
    # results are strong and need no explanation.
    hint: str | None = None
    hint_code: str | None = None


# ── Compare across price bases ───────────────────────────────────────────────


class CompareRequest(BaseModel):
    """Find the same work item priced across every installed region.

    Give a ``code`` (the CWICR rate code, shared verbatim across regions) or a
    ``cost_item_id`` to resolve the code from. One of the two is required.
    """

    code: str | None = Field(None, max_length=64, description="Rate code shared across regions.")
    cost_item_id: str | None = Field(None, max_length=64, description="Resolve the code from this item id instead.")
    limit: int = Field(60, ge=1, le=200)

    @model_validator(mode="after")
    def _need_one(self) -> CompareRequest:
        if not (self.code or self.cost_item_id):
            raise ValueError("provide either 'code' or 'cost_item_id'")
        return self


class CompareRow(BaseModel):
    """One region's pricing of the shared work item."""

    cost_item_id: str
    code: str
    description: str = ""
    unit: str = ""
    rate: str = ""
    currency: str = ""
    region: str | None = None
    source: str = ""


class CompareResponse(BaseModel):
    """The same work item across regions.

    Currencies differ between regions, so the rows are not directly comparable
    as numbers; ``currencies`` lists what appears so the UI can flag the mix.
    """

    code: str
    unit: str = ""
    description: str = ""
    region_count: int = 0
    currencies: list[str] = Field(default_factory=list)
    rows: list[CompareRow] = Field(default_factory=list)


# ── Substitute a resource / re-price a line ──────────────────────────────────


class SubstituteRequest(BaseModel):
    """Re-price one resource line of a work item and see the effect on its rate.

    Supply ``new_unit_rate`` for an explicit price, or ``substitute_resource_code``
    to pull the price from another catalog resource. One of the two is required.
    """

    cost_item_id: str = Field(..., max_length=64, description="The work item whose rate is tested.")
    resource_code: str = Field(..., max_length=64, description="The resource line inside the item to re-price.")
    new_unit_rate: str | None = Field(None, max_length=32, description="Explicit replacement unit price.")
    substitute_resource_code: str | None = Field(
        None, max_length=64, description="Take the replacement price from this catalog resource instead."
    )

    @field_validator("new_unit_rate")
    @classmethod
    def _finite_price(cls, value: str | None) -> str | None:
        """Reject a non-numeric, non-finite, or absurdly large explicit price.

        Without this a caller could pass a huge-exponent Decimal string that
        parses fine but overflows the Decimal context inside the pricing maths.

        A blank string normalises to ``None`` (not "0") so the "provide one or
        the other" rule below still fires and the service does not silently take
        the explicit-price branch with a zero price, dropping the line.
        """
        if value is None or value.strip() == "":
            return None
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("new_unit_rate must be a number") from exc
        if not parsed.is_finite():
            raise ValueError("new_unit_rate must be a finite number")
        if abs(parsed) > _MAX_ABS_PRICE:
            raise ValueError("new_unit_rate is out of range")
        return value

    @model_validator(mode="after")
    def _need_price(self) -> SubstituteRequest:
        if self.new_unit_rate is None and not self.substitute_resource_code:
            raise ValueError("provide either 'new_unit_rate' or 'substitute_resource_code'")
        return self


class SubstituteResponse(BaseModel):
    """Outcome of re-pricing a resource line via the incremental delta."""

    cost_item_id: str
    code: str
    description: str = ""
    unit: str = ""
    currency: str = ""
    region: str | None = None

    resource_code: str
    resource_name: str = ""
    quantity: str = ""
    old_unit_rate: str = ""
    new_unit_rate: str = ""
    substitute_resource_code: str | None = None
    substitute_resource_name: str | None = None

    # Unit basis of the line vs the swapped-in resource. ``unit_mismatch`` is
    # True only when both are known and differ, so the UI can warn that the
    # kept quantity may not line up with the replacement's price basis.
    original_unit: str | None = None
    substitute_unit: str | None = None
    unit_mismatch: bool = False

    old_rate: str = ""
    new_rate: str = ""
    delta: str = ""
    delta_pct: float = 0.0
    clamped: bool = False


# ── Price intelligence for one resource ──────────────────────────────────────


class PriceStatsOut(BaseModel):
    """Spread of a resource's unit price across the rows that carry it.

    The spread is scoped to a single region (``currency``) so it never blends
    price bases in different currencies into one meaningless distribution.
    """

    count: int = 0
    min: str = "0"
    p25: str = "0"
    median: str = "0"
    p75: str = "0"
    max: str = "0"
    mean: str = "0"
    currency: str = ""


class PriceRegionRow(BaseModel):
    """One catalog row for the resource, per region."""

    region: str | None = None
    unit: str = ""
    base_price: str = ""
    min_price: str = ""
    max_price: str = ""
    currency: str = ""


class PriceUsageWork(BaseModel):
    """A work item that consumes this resource, with its in-item figures."""

    cost_item_id: str
    code: str
    description: str = ""
    region: str | None = None
    quantity: str = ""
    unit_rate: str = ""


class PriceIntelResponse(BaseModel):
    """Where a resource's price sits and which works drive its demand."""

    resource_code: str
    resource_name: str = ""
    resource_type: str = ""
    unit: str = ""
    stats: PriceStatsOut = Field(default_factory=PriceStatsOut)
    stats_region: str | None = Field(
        None,
        description="Region the single-currency price spread was computed over (the dominant one when no region was requested).",
    )
    usage_count: int = 0
    by_region: list[PriceRegionRow] = Field(default_factory=list)
    top_works: list[PriceUsageWork] = Field(default_factory=list)


# ── Reindex (admin) ─────────────────────────────────────────────────────────


class ReindexResponse(BaseModel):
    """Outcome of rebuilding the resource -> work reverse index."""

    regions: list[str] = Field(default_factory=list)
    items_scanned: int = 0
    edges_written: int = 0
    resources_seen: int = 0
