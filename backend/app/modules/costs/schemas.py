"""Cost item Pydantic schemas for request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# CWICR ingestion historically stored currency as an empty string because the
# parquet files don't carry a currency column. We resolve the right ISO 4217
# code from the region at response time so legacy rows behave correctly
# without forcing a re-import. Keep the keys aligned with the frontend
# REGION_MAP (UPPERCASE country prefix).
_REGION_CURRENCY_FALLBACK: dict[str, str] = {
    "DE_BERLIN": "EUR",
    "DE_MUNICH": "EUR",
    "DE_HAMBURG": "EUR",
    "AT_VIENNA": "EUR",
    "CH_ZURICH": "CHF",
    "FR_PARIS": "EUR",
    "ES_MADRID": "EUR",
    "IT_ROME": "EUR",
    "NL_AMSTERDAM": "EUR",
    "BE_BRUSSELS": "EUR",
    "PT_LISBON": "EUR",
    "PT_SAOPAULO": "BRL",
    "GB_LONDON": "GBP",
    "IE_DUBLIN": "EUR",
    "PL_WARSAW": "PLN",
    "CZ_PRAGUE": "CZK",
    "RO_BUCHAREST": "RON",
    "RU_STPETERSBURG": "RUB",
    "RU_MOSCOW": "RUB",
    "USA_USD": "USD",
    "USA_NEWYORK": "USD",
    "CA_TORONTO": "CAD",
    "ENG_TORONTO": "CAD",
    "MX_MEXICO": "MXN",
    "BR_SAOPAULO": "BRL",
    "AR_BUENOSAIRES": "ARS",
    "CN_SHANGHAI": "CNY",
    "JP_TOKYO": "JPY",
    "IN_MUMBAI": "INR",
    "AE_DUBAI": "AED",
    "SA_RIYADH": "SAR",
    "TR_ISTANBUL": "TRY",
    "AU_SYDNEY": "AUD",
    "NZ_AUCKLAND": "NZD",
    "ZA_JOHANNESBURG": "ZAR",
}

# ── Create / Update ───────────────────────────────────────────────────────


class CostItemCreate(BaseModel):
    """Create a new cost item."""

    code: str = Field(
        ..., min_length=1, max_length=100, description="Unique cost item code / rate code"
    )
    description: str = Field(default="", description="Cost item description text")
    descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Localized descriptions keyed by locale (e.g. {\"en\": \"...\", \"de\": \"...\"})",
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement (m, m2, m3, kg, pcs, hr, etc.)",
    )
    rate: float = Field(..., ge=0, description="Unit rate (must be >= 0)")
    currency: str = Field(
        default="EUR", max_length=10, description="ISO 4217 currency code"
    )
    source: str = Field(
        default="cwicr", max_length=50, description="Data source (e.g. cwicr, rsmeans, manual)"
    )
    classification: dict[str, str] = Field(
        default_factory=dict,
        description="Classification codes (e.g. {\"din276\": \"330\", \"masterformat\": \"03 30 00\"})",
    )
    components: list[dict[str, Any]] = Field(
        default_factory=list, description="Assembly components (labor, material, equipment breakdown)"
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    region: str | None = Field(
        default=None, max_length=50, description="Regional identifier (e.g. DACH, UK, US)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")


class CostItemUpdate(BaseModel):
    """Update a cost item (all fields optional)."""

    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None)
    descriptions: dict[str, str] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    rate: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, max_length=50)
    classification: dict[str, str] | None = None
    components: list[dict[str, Any]] | None = None
    region: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


# ── Response ───────────────────────────────────────────────────────────


class CostItemResponse(BaseModel):
    """Cost item in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    description: str
    descriptions: dict[str, str]
    unit: str
    rate: float
    currency: str
    source: str
    classification: dict[str, str]
    components: list[dict[str, Any]]
    tags: list[str]
    region: str | None
    is_active: bool
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _resolve_currency_from_region(self) -> CostItemResponse:
        """Backfill currency from region for legacy CWICR rows.

        Pre-v2.6.30 imports stored ``currency = ''`` because the parquet
        source doesn't carry the column. Without this, the BOQ apply path
        falls back to ``USD`` and every RU/RO/UK rate is mislabeled. This
        validator runs once per response (read-side), so existing rows
        surface the right ISO 4217 code without a backfill migration.
        """
        if (not self.currency or not self.currency.strip()) and self.region:
            mapped = _REGION_CURRENCY_FALLBACK.get(self.region.strip().upper())
            if mapped:
                # Bypass strict-frozen guard via __dict__ — the model is
                # mutable by default, but we go direct to skip any future
                # ConfigDict(frozen=True) regression.
                self.__dict__["currency"] = mapped
        return self


