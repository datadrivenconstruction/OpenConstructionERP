# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost item Pydantic schemas for request/response validation."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    field_validator,
    model_validator,
)

from app.modules.costs.buildup import buildup_rate as _buildup_rate
from app.modules.costs.hazards import hazards_in as _hazards_in
from app.modules.costs.region_currency import REGION_CURRENCY

# Round-7 audit (2026-05-24): money / rate / factor fields are exchanged as
# strings on the wire so JSON's float bridge never silently rounds a
# precision-critical value (see the architecture guide "Money is Decimal not Float
# (v3 §10 ban)"). Inputs accept any JSON number or numeric string;
# Pydantic v2 promotes them to ``Decimal`` automatically. Outputs are
# emitted as strings so a 199.99 rate doesn't become 199.98999999...
# downstream in a JS client.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]

logger = logging.getLogger(__name__)

# Canonical CWICR region shape - ``<2-3 letter country>_<UPPERCASE city>``.
# Anything else is junk / a typo and we log a warning rather than silently
# resolving it to EUR.
_REGION_FORMAT_RE = re.compile(r"^[A-Z]{2,3}_[A-Z0-9]+$")

# CWICR ingestion historically stored currency as an empty string because the
# parquet files don't carry a currency column. We resolve the right ISO 4217
# code from the region at response time so legacy rows behave correctly
# without forcing a re-import.
#
# This binds the SAME object the write path uses (see
# :mod:`app.modules.costs.region_currency`), not a second copy of the same
# construction. The two were previously built independently and kept in step by
# a comment, which is a promise, not a mechanism: a region added to one was a
# region the other still answered "unknown" for, and the single-item read path
# then contradicted the list path on the same row.
_REGION_CURRENCY_FALLBACK: dict[str, str] = REGION_CURRENCY


# ── Mass-based pricing helpers ─────────────────────────────────────────────
#
# A structural-steel section (e.g. a "360UB" universal beam) is priced by
# mass: its linear mass (kg per metre) times its length gives a mass, and the
# rate is quoted per tonne (or per kg). ``mass_basis`` records which one; an
# empty string means mass pricing is off and the item is a plain per-unit
# rate. ``mass_per_unit`` is the linear mass in kg per one length unit.
MASS_BASES: frozenset[str] = frozenset({"t", "kg"})

# Mass per length unit is exchanged as a plain decimal *string* for the same
# precision reason as ``rate`` (stored as String(50)) - JSON's float bridge
# would otherwise round a value like 44.7 kg/m. An empty string is the "not
# set" sentinel. The schema fields type it as ``str`` and the normalisers
# below produce a clean canonical string.


def _normalize_mass_basis(value: str | None) -> str:
    """Lower-case + validate a mass basis (``t`` / ``kg`` / empty).

    Returns ``""`` for ``None`` / blank so mass pricing is treated as off.
    """
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned in ("tonne", "tonnes", "ton", "te"):
        cleaned = "t"
    if cleaned not in MASS_BASES:
        raise ValueError("mass_basis must be 't' (per tonne), 'kg' (per kg), or empty")
    return cleaned


def _normalize_mass_per_unit(value: Decimal | str | float | None) -> str:
    """Coerce a linear-mass value to a clean non-negative decimal string.

    Accepts a JSON number or numeric string. Empty / blank gives ``""`` (unset).
    A negative or non-finite mass is rejected - a section cannot weigh below
    zero, and a non-finite figure would poison the apply-time conversion.
    """
    if value is None or value == "":
        return ""
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("mass_per_unit must be a number (kg per unit)") from None
    if not dec.is_finite() or dec < 0:
        raise ValueError("mass_per_unit must be a finite, non-negative number")
    return format(dec, "f")