# ── Search ────────────────────────────────────────────────────────────────


class CostAutocompleteItem(BaseModel):
    """Compact cost item result for autocomplete dropdown.

    Phase F (v2.7.0): the response carries a slim ``cost_breakdown`` block
    (labor / material / equipment) plus the region tag and a thinned-out
    ``metadata_`` so the BOQ description-cell hover tooltip can render a
    rich preview without a second round-trip. The added bytes are bounded
    (< 200 B / item with the variant array left out) which keeps the
    autocomplete payload firmly under the lazy-fetch threshold.
    """

    code: str
    description: str
    unit: str
    rate: float
    # ISO 4217 currency. Non-optional for the frontend's apply path —
    # callers stamp it onto the BOQ resource entry so each rate keeps its
    # native currency instead of silently coercing to the BOQ base.
    currency: str = "EUR"
    region: str | None = Field(
        default=None,
        description="Region tag (e.g. DE_BERLIN). Forwarded so the tooltip can label the rate.",
    )
    classification: dict[str, str]
    components: list[dict[str, Any]] = Field(default_factory=list)
    cost_breakdown: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional labor / material / equipment split (in the catalog's "
            "native currency). Populated from CostItem.metadata when the "
            "source row carries CWICR's ``cost_of_working_hours`` / "
            "``total_value_machinery_equipment`` / "
            "``total_material_cost_per_position`` columns. Absent when the "
            "row has no breakdown — the tooltip then hides the breakdown "
            "section gracefully."
        ),
    )
    metadata_: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Slim metadata mirror (variant_stats + variant count) for the "
            "tooltip's variant indicator. The field name (with trailing "
            "underscore) matches the frontend ``CostAutocompleteItem`` "
            "contract and the wire-shape used by the paginated cost search "
            "endpoint. The full ``variants`` array is intentionally "
            "omitted to keep the payload small; callers that need it "
            "should hit ``GET /v1/costs/{id}/`` on apply."
        ),
    )


class CostSearchQuery(BaseModel):
    """Query parameters for cost item search."""

    q: str | None = Field(default=None, description="Text search on code and description")
    unit: str | None = None
    source: str | None = None
    region: str | None = Field(default=None, description="Filter by region (e.g. DE_BERLIN)")
    category: str | None = Field(default=None, description="Filter by classification.collection value")
    classification_path: str | None = Field(
        default=None,
        description=(
            "Slash-delimited classification prefix path (collection/department/"
            "section/subsection). Prefix-matches at any depth, e.g. "
            "'Buildings/Concrete' matches all rows under that branch. Empty "
            "segments in the middle act as wildcards."
        ),
    )
    min_rate: float | None = Field(default=None, ge=0)
    max_rate: float | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    cursor: str | None = Field(
        default=None,
        description=(
            "Opaque keyset-pagination cursor returned in the previous "
            "response's ``next_cursor`` field. When supplied, ``offset`` is "
            "ignored, ``total`` is omitted, and items resume after the "
            "(code, id) pair encoded in the cursor."
        ),
    )


class CostSearchResponse(BaseModel):
    """Legacy offset-paginated search response for cost items.

    Kept for any client still consuming the old shape; the live router
    returns ``CostSearchPaginatedResponse``-shaped dicts which are a
    superset of this model (extra ``next_cursor`` / ``has_more`` keys,
    ``total`` becomes optional).
    """

    items: list[CostItemResponse]
    total: int
    limit: int
    offset: int


class CostSearchPaginatedResponse(BaseModel):
    """Keyset-paginated search response.

    Backwards compatibility:
        - When the caller does NOT send ``cursor``, ``total`` is populated
          (cached for 30s by the router) so existing clients keep working.
        - When the caller DOES send ``cursor``, ``total`` is ``None`` —
          counting on every page is wasteful and the frontend doesn't
          need it after the first page.
        - ``next_cursor`` is ``None`` on the last page.
    """

    items: list[CostItemResponse]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the NEXT page; ``None`` on the last page.",
    )
    has_more: bool = Field(
        default=False,
        description="True when at least one row exists beyond this page.",
    )
    total: int | None = Field(
        default=None,
        description="Total row count — only populated on the FIRST page (no cursor).",
    )
    limit: int
    offset: int