def _canonicalize_components(components: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Move a recipe component's ``factor`` onto the canonical ``quantity``.

    ``quantity`` is what every reader of ``CostItem.components`` looks for, and
    what the CWICR ingest writes. ``factor`` is the assemblies module's word for
    the same idea, and the import guide and the shipped recipe template asked
    for it up to 16.2.0, so files written against that documentation are out
    there. We keep reading them, but we stop storing them that way: the alias is
    resolved here, once, on the way in, so no reader downstream has to know
    about it.

    ``factor`` is left in place alongside the ``quantity`` it filled in. The
    component dict is the caller's own shape and dropping a key they sent is a
    second surprise; a duplicate is harmless because every reader prefers
    ``quantity``.

    Args:
        components: The submitted component list, or ``None``.

    Returns:
        The list with ``quantity`` filled in wherever only ``factor`` was given.

    Raises:
        ValueError: When a component carries both keys with different values.
            A half-migrated file is exactly where a silent precedence rule turns
            into the next wrong number, so it is refused rather than resolved.
    """
    if not components:
        return components
    for index, comp in enumerate(components):
        if not isinstance(comp, dict) or "factor" not in comp:
            continue
        factor = comp["factor"]
        quantity = comp.get("quantity")
        if quantity is None or quantity == "":
            comp["quantity"] = factor
            continue
        try:
            same = Decimal(str(quantity)) == Decimal(str(factor))
        except (InvalidOperation, ValueError, TypeError):
            same = str(quantity) == str(factor)
        if not same:
            raise ValueError(
                f"component[{index}] carries both 'quantity' ({quantity}) and 'factor' ({factor}) "
                f"with different values; 'factor' is a legacy alias for 'quantity', so drop one"
            )
    return components


# ── Create / Update ───────────────────────────────────────────────────────


class CostItemCreate(BaseModel):
    """Create a new cost item."""

    code: str = Field(..., min_length=1, max_length=100, description="Unique cost item code / rate code")
    description: str = Field(default="", description="Cost item description text")
    descriptions: dict[str, str] = Field(
        default_factory=dict,
        description='Localized descriptions keyed by locale (e.g. {"en": "...", "de": "..."})',
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement (m, m2, m3, kg, pcs, hr, etc.)",
    )
    rate: DecimalMoney = Field(..., ge=0, description="Unit rate (must be >= 0)")
    currency: str = Field(default="", max_length=10, description="ISO 4217 currency code (empty when unknown)")
    source: str = Field(default="cwicr", max_length=50, description="Data source (e.g. cwicr, manual)")
    classification: dict[str, str] = Field(
        default_factory=dict,
        description='Classification codes (e.g. {"din276": "330", "masterformat": "03 30 00"})',
    )
    components: list[dict[str, Any]] = Field(
        default_factory=list, description="Assembly components (labor, material, equipment breakdown)"
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    region: str | None = Field(default=None, max_length=50, description="Regional identifier (e.g. DACH, UK, US)")
    mass_per_unit: str = Field(
        default="",
        description=(
            "Linear mass in kg per one ``unit`` (e.g. 44.7 for a 360UB at "
            "44.7 kg/m). Combined with ``mass_basis`` to price a section by "
            "mass on a length line. Empty = mass pricing off."
        ),
    )
    mass_basis: str = Field(
        default="",
        max_length=10,
        description="Rate basis for mass pricing: 't' (per tonne), 'kg' (per kg), or empty (off).",
    )
    catalog_id: UUID | None = Field(
        default=None,
        description=(
            "Owning user catalog. When set and ``currency`` is empty, the item "
            "inherits the catalog currency at creation time."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")

    @field_validator("mass_basis")
    @classmethod
    def _validate_mass_basis(cls, v: str) -> str:
        return _normalize_mass_basis(v)

    @field_validator("mass_per_unit", mode="before")
    @classmethod
    def _validate_mass_per_unit(cls, v: Decimal | str | float | None) -> str:
        return _normalize_mass_per_unit(v)

    @field_validator("components")
    @classmethod
    def _canonicalize_components(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _canonicalize_components(v) or []


class CostItemUpdate(BaseModel):
    """Update a cost item (all fields optional)."""

    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None)
    descriptions: dict[str, str] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    rate: DecimalMoney | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, max_length=50)
    classification: dict[str, str] | None = None
    components: list[dict[str, Any]] | None = None
    region: str | None = Field(default=None, max_length=50)
    mass_per_unit: str | None = Field(default=None, description="Linear mass kg per unit; '' clears it.")
    mass_basis: str | None = Field(default=None, max_length=10, description="'t' | 'kg' | '' (off).")
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("mass_basis")
    @classmethod
    def _validate_mass_basis(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_mass_basis(v)

    @field_validator("mass_per_unit", mode="before")
    @classmethod
    def _validate_mass_per_unit(cls, v: Decimal | str | float | None) -> str | None:
        if v is None:
            return None
        return _normalize_mass_per_unit(v)

    @field_validator("components")
    @classmethod
    def _canonicalize_components(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _canonicalize_components(v)


# ── Response ───────────────────────────────────────────────────────────


class CostItemResponse(BaseModel):
    """Cost item in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    description: str
    descriptions: dict[str, str]
    unit: str
    # Round-7: money serialised as string. CostItem.rate is stored as
    # String(50) in the model (SQLite Decimal compat), so we accept any
    # numeric-coercible value at validate time and emit a string in
    # responses - JSON clients then parse with their own BigDecimal /
    # Decimal libraries without going through float.
    rate: DecimalMoney
    currency: str
    source: str
    classification: dict[str, str]
    components: list[dict[str, Any]]
    tags: list[str]
    region: str | None
    # Mass-based pricing (structural members). ``mass_basis`` empty = off.
    # ``mass_per_unit`` is a Decimal-string (kg per unit) or "" when unset.
    mass_per_unit: str = ""
    mass_basis: str = ""
    catalog_id: UUID | None = None
    is_active: bool
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def buildup_rate(self) -> str | None:
        """The unit rate a bill line receives when this item is added.

        The catalogue ``rate`` and the sum of the item's components are two
        figures in the source data. The add flow prices the line from its
        components, so a picker that shows only ``rate`` promises one price and
        delivers another. ``None`` when the item has no components (it is added
        at ``rate``) or has a variant slot (the rate follows the variant
        picked). Decimal-string, like ``rate``.
        """
        value = _buildup_rate(self.components, self.metadata)
        return None if value is None else str(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hazards(self) -> list[str]:
        """Hazardous materials the item is made of, as ids (``["asbestos"]``).

        Read from the description in every language the row carries, against
        the terms in ``hazard_terms.json``. The picker shows a warning badge
        for each; an empty list means none was recognised, not a guarantee.
        """
        return _hazards_in([self.description, *self.descriptions.values()])

    @model_validator(mode="after")
    def _resolve_currency_from_region(self) -> CostItemResponse:
        """Backfill currency from region for legacy CWICR rows.

        Pre-v2.6.30 imports stored ``currency = ''`` because the parquet
        source doesn't carry the column. Without this, the BOQ apply path
        falls back to ``USD`` and every RU/RO/UK rate is mislabeled. This
        validator runs once per response (read-side), so existing rows
        surface the right ISO 4217 code without a backfill migration.

        Logs a warning when the region is malformed or unknown so the
        offending row can be tracked down - the route handler picks the
        same warning up via ``_resolve_currency()`` to surface it on the
        API response for the FE toast.
        """
        if (not self.currency or not self.currency.strip()) and self.region:
            normalized = self.region.strip().upper()
            if not _REGION_FORMAT_RE.match(normalized):
                logger.warning(
                    "Cost row uses non-canonical region tag %r (expected ``XX_CITY``); currency falls back to EUR.",
                    normalized,
                )
            else:
                mapped = _REGION_CURRENCY_FALLBACK.get(normalized)
                if mapped:
                    # Bypass strict-frozen guard via __dict__ - the model is
                    # mutable by default, but we go direct to skip any future
                    # ConfigDict(frozen=True) regression.
                    self.__dict__["currency"] = mapped
                else:
                    logger.warning(
                        "Unknown region %r - no entry in _REGION_CURRENCY_FALLBACK; currency falls back to EUR.",
                        normalized,
                    )
        return self


# ── Mass apply preview ──────────────────────────────────────────────────


class MassApplyPreviewResponse(BaseModel):
    """Preview of applying a cost item to a length quantity (mass-aware).

    Returned by ``POST /v1/costs/{id}/apply-preview``. For a mass-priced
    section the ``effective_unit_rate`` is the catalog rate converted to a
    per-length figure (``mass_per_unit * rate / 1000`` when priced per
    tonne); ``total_mass_kg`` / ``total_mass_t`` show the derived mass for
    ``quantity`` units. For a plain item ``mass_priced`` is ``False`` and the
    effective rate equals the catalog rate. All money / mass figures are
    Decimal-as-string so a JS client never rounds through float.
    """

    cost_item_id: str
    code: str
    unit: str
    quantity: DecimalMoney
    mass_priced: bool
    mass_basis: str = ""
    mass_per_unit: str = ""
    base_rate: DecimalMoney
    effective_unit_rate: DecimalMoney
    total_mass_kg: DecimalMoney | None = None
    total_mass_t: DecimalMoney | None = None
    line_total: DecimalMoney
    currency: str = ""


# ── User cost catalogs ────────────────────────────────────────────────────

# 3-letter ISO 4217 currency code, normalised to UPPERCASE on input.
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _normalize_currency_code(value: str) -> str:
    """Uppercase and validate a 3-letter ISO 4217 currency code."""
    cleaned = (value or "").strip().upper()
    if not _CURRENCY_CODE_RE.match(cleaned):
        raise ValueError("currency must be a 3-letter ISO 4217 code (e.g. EUR, USD)")
    return cleaned


class CostCatalogCreate(BaseModel):
    """Create a user-owned cost catalog. Currency is REQUIRED."""

    name: str = Field(..., min_length=1, max_length=255, description="Catalog display name")
    description: str | None = Field(default=None, description="Optional free-text description")
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code every item in this catalog defaults to",
    )

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, v: str) -> str:
        return _normalize_currency_code(v)