class CategoryTreeNode(BaseModel):
    """One node in the 4-level category tree.

    The tree shape is recursive but bounded to 4 depths:
    ``collection → department → section → subsection``. The frontend
    relies on the implicit depth to label each level; the backend just
    nests them generically.
    """

    name: str = Field(
        ...,
        description=(
            "Classification segment name. Use the sentinel "
            "'__unspecified__' when the source row has a NULL/empty value "
            "for this depth — frontends localize this key."
        ),
    )
    count: int = Field(..., ge=0, description="Number of cost items under this branch.")
    children: list[CategoryTreeNode] = Field(
        default_factory=list,
        description="Child nodes; empty for leaf (subsection) nodes.",
    )


# Pydantic v2: resolve the self-reference in CategoryTreeNode.children so
# the model is fully usable as a response_model and for .model_validate().
CategoryTreeNode.model_rebuild()


# Sentinel emitted in CategoryTreeNode.name when the source row has a
# NULL / empty value for that classification depth. The frontend is
# expected to detect this string and substitute a localized label
# (e.g. "Unspecified" / "Без категории").
UNSPECIFIED_CATEGORY = "__unspecified__"


# ── BIM suggestion ────────────────────────────────────────────────────────


class CostSuggestion(BaseModel):
    """A ranked cost-item suggestion for a BIM element.

    Returned by ``POST /api/v1/costs/suggest-for-element``.  The frontend
    renders these as chips in the AddToBOQ modal so the estimator can
    one-click populate a BOQ position's unit rate.
    """

    cost_item_id: str = Field(..., description="UUID of the underlying CostItem")
    code: str = Field(..., description="CWICR rate code / cost item code")
    description: str = Field(..., description="Human-readable description")
    unit: str = Field(..., description="Unit of measurement")
    unit_rate: float | str = Field(..., description="Unit rate (numeric if parseable)")
    classification: dict[str, str] = Field(
        default_factory=dict,
        description="Classification codes forwarded from the CostItem",
    )
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Relevance score 0..1 (higher = better)"
    )
    match_reasons: list[str] = Field(
        default_factory=list,
        description="Short human-readable strings explaining why this matched",
    )


class SuggestCostsForElementRequest(BaseModel):
    """Request body for BIM-element cost suggestion endpoint."""

    element_type: str | None = None
    name: str | None = None
    discipline: str | None = None
    properties: dict[str, Any] | None = None
    quantities: dict[str, float] | None = None
    classification: dict[str, str] | None = None
    limit: int = Field(default=5, ge=1, le=50)
    region: str | None = None


# ── CWICR Matcher (T12) ───────────────────────────────────────────────────


class CwicrMatchRequest(BaseModel):
    """Request body for ``POST /costs/match``.

    The matcher is intentionally permissive on input — empty / whitespace
    queries simply produce an empty result set rather than raising 422,
    so the BOQ editor can call it on every keystroke without guards.
    """

    query: str = Field(default="", description="BOQ position description (free text)")
    unit: str | None = Field(
        default=None,
        max_length=20,
        description="Optional unit-of-measure hint (m, m2, m3, kg, pcs, ...)",
    )
    lang: str | None = Field(
        default=None,
        max_length=10,
        description="Optional language hint (ISO-639-1: en, de, ru, fr, ...)",
    )
    top_k: int = Field(
        default=10, ge=1, le=50, description="Maximum number of matches to return"
    )
    mode: str = Field(
        default="lexical",
        description="Matcher mode: lexical | semantic | hybrid",
    )
    region: str | None = Field(
        default=None, max_length=50, description="Restrict to a single region"
    )


class CwicrMatchFromPositionRequest(BaseModel):
    """Request body for ``POST /costs/match-from-position``."""

    position_id: UUID = Field(..., description="UUID of the BOQ Position to match against")
    top_k: int = Field(default=10, ge=1, le=50)
    mode: str = Field(default="lexical")
    lang: str | None = Field(default=None, max_length=10)
    region: str | None = Field(default=None, max_length=50)