class CostCatalogUpdate(BaseModel):
    """Update a cost catalog (all fields optional).

    A currency change is rejected by the service when the catalog already
    has items - silently re-labelling existing rates would corrupt them.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_currency_code(v)


class CostCatalogResponse(BaseModel):
    """Cost catalog in API responses, including its live item count."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    currency: str
    source: str
    created_by: UUID | None
    item_count: int = 0
    created_at: datetime
    updated_at: datetime


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
    rate: DecimalMoney
    # ISO 4217 currency. Non-optional for the frontend's apply path -
    # callers stamp it onto the BOQ resource entry so each rate keeps its
    # native currency instead of silently coercing to the BOQ base.
    currency: str = "EUR"
    region: str | None = Field(
        default=None,
        description="Region tag (e.g. DE_BERLIN). Forwarded so the tooltip can label the rate.",
    )
    classification: dict[str, str]
    components: list[dict[str, Any]] = Field(default_factory=list)
    cost_breakdown: dict[str, DecimalMoney] | None = Field(
        default=None,
        description=(
            "Optional labor / material / equipment split (in the catalog's "
            "native currency). Populated from CostItem.metadata when the "
            "source row carries CWICR's ``cost_of_working_hours`` / "
            "``total_value_machinery_equipment`` / "
            "``total_material_cost_per_position`` columns. Absent when the "
            "row has no breakdown - the tooltip then hides the breakdown "
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

    q: str | None = Field(
        default=None,
        description=(
            "Free-text search - matches substring (ILIKE) against code OR "
            "description. Canonical param. Aliases ``search`` and ``query`` "
            "are silently mapped to this at the API boundary."
        ),
    )
    name: str | None = Field(
        default=None,
        description="Substring filter against code only (the catalog 'name').",
    )
    description: str | None = Field(
        default=None,
        description="Substring filter against description only.",
    )
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
    catalog_id: UUID | None = Field(
        default=None,
        description="Filter to items in one user-owned cost catalog (exact match).",
    )
    min_rate: Decimal | None = Field(default=None, ge=0)
    max_rate: Decimal | None = Field(default=None, ge=0)
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
    fuzzy: bool = Field(
        default=True,
        description=(
            "Enable typo- and word-order-tolerant fuzzy ranking for ``q`` using "
            "PostgreSQL trigram similarity (pg_trgm): exact and prefix hits rank "
            "first, then trigram similarity. Falls back automatically to plain "
            "substring (ILIKE) matching when pg_trgm is unavailable, when ``q`` is "
            "empty, or on a non-PostgreSQL backend, so results never regress "
            "below the legacy substring behaviour. Set false to force the legacy "
            "substring path."
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
        - When the caller DOES send ``cursor``, ``total`` is ``None`` -
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
        description="Total row count - only populated on the FIRST page (no cursor).",
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
            "for this depth - frontends localize this key."
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
    unit_rate: DecimalMoney | str = Field(..., description="Unit rate (Decimal-string if parseable, else raw string)")
    classification: dict[str, str] = Field(
        default_factory=dict,
        description="Classification codes forwarded from the CostItem",
    )
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score 0..1 (higher = better)")
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

    The matcher is intentionally permissive on input - empty / whitespace
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
    top_k: int = Field(default=10, ge=1, le=50, description="Maximum number of matches to return")
    mode: str = Field(
        default="lexical",
        description="Matcher mode: lexical | semantic | hybrid",
    )
    region: str | None = Field(default=None, max_length=50, description="Restrict to a single region")


class CwicrMatchFromPositionRequest(BaseModel):
    """Request body for ``POST /costs/match-from-position``."""

    position_id: UUID = Field(..., description="UUID of the BOQ Position to match against")
    top_k: int = Field(default=10, ge=1, le=50)
    mode: str = Field(default="lexical")
    lang: str | None = Field(default=None, max_length=10)
    region: str | None = Field(default=None, max_length=50)


# ── Cost Intelligence (v3.12.0 - Stream B) ────────────────────────────────


# Six high-level categories the v3.12.0 regional matrix supports. Extra
# categories may exist in third-party data feeds (escalation feeds in
# v3.13.0); the API accepts any string but the UI exposes this list.
RegionalCategory = Literal[
    "concrete",
    "steel",
    "labor",
    "mep",
    "finishes",
    "sitework",
]


class RegionalIndexResponse(BaseModel):
    """A single regional cost-factor row as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    region_code: str
    category: str
    subcategory: str | None
    factor: DecimalMoney
    source: str
    effective_date: date
    created_at: datetime
    updated_at: datetime


class RegionalAdjustResponse(BaseModel):
    """Adjusted unit-rate preview for ``GET /v1/costs/regional-adjust``.

    Returns the same shape whether or not a matching index row exists -
    when no row is found ``factor_applied`` is ``1.0`` and ``source`` is
    ``"baseline"``, so the frontend can render the value without
    branching on null. The estimator still sees ``adjusted_rate ==
    base_rate`` which is the correct interpretation of "no adjustment
    on file".
    """

    region: str = Field(..., description="Echoed region code (uppercased)")
    category: str = Field(..., description="Echoed category key")
    base_rate: DecimalMoney = Field(..., ge=0)
    factor_applied: DecimalMoney = Field(..., gt=0)
    adjusted_rate: DecimalMoney = Field(..., ge=0)
    source: str
    effective_date: date | None = Field(
        default=None,
        description=("Date of the index row used. ``None`` when no row matched and the baseline factor was applied."),
    )


class CertaintyBadge(BaseModel):
    """Output of ``GET /v1/costs/{id}/certainty``.

    Drives the green / yellow / red dot rendered next to a cost item in
    the BOQ rate picker. Thresholds (see ``service.compute_certainty``):

    * green  - ``frequency >= 10`` AND ``age_days < 365``
    * yellow - ``frequency in [3, 9]`` OR ``age_days in [365, 1095]``
    * red    - everything else (rarely used or very stale)
    """

    cost_item_id: UUID
    frequency: int = Field(..., ge=0, description="Total recorded uses across all projects.")
    age_days: int = Field(
        ...,
        ge=0,
        description=(
            "Days since the most recent recorded use. ``999999`` when "
            "the item has never been used - that's the red threshold."
        ),
    )
    source: str = Field(..., description="Underlying CostItem.source (cwicr, manual, …)")
    confidence_badge: Literal["green", "yellow", "red"]
    last_used_at: datetime | None = Field(
        default=None,
        description="ISO-8601 timestamp of the most recent use; None when never used.",
    )

    # ── Price-date freshness (merged from ``service.price_freshness``) ──────
    # All optional so a rate that carries no ``price_as_of`` keeps the original
    # usage-only badge shape. ``reprice_due`` and the band are computed purely
    # from the price date and the horizon, never from usage frequency, so a
    # heavily-used but long-unpriced rate is still flagged as stale.
    price_as_of: date | None = Field(
        default=None,
        description="Day the rate's price was last set or verified; None when unknown.",
    )
    price_age_days: int | None = Field(
        default=None,
        description="Whole days since price_as_of; None when there is no price date.",
    )
    reprice_due: bool = Field(
        default=False,
        description="True when the price has aged at or past the staleness horizon.",
    )
    price_freshness_band: Literal["green", "yellow", "red"] | None = Field(
        default=None,
        description="Green/yellow/red by price age; None when there is no price date.",
    )
    staleness_horizon_days: int | None = Field(
        default=None,
        description="The re-price-due horizon in days that was applied.",
    )
    suggested_reprice_value: DecimalMoney | None = Field(
        default=None,
        description="Escalated one-click reprice value; set only when reprice_due.",
    )


class RecordUsageRequest(BaseModel):
    """Request body for ``POST /v1/costs/{id}/record-usage``.

    Called from the BOQ apply-rate path so the certainty badge for the
    next user of the same rate reflects up-to-date frequency. The body
    is intentionally small - the cost-item id is in the URL and the
    timestamp is server-stamped.
    """

    project_id: UUID
    context: Literal["boq", "assembly", "tender"] = "boq"
    unit_rate_at_use: DecimalMoney = Field(..., ge=0, description="Rate as it was at the moment of apply.")


# ── Cost benchmarks: own-portfolio distribution (Cost Benchmarks Phase 2) ──


class BenchmarkRequest(BaseModel):
    """Request body for ``POST /v1/costs/benchmark/``.

    Positions a user's cost-per-m2 figure against the tenant's OWN real
    projects. Every field is optional: with no filters the endpoint
    returns the distribution across all of the tenant's projects that
    carry both a cost (BOQ grand total) and a recorded gross floor area.
    The industry reference numbers are owned by the client (it holds the
    richer static benchmark table); this endpoint only adds what the
    client cannot compute - the user's own portfolio.
    """

    building_type: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional building type filter, matched against "
            "``Project.project_type`` (case-insensitive). When set, only "
            "projects of that type contribute to the distribution."
        ),
    )
    region: str | None = Field(
        default=None,
        max_length=64,
        description="Optional region filter, matched against ``Project.region``.",
    )
    currency: str | None = Field(
        default=None,
        max_length=10,
        description=(
            "Optional currency to scope the distribution to. The endpoint "
            "never blends currencies: when set, only same-currency projects "
            "are included. When omitted, the dominant project currency in "
            "the filtered set is used and reported back."
        ),
    )
    cost_per_m2: DecimalMoney | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional value to position against the portfolio, read in the unit "
            "of the selected metric (a cost per m2, an overrun fraction or a "
            "recovery rate). When supplied, the response carries "
            "``percentile_vs_own``."
        ),
    )
    metric: Literal["cost_per_m2", "overrun_pct", "recovery_rate"] = Field(
        default="cost_per_m2",
        description=(
            "Which figure to benchmark across the tenant's own projects. "
            "``cost_per_m2`` (default) is the BOQ grand total over gross floor "
            "area, currency-scoped. ``overrun_pct`` is each project's priced "
            "scope over its approved budget, and ``recovery_rate`` its recovered "
            "share of chargeable cost; both are dimensionless fractions compared "
            "across currencies and reported with an empty currency."
        ),
    )


class OwnPortfolio(BaseModel):
    """The tenant's own distribution of the requested benchmark metric.

    All figures are emitted as decimal strings per the money rule so a JS client
    never rounds a precision-critical value through Number. For the ratio
    metrics (overrun_pct / recovery_rate) the five points are dimensionless
    fractions rather than money.
    """

    project_count: int = Field(..., ge=0, description="Projects with both a cost and an area in the filtered set.")
    min: DecimalMoney
    p25: DecimalMoney
    median: DecimalMoney
    p75: DecimalMoney
    max: DecimalMoney
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description="Confidence in the distribution, derived from the project count.",
    )
    note: str = Field(
        ..., description="Plain-language basis line, e.g. 'Based on 7 of your projects with cost and area.'"
    )
    note_code: Literal["", "cost_and_area", "budget_and_boq", "recovery_ledger"] = Field(
        default="",
        description=(
            "Which basis line ``note`` states, as a stable token the client can "
            "translate. ``note`` itself is English only and cannot be localized, "
            "since it is built here and rendered as it arrives. Pair this with "
            "``project_count`` for the plural form."
        ),
    )


class BenchmarkResponse(BaseModel):
    """Response for ``POST /v1/costs/benchmark/``.

    ``own_portfolio`` and ``percentile_vs_own`` are null when the tenant
    has no usable projects (none with both a cost and an area), in which
    case the client falls back to industry-only output. The endpoint still
    returns 200 in that case - an empty portfolio is an honest state, not
    an error.
    """

    currency: str = Field(
        default="",
        description=(
            "Currency the portfolio distribution is denominated in. Empty when "
            "no portfolio, and always empty for the dimensionless ratio metrics."
        ),
    )
    metric: str = Field(
        default="cost_per_m2",
        description="The metric the distribution reports: cost_per_m2 / overrun_pct / recovery_rate.",
    )
    own_portfolio: OwnPortfolio | None = None
    percentile_vs_own: float | None = Field(
        default=None,
        description="Where the user value sits in the own-portfolio distribution (0-100). Null when no portfolio.",
    )
    explanation: str = Field(
        default="",
        description="Short plain-language reading of the position, e.g. 'Your value sits below your own portfolio median.'",
    )
    explanation_code: Literal["", "below_median", "above_median", "at_median", "specify_currency"] = Field(
        default="",
        description=(
            "Which reading ``explanation`` states, as a stable token the client "
            "can translate. ``explanation`` stays for any consumer already "
            "reading it, but it is English only. ``specify_currency`` names the "
            "currency in ``currency`` on this same response."
        ),
    )


# ── Resource price sheet (v3.187 - makes coefficient bases calculable) ─────────


class ResourcePriceRow(BaseModel):
    """One resource's unit price for a region (a row in the price sheet)."""

    model_config = ConfigDict(from_attributes=True)

    resource_key: str = Field(..., description="Stable per-region resource identity (code, or name: prefix).")
    resource_code: str = Field(default="", description="Resource code when the base carries one, else empty.")
    resource_name: str = Field(..., description="Human-readable resource name.")
    resource_type: str = Field(
        default="material",
        description="labor | material | equipment | operator | electricity | other.",
    )
    unit: str = Field(default="", description="Unit the price is per (e.g. m3, kg, hour).")
    unit_price: DecimalMoney = Field(..., ge=0, description="Local unit price. 0 means unpriced.")
    currency: str = Field(default="", description="ISO 4217 currency of the price.")
    source: str = Field(default="cwicr_import", description="cwicr_import (seeded) | user (edited).")
    is_active: bool = True


class ResourcePriceStats(BaseModel):
    """Coverage of a region's price sheet."""

    region: str
    resources: int = Field(..., ge=0, description="Distinct resources on the sheet.")
    priced: int = Field(..., ge=0, description="Resources with a non-zero price.")
    unpriced: int = Field(..., ge=0, description="Resources still at 0 (need a local price).")
    coverage: float = Field(..., ge=0, le=1, description="priced / resources.")


class ResourcePriceListResponse(BaseModel):
    """Paginated price-sheet rows plus region coverage stats."""

    region: str
    total: int = Field(..., ge=0, description="Rows matching the filter, before pagination.")
    limit: int
    offset: int
    stats: ResourcePriceStats
    rows: list[ResourcePriceRow]


class ResourcePriceSetRequest(BaseModel):
    """Set one resource's unit price (marks the row user-edited)."""

    unit_price: DecimalMoney = Field(..., ge=0, description="New local unit price.")
    currency: str | None = Field(default=None, max_length=10)
    unit: str | None = Field(default=None, max_length=30)
    resource_name: str | None = Field(default=None, max_length=300)
    resource_type: str | None = Field(default=None, max_length=30)


class ResourcePriceBulkItem(BaseModel):
    """One edit inside a bulk price update."""

    resource_key: str = Field(..., min_length=1, max_length=300)
    unit_price: DecimalMoney = Field(..., ge=0)
    currency: str | None = Field(default=None, max_length=10)
    resource_name: str | None = Field(default=None, max_length=300)
    resource_type: str | None = Field(default=None, max_length=30)
    unit: str | None = Field(default=None, max_length=30)


class ResourcePriceBulkRequest(BaseModel):
    """Apply many price edits to a region in one transaction."""

    items: list[ResourcePriceBulkItem] = Field(..., min_length=1, max_length=5000)


class ResourceSeedResponse(BaseModel):
    """Result of seeding a region's price sheet from its work items."""

    region: str
    resources: int
    created: int
    updated: int
    priced: int
    unpriced: int
    preserved_user_edits: int
    coverage: float


class RepriceResponse(BaseModel):
    """Result of re-pricing a region's work items from its price sheet."""

    region: str
    items_total: int
    items_repriced: int
    items_changed: int
    items_fully_priced: int
    items_partially_priced: int
    items_unpriced: int
    # Items whose rate was left alone because their recipe could not be read:
    # a component carried no usable quantity, so no total was computable.
    items_unreadable: int = 0
    # Items whose rate was left alone because a fully priced recipe came to
    # nothing while the item already carried a rate.
    items_zero_total: int = 0
    coverage: float
    missing_resource_count: int
    missing_resources_sample: list[str]
    unreadable_resource_count: int = 0
    unreadable_resources_sample: list[str] = Field(default_factory=list)
    dry_run: bool
    # True when the region held more work items than one pass walks. The counts
    # above then describe the first ``items_cap`` of the region rather than the
    # region, and the rest still carries its previous rates - so a caller that
    # reads ``coverage`` has to read this first.
    items_truncated: bool = False
    #: The per-pass ceiling the counts above were collected under.
    items_cap: int = 0
