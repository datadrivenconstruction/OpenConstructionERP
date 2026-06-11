"""‌⁠‍BOQ Pydantic schemas - request/response models.

Defines create, update, and response schemas for BOQs, positions, markups,
structured (sectioned) BOQ responses, templates, and activity log entries.

Numeric values (quantity, unit_rate, total) are exposed as floats in the API
but stored as strings in SQLite-compatible models.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

# Probe-A scenario 11: hard cap on ``quantity * unit_rate``. A 1e10 × 1e10
# input would compute to 1e20, which is far beyond any plausible
# construction line item and likely indicates fat-fingered input or
# unit confusion (e.g. m³ vs mm³). Capping at 1e15 still allows
# trillion-EUR megaprojects (gas pipelines, civil works) while
# catching obvious overflow before it hits the DB. ``Decimal`` is used
# throughout so the comparison is exact, not float-approximate.
POSITION_TOTAL_CAP: Decimal = Decimal("1e15")


def _check_position_total_cap(
    quantity: float | None,
    unit_rate: float | Decimal | None,
) -> None:
    """Reject ``quantity * unit_rate`` totals beyond ``POSITION_TOTAL_CAP``.

    Raises ``ValueError`` (which Pydantic surfaces as a 422) when the
    product exceeds the cap. Either side being ``None`` means "no
    change" on update - skip the check; the existing stored value
    governs the effective total.
    """
    if quantity is None or unit_rate is None:
        return
    try:
        product = Decimal(str(quantity)) * Decimal(str(unit_rate))
    except (InvalidOperation, ValueError):
        # Bad numeric input is caught by the per-field validators; this
        # cross-field check just bails out so we don't double-report.
        return
    if product > POSITION_TOTAL_CAP:
        raise ValueError(
            "Position total exceeds reasonable limit. Check quantity and unit rate.",
        )


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Money fields are stored / accepted as ``Decimal`` but emitted as plain
# decimal *strings* in JSON. Float forces every consumer to parse a
# locale-coloured number and silently drops precision past ~15 sig figs.
# This is the canonical helper mirrored by sibling modules
# (match_elements, bim_hub) - keep them in sync.
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


def _sanitise_free_text(value: str | None) -> str | None:
    """‌⁠‍Strip XSS-dangerous HTML from free-text BOQ fields (BUG-326/389).

    BOQ names and descriptions are rendered in multiple places in the
    frontend (BOQ editor, reports, exports), some of which historically
    used ``dangerouslySetInnerHTML``. Scrubbing at the schema layer means
    the database never stores a ``<script>`` payload, regardless of
    which handler accepted the write.
    """
    if value is None:
        return value
    from app.core.sanitize import strip_dangerous_html

    return strip_dangerous_html(value)


# ── BOQ schemas ───────────────────────────────────────────────────────────────


class BOQCreate(BaseModel):
    """‌⁠‍Create a new Bill of Quantities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID = Field(..., description="UUID of the parent project")
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="BOQ name (must be at least 1 character)",
        examples=["Detailed Estimate Phase 1"],
    )
    description: str = Field(
        default="",
        max_length=5000,
        description="Optional description of the BOQ scope",
        examples=["Full BOQ for structural and architectural works"],
    )
    estimate_type: str | None = Field(
        default=None,
        max_length=50,
        description="Estimate type (e.g. detailed, budget, order_of_magnitude)",
        examples=["detailed"],
    )
    base_date: str | None = Field(
        default=None,
        max_length=20,
        description="Base date / price level reference (e.g. 2026-Q2)",
        examples=["2026-Q2"],
    )
    tax_rate: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        description="VAT / sales-tax rate as a fraction (0.19 = 19%). None = no tax line.",
        examples=["0.19"],
    )

    @field_validator("name", "description", mode="after")
    @classmethod
    def _sanitise(cls, v: str) -> str:
        return _sanitise_free_text(v) or ""


class BOQUpdate(BaseModel):
    """Partial update for a BOQ."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern=r"^(draft|final|archived)$")
    metadata: dict[str, Any] | None = None
    estimate_type: str | None = Field(default=None, max_length=50)
    base_date: str | None = Field(default=None, max_length=20)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)

    @field_validator("name", "description", mode="after")
    @classmethod
    def _sanitise(cls, v: str | None) -> str | None:
        return _sanitise_free_text(v)


class BOQResponse(BaseModel):
    """BOQ returned from the API."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_extra={"x-build": "oe-443"},
    )

    id: UUID
    project_id: UUID
    name: str
    description: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Phase 12.2 lock & revision fields
    base_date: str | None = None
    estimate_type: str | None = None
    is_locked: bool = False
    parent_estimate_id: UUID | None = None
    approved_by: str | None = None
    approved_at: str | None = None

    # BUG-MATH04: defence-in-depth strip of any residual HTML on output.
    # Input validators only block the *dangerous* subset; legacy rows
    # written before that fix may still contain ``<b>`` etc. Stripping at
    # serialisation guarantees the JSON consumer sees plain text even if
    # storage was ever compromised by a path that bypassed the input
    # validators (bulk import, raw SQL migration, etc.).
    @field_validator("name", "description", mode="after")
    @classmethod
    def _strip_html_on_response(cls, v: str) -> str:
        from app.core.sanitize import sanitise_text

        return sanitise_text(v) or ""


class BOQListItem(BOQResponse):
    """BOQ summary returned from list endpoints, includes computed grand_total.

    ``grand_total`` is the **final** number a user sees on dashboards: direct
    cost plus all active markups (and taxes when present).  ``direct_cost_total``
    breaks out the same number minus markups, so the two figures are always
    consistent across list / detail / structured endpoints (BUG-008).

    v3 §10 - money emitted as Decimal-as-string. Floats here silently
    truncated very-large totals on listing endpoints and forced every
    consumer to parse a locale-coloured number.
    """

    direct_cost_total: Decimal = Decimal("0")
    markups_total: Decimal = Decimal("0")
    tax_rate: Decimal | None = None
    tax_amount: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")
    position_count: int = 0

    @field_serializer(
        "direct_cost_total",
        "markups_total",
        "tax_rate",
        "tax_amount",
        "grand_total",
        when_used="json",
    )
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


# ── Position schemas ───────────────────────────────────────────────────────


class PositionCreate(BaseModel):
    """Create a new BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID = Field(..., description="UUID of the parent BOQ")
    parent_id: UUID | None = Field(default=None, description="Parent position UUID for hierarchical grouping")
    ordinal: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Position number / ordinal code (e.g. 01.02.003)",
        examples=["01.02.003"],
    )
    description: str = Field(
        default="",
        max_length=5000,
        description="Position description / specification text",
        examples=["Reinforced concrete wall C30/37, 24cm, formwork both sides"],
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement (m, m2, m3, kg, t, pcs, lsum, hr, etc.)",
        examples=["m3"],
    )
    # BUG-MATH02: quantity is REQUIRED on create.  Previously it defaulted to
    # 0.0, so an Excel import with a blank quantity cell silently zero-filled
    # the line and rolled up as €0 instead of being flagged as missing data.
    quantity: float = Field(..., ge=0.0, description="Measured quantity", examples=[125.5])
    # v3 §10 - money is Decimal-in / Decimal-as-string out. Pydantic v2
    # coerces int/float/str inputs to Decimal so legacy clients still work.
    unit_rate: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Price per unit",
        examples=["285.00"],
    )
    classification: dict[str, Any] = Field(
        default_factory=dict,
        description="Classification codes (e.g. din276, nrm, masterformat)",
        examples=[{"din276": "330"}],
    )
    source: str = Field(
        default="manual",
        pattern=r"^(manual|cad_import|ai_takeoff|gaeb_import|excel_import|bc3_import|takeoff|smart_import|smart_import_ai|cad_import_ai|cost_database|assembly|cwicr|enriched|ai_match)$",
        description=(
            "Data source. One of: manual, cad_import, ai_takeoff, gaeb_import, "
            "excel_import, bc3_import, takeoff, smart_import, smart_import_ai, "
            "cad_import_ai, cost_database, assembly, cwicr, enriched, ai_match."
        ),
        examples=["manual"],
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="AI confidence score (0.0-1.0). Only for AI-sourced positions",
    )
    cad_element_ids: list[str] = Field(default_factory=list, description="Linked CAD element IDs from canonical format")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    wbs_id: str | None = Field(default=None, description="Linked WBS node ID")
    cost_code_id: str | None = Field(default=None, description="Linked cost code ID")
    # Issue #79: link a BOQ position to a CostItem in the cost database
    # (CWICR / RSMeans / etc.).  Persisted in ``metadata.cost_item_id`` so
    # no schema migration is required; the service validates that the
    # supplied UUID resolves to an active CostItem before persisting.
    cost_item_id: UUID | None = Field(
        default=None,
        description=(
            "UUID of a CostItem in the cost database to link this position to "
            "(typically used together with source='cwicr'). The service "
            "validates that the referenced CostItem exists and is active."
        ),
    )
    # ── Issue #127: BOQ code reuse / linked positions ────────────────────
    reference_code: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Reusable user-facing code (Sección/Partida/Recurso, e.g. "
            "'0040'). DISTINCT from ``ordinal``: typing an existing code "
            "creates a LINKED INSTANCE that carries the master code's "
            "definition + sub-structure (it does NOT 409). The instance "
            "still gets its own unique auto-assigned ordinal and its own "
            "per-instance quantity. When omitted the service stamps a "
            "stable internal code so the position stays referenceable."
        ),
        examples=["0040"],
    )
    link_mode: Literal["link", "copy", "standalone"] | None = Field(
        default=None,
        description=(
            "Behaviour when ``reference_code`` collides with an existing "
            "code in the project. 'link' (DEFAULT on collision) = create a "
            "linked instance; master-definition edits propagate to it. "
            "'copy' = one-time clone, unlinked (no future propagation). "
            "'standalone' = ignore the collision, plain create. No "
            "collision: always a plain create."
        ),
    )
    # ── Issue #139: insert directly below the selected row ───────────────
    after_position_id: UUID | None = Field(
        default=None,
        description=(
            "Optional UUID of an existing position the new row should be "
            "placed *immediately after* (same BOQ). When set, the new "
            "position's sort_order slots right after that sibling and every "
            "later position shifts down by one - so 'Add position' inserts "
            "below the selected row instead of at the end of the section. "
            "Ignored for the reuse/linked-instance path."
        ),
    )

    # Sanitise + canonicalise; **don't** gate on a fixed catalogue.  Locale
    # spellings (Romanian "Bucat", Bulgarian "бр", Russian "шт", German
    # "Stück", CWICR multi-prefix forms like "100 EA") all round-trip
    # through ``normalise_unit`` lowercased and stripped.  Common synonyms
    # ("ton" → "t", "metre" → "m") still bucket into canonical forms so
    # aggregations stay coherent.  Only genuinely unsafe shapes (empty,
    # > 30 chars, control chars, HTML / SQL / quote characters) are
    # rejected.
    @field_validator("unit", mode="after")
    @classmethod
    def _check_unit(cls, v: str) -> str:
        from app.modules.boq.units import normalise_unit

        normalised = normalise_unit(v)
        if normalised is None:
            raise ValueError(
                f"unit '{v}' has an unsafe shape - must be 1-30 characters, "
                f"start with a letter or digit, and contain only letters, "
                f"digits, spaces, or any of '. _ - / ² ³ %'"
            )
        return normalised

    # Probe-A scenario 11 - overflow guard. Cross-field check so a
    # 1e10 × 1e10 = 1e20 input fails before it hits the DB rather than
    # silently corrupting BOQ rollups.
    @model_validator(mode="after")
    def _check_total_cap(self) -> "PositionCreate":
        _check_position_total_cap(self.quantity, self.unit_rate)
        return self

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class SectionCreate(BaseModel):
    """Create a BOQ section (header row without pricing).

    Sections are grouping rows.  They have an ordinal and description but
    no unit, quantity, or unit_rate.

    Issue #136: a section MAY now nest under another section via
    ``parent_id`` (sections-within-sections), bounded by the configurable
    ``MAX_NESTING_DEPTH`` cap. Omitting ``parent_id`` keeps the legacy
    top-level behaviour, so existing callers are unaffected.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=5000)
    parent_id: UUID | None = Field(
        default=None,
        description=("Parent section UUID for nested sections (Issue #136). None = top-level section."),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class PositionUpdate(BaseModel):
    """Partial update for a BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    ordinal: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity: float | None = Field(default=None, ge=0.0)
    # v3 §10 - money is Decimal-in / Decimal-as-string out.
    unit_rate: Decimal | None = Field(default=None, ge=0)
    classification: dict[str, Any] | None = None
    source: str | None = Field(
        default=None,
        pattern=r"^(manual|cad_import|ai_takeoff|gaeb_import|excel_import|takeoff|smart_import|smart_import_ai|cad_import_ai|cost_database|assembly|cwicr|enriched|ai_match)$",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cad_element_ids: list[str] | None = None
    validation_status: str | None = Field(
        default=None,
        pattern=r"^(pending|passed|warnings|errors)$",
    )
    metadata: dict[str, Any] | None = None
    sort_order: int | None = None
    wbs_id: str | None = None
    cost_code_id: str | None = None
    # Issue #79: optional re-linkage to a different CostItem.  Mirrors
    # PositionCreate.cost_item_id; when supplied, the service validates
    # the new target and stores the UUID under ``metadata.cost_item_id``.
    cost_item_id: UUID | None = Field(
        default=None,
        description=(
            "UUID of a CostItem to (re)link this position to. The service "
            "validates that the referenced CostItem exists and is active."
        ),
    )
    # BUG-CONCURRENCY01: optimistic concurrency token. Clients echo the
    # ``version`` they last read; the service rejects with 409 when the
    # row's current version no longer matches.
    version: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Optimistic concurrency token. If supplied and the row's current "
            "version does not match, the update is rejected with 409 Conflict."
        ),
    )
    # ── Issue #127: code reuse / linked positions ────────────────────────
    reference_code: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Change this position's reusable code. Note: editing a MASTER's "
            "definition fields propagates to every linked instance in the "
            "project; editing an INSTANCE's definition directly UNLINKS it "
            "from the group and attaches a warning (quantity edits never "
            "propagate or unlink)."
        ),
    )
    link_mode: Literal["link", "copy", "standalone"] | None = Field(
        default=None,
        description=(
            "Reserved for symmetry with PositionCreate; ignored on update (linking decisions are made at create time)."
        ),
    )

    # Mirrors PositionCreate: sanitise + canonicalise on partial updates.
    @field_validator("unit", mode="after")
    @classmethod
    def _check_unit(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.modules.boq.units import normalise_unit

        normalised = normalise_unit(v)
        if normalised is None:
            raise ValueError(
                f"unit '{v}' has an unsafe shape - must be 1-30 characters, "
                f"start with a letter or digit, and contain only letters, "
                f"digits, spaces, or any of '. _ - / ² ³ %'"
            )
        return normalised

    # Probe-A scenario 11 - overflow guard for partial updates. Only
    # fires when BOTH ``quantity`` and ``unit_rate`` are supplied in
    # the same PATCH; if only one side is updated we cannot recompute
    # without DB access. The service layer recomputes ``total`` and
    # an additional cap check there guards the partial-update path.
    @model_validator(mode="after")
    def _check_total_cap(self) -> "PositionUpdate":
        _check_position_total_cap(self.quantity, self.unit_rate)
        return self

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


# ── v3.12.0 Stream A - bulk-update + per-field restore ───────────────────────


class BulkPositionUpdate(BaseModel):
    """Atomic bulk update for a set of positions within a BOQ.

    Accepts one of three mutation styles, applied to every ``ids`` entry:

    * ``updates`` - direct field assignment (e.g. ``{"unit": "m3"}`` or
      ``{"classification": {"din276": "330"}}``). The same payload is
      written to every selected position.
    * ``rate_factor`` - multiply each row's existing ``unit_rate`` by a
      scalar (e.g. 1.05 = +5 %). Reads the row's current value, writes
      back the product. ``quantity`` and ``total`` are recomputed by
      the service.
    * ``quantity_factor`` - same as ``rate_factor`` but for ``quantity``.

    Exactly one of ``updates`` / ``rate_factor`` / ``quantity_factor``
    must be supplied. Mixing styles is rejected with 422 so the audit
    trail stays unambiguous (one log entry per row per kind).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Position UUIDs to update. All must live in the same BOQ.",
    )
    updates: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional direct-set payload. Allowed keys: 'unit', "
            "'classification', 'validation_status', 'source'. Other keys "
            "are rejected with 422."
        ),
    )
    rate_factor: float | None = Field(
        default=None,
        gt=0.0,
        le=1_000_000.0,
        description="Multiplicative factor for unit_rate (must be > 0).",
    )
    quantity_factor: float | None = Field(
        default=None,
        gt=0.0,
        le=1_000_000.0,
        description="Multiplicative factor for quantity (must be > 0).",
    )

    @model_validator(mode="after")
    def _exactly_one_mutation(self) -> "BulkPositionUpdate":
        styles = [
            self.updates is not None,
            self.rate_factor is not None,
            self.quantity_factor is not None,
        ]
        if sum(1 for s in styles if s) != 1:
            raise ValueError(
                "Exactly one of 'updates', 'rate_factor', 'quantity_factor' must be supplied.",
            )
        if isinstance(self.updates, dict):
            # Tight allowlist - bulk operations must not silently rewrite
            # quantity / unit_rate / metadata blobs (those have dedicated
            # factor paths and per-row endpoints).
            allowed = {"unit", "classification", "validation_status", "source"}
            bad = set(self.updates) - allowed
            if bad:
                raise ValueError(
                    f"updates keys not allowed in bulk mode: {sorted(bad)}. Allowed: {sorted(allowed)}.",
                )
            if not self.updates:
                raise ValueError("updates dict cannot be empty.")
        return self


class BulkUpdateResult(BaseModel):
    """Outcome of a bulk update - counts plus failed-id detail."""

    model_config = ConfigDict(from_attributes=True)

    updated: int = 0
    skipped: int = 0
    failed_ids: list[UUID] = Field(default_factory=list)
    log_id: UUID | None = Field(
        default=None,
        description="Activity-log entry id for the umbrella bulk action.",
    )


class RestoreFieldRequest(BaseModel):
    """Restore a single field on one position from a prior activity-log row.

    The server verifies that ``log_id`` references an existing
    BOQActivityLog whose ``target_id`` equals the URL's ``position_id``
    and whose ``changes`` JSON carries a record for ``field``. The
    supplied ``value`` is then written via the normal update path so
    every downstream invariant (total recompute, validation reset,
    optimistic-concurrency bump) still fires.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    field: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Position attribute to restore (e.g. 'unit_rate').",
    )
    value: Any = Field(
        default=None,
        description="Value to assign - typically the 'old' side of the log diff.",
    )
    log_id: UUID = Field(
        ...,
        description="Source BOQActivityLog id this restore is replaying.",
    )


class RestoreFieldResponse(BaseModel):
    """Echo of a successful per-field restore."""

    position_id: UUID
    field: str
    restored_value: Any
    source_log_id: UUID
    new_log_id: UUID | None = None


class PositionResponse(BaseModel):
    """Position returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    parent_id: UUID | None
    ordinal: str
    description: str
    unit: str
    # BUG-B-011: stored as 4 dp Decimal strings in the model. Typing these
    # as ``float`` truncated values past ~15 significant figures (a
    # 999,999,999.99 × 999,999.99 line lost its tail in JSON). Keep them as
    # ``Decimal`` and serialise as a plain decimal *string* so large totals
    # round-trip exactly and stay locale-neutral (per the architecture guide). Accepts
    # str / float / Decimal on input via Pydantic's Decimal coercion.
    quantity: Decimal
    unit_rate: Decimal
    total: Decimal
    classification: dict[str, Any]
    source: str
    confidence: float | None
    cad_element_ids: list[str]
    validation_status: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    sort_order: int
    created_at: datetime
    updated_at: datetime
    wbs_id: str | None = None
    cost_code_id: str | None = None
    # Issue #79: linkage to a CostItem in the cost database, surfaced from
    # ``metadata.cost_item_id`` so clients receive the same shape they sent.
    cost_item_id: UUID | None = None
    # BUG-CONCURRENCY01: monotonic per-row counter, surfaced so clients
    # can echo it back on the next PATCH for conflict detection.
    version: int = 0
    # ── Issue #127: code reuse / linked positions (read-only) ────────────
    reference_code: str | None = None
    link_role: str | None = None
    link_group_id: UUID | None = None
    # Only populated for masters: how many OTHER positions reuse this code
    # (linked instances) project-wide. None for instances / standalone.
    linked_instance_count: int | None = None

    # BUG-MATH04: response-side HTML strip. Position descriptions are the
    # most-rendered free-text field in the product (BOQ grid, exports,
    # AI-chat reuse). Even though input validators block dangerous tags,
    # the response strip is a belt-and-braces defence for any frontend
    # that mistakenly uses ``dangerouslySetInnerHTML`` on this field.
    @field_validator("description", mode="after")
    @classmethod
    def _strip_html_on_response(cls, v: str) -> str:
        from app.core.sanitize import sanitise_text

        return sanitise_text(v) or ""

    # BUG-B-011: emit money/quantity as a *plain* decimal string. ``str``
    # on a Decimal can yield scientific notation (e.g. 1E+3); the explicit
    # non-exponential format keeps the value exact, human- and
    # machine-readable, and locale-neutral (per the architecture guide). Non-finite
    # values (defensive - the write path quantises and rejects NaN/Inf)
    # collapse to "0".
    @field_serializer("quantity", "unit_rate", "total", when_used="json")
    @classmethod
    def _serialise_decimal(cls, v: Decimal) -> str:
        if not isinstance(v, Decimal):
            try:
                v = Decimal(str(v))
            except (InvalidOperation, ValueError):
                return "0"
        if not v.is_finite():
            return "0"
        return format(v, "f")


# ── Markup schemas ────────────────────────────────────────────────────────────


class _MarkupBase(BaseModel):
    """Shared serializer for ``fixed_amount`` (v3 §10 - Decimal-as-string)."""

    @field_serializer("fixed_amount", when_used="json", check_fields=False)
    def _ser_fixed_amount(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class MarkupCreate(_MarkupBase):
    """Create a markup/overhead line on a BOQ.

    ``apply_to`` controls the markup base:

    * ``direct_cost`` - applies to the BOQ direct-cost subtotal only
      (excludes every other markup line).
    * ``subtotal`` - applies to the direct-cost subtotal **plus the sum
      of all preceding markup lines** (e.g. VAT/output tax on the
      contractor price including overhead & profit). Behaves identically
      to ``cumulative``; the alias is retained for GAEB/legacy clients
      that label the tax base "subtotal".
    * ``cumulative`` - applies to the running total *including all
      prior markups*. When multiple markups have ``apply_to='cumulative'``
      they are evaluated in ``sort_order`` ASC, and each cumulative
      markup's base is the direct-cost subtotal **plus** every PRIOR
      markup (cumulative, subtotal or direct_cost) in the same BOQ. This
      compounds profit-on-overhead-on-cost, the GAEB / DIN 276 default.
      Reorder markups by changing ``sort_order``; ties are stable by ``id``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    markup_type: str = Field(default="percentage", pattern=r"^(percentage|fixed|per_unit)$")
    category: str = Field(
        default="overhead",
        pattern=r"^(overhead|profit|tax|contingency|insurance|bond|other)$",
    )
    percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    fixed_amount: Decimal = Field(default=Decimal("0"), ge=0)
    apply_to: str = Field(default="direct_cost", pattern=r"^(direct_cost|subtotal|cumulative)$")
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkupUpdate(_MarkupBase):
    """Partial update for a BOQ markup."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    markup_type: str | None = Field(default=None, pattern=r"^(percentage|fixed|per_unit)$")
    category: str | None = Field(
        default=None,
        pattern=r"^(overhead|profit|tax|contingency|insurance|bond|other)$",
    )
    percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    fixed_amount: Decimal | None = Field(default=None, ge=0)
    apply_to: str | None = Field(default=None, pattern=r"^(direct_cost|subtotal|cumulative)$")
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class MarkupResponse(_MarkupBase):
    """Markup line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    name: str
    markup_type: str
    category: str
    percentage: float
    fixed_amount: Decimal = Decimal("0")
    apply_to: str
    sort_order: int
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class MarkupCalculated(MarkupResponse):
    """Markup response enriched with the computed amount.

    v3 §10 - ``amount`` is money; emitted as a Decimal-as-string so
    rollups stay locale-neutral and exact.
    """

    amount: Decimal = Decimal("0")

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Composite schemas ─────────────────────────────────────────────────────────


class BOQWithPositions(BOQResponse):
    """BOQ with all its positions and computed grand total.

    ``grand_total`` includes active markups (matches list / structured
    semantics - BUG-008).  ``direct_cost_total`` and ``markups_total``
    are exposed alongside for clients that need the breakdown without
    re-summing markups themselves.

    v3 §10 - money emitted as Decimal-as-string.
    """

    positions: list[PositionResponse] = Field(default_factory=list)
    direct_cost_total: Decimal = Decimal("0")
    markups_total: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")
    position_count: int = 0

    @field_serializer("direct_cost_total", "markups_total", "grand_total", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class SectionResponse(BaseModel):
    """A BOQ section (header) with its child positions and subtotal.

    v3 §10 - ``subtotal`` is money; Decimal-as-string in JSON.
    """

    id: UUID
    ordinal: str
    description: str
    positions: list[PositionResponse] = Field(default_factory=list)
    subtotal: Decimal = Decimal("0")

    # BUG-MATH04: matches PositionResponse / BOQResponse policy.
    @field_validator("description", mode="after")
    @classmethod
    def _strip_html_on_response(cls, v: str) -> str:
        from app.core.sanitize import sanitise_text

        return sanitise_text(v) or ""

    @field_serializer("subtotal", when_used="json")
    def _ser_subtotal(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class BOQWithSections(BOQResponse):
    """BOQ with hierarchical sections, positions, subtotals, and markups.

    ``sections`` - grouped positions under section headers.
    ``positions`` - ungrouped positions that have no parent (and are not sections).
    ``direct_cost`` - sum of all position totals (items only, not sections).
    ``markups`` - ordered list of markup lines with computed amounts.
    ``net_total`` - direct_cost + sum of markup amounts.
    ``tax_rate`` - VAT / sales-tax fraction applied to net_total (None = no tax).
    ``tax_amount`` - net_total * tax_rate, ROUND_HALF_UP to 2 dp (0 when no tax).
    ``grand_total`` - net_total + tax_amount.

    v3 §10 - money emitted as Decimal-as-string.
    """

    sections: list[SectionResponse] = Field(default_factory=list)
    positions: list[PositionResponse] = Field(default_factory=list)
    direct_cost: Decimal = Decimal("0")
    markups: list[MarkupCalculated] = Field(default_factory=list)
    net_total: Decimal = Decimal("0")
    tax_rate: Decimal | None = None
    tax_amount: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")

    @field_serializer("direct_cost", "net_total", "tax_rate", "tax_amount", "grand_total", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


# ── Template schemas ─────────────────────────────────────────────────────────


class TemplatePositionInfo(BaseModel):
    """Summary of a single template position (used in template listing)."""

    ordinal: str
    description: str
    unit: str
    qty_factor: float
    rate: float


class TemplateSectionInfo(BaseModel):
    """Summary of a single template section (used in template listing)."""

    ordinal: str
    description: str
    position_count: int


class TemplateInfo(BaseModel):
    """Summary of a BOQ template returned by GET /boqs/templates."""

    id: str
    name: str
    description: str
    icon: str
    section_count: int
    position_count: int


class BOQFromTemplateRequest(BaseModel):
    """Request body for creating a BOQ from a template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    template_id: str = Field(..., min_length=1, max_length=50)
    area_m2: float = Field(..., gt=0.0, description="Gross floor area in m2")
    boq_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Custom BOQ name. Defaults to template name if omitted.",
    )


# ── Issue #127: linked-position schemas ──────────────────────────────────────


class LinkedPositionInfo(BaseModel):
    """One member of a reference-code link group."""

    id: UUID
    boq_id: UUID
    ordinal: str
    description: str
    quantity: Decimal
    total: Decimal
    link_role: str | None = None
    is_master: bool = False

    @field_serializer("quantity", "total", when_used="json")
    @classmethod
    def _serialise_decimal(cls, v: Decimal) -> str:
        if not isinstance(v, Decimal):
            try:
                v = Decimal(str(v))
            except (InvalidOperation, ValueError):
                return "0"
        if not v.is_finite():
            return "0"
        return format(v, "f")


class PositionLinksResponse(BaseModel):
    """Result of ``GET /positions/{id}/links/`` - the code's reuse group.

    Lists every position that shares the queried position's
    ``reference_code`` across the whole project, identifies the master,
    and reports counts. ``linked`` is False for a standalone position
    (its code is used exactly once).
    """

    reference_code: str | None = None
    link_group_id: UUID | None = None
    linked: bool = False
    master_id: UUID | None = None
    total_count: int = 0
    instance_count: int = 0
    members: list[LinkedPositionInfo] = Field(default_factory=list)


# ── Activity log schemas ─────────────────────────────────────────────────────


# ── AI Chat schemas ──────────────────────────────────────────────────────────


class AIChatContext(BaseModel):
    """Context about the current BOQ for AI chat prompts.

    Currency / standard default to empty so the AI prompt renders bare
    blanks (interpreted by the LLM as "no constraint specified") rather
    than steering the model toward EUR + DIN-276. A hardcoded default
    of EUR/din276 silently mis-orientated suggestions on every USD/UK/
    LATAM project that didn't pass an explicit context.
    """

    project_name: str = ""
    currency: str = ""
    standard: str = ""
    existing_positions_count: int = 0


class AIChatRequest(BaseModel):
    """Request body for AI chat within the BOQ editor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=2000)
    context: AIChatContext = Field(default_factory=AIChatContext)
    locale: str = Field(default="en", max_length=10)


class AIChatItem(BaseModel):
    """A single BOQ position suggested by AI chat.

    v3 §10 - ``unit_rate`` and ``total`` are money and emitted as
    Decimal-as-string. ``quantity`` is a measurement and stays float.
    """

    ordinal: str
    description: str
    unit: str
    quantity: float
    unit_rate: Decimal = Decimal("0")
    total: Decimal = Decimal("0")

    @field_serializer("unit_rate", "total", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class AIChatResponse(BaseModel):
    """Response from AI chat.

    ``reply`` is the assistant's natural-language answer - always populated
    when the model produced any output, so a knowledge question gets a real
    answer instead of an empty chat (issue #138). ``items`` are suggested
    BOQ positions, present only when the user asked to generate scope.
    ``message`` is an optional operational summary of generated items.
    """

    items: list[AIChatItem] = Field(default_factory=list)
    reply: str = ""
    message: str = ""


# ── Activity log schemas ─────────────────────────────────────────────────────


class ActivityLogResponse(BaseModel):
    """Activity log entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None
    boq_id: UUID | None
    user_id: UUID | None = None
    action: str
    target_type: str
    target_id: UUID | None
    description: str
    changes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime


class ActivityLogList(BaseModel):
    """Paginated list of activity log entries."""

    items: list[ActivityLogResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Snapshot schemas ─────────────────────────────────────────────────────────


class SnapshotCreate(BaseModel):
    """Create a point-in-time snapshot of a BOQ.

    Some clients (older UI, third-party scripts) post the snapshot title
    as ``label`` instead of ``name``. The validation alias accepts both
    spellings; the server canonicalises to ``name`` before persisting,
    so downstream code only ever sees one field.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(
        default="",
        max_length=255,
        validation_alias=AliasChoices("name", "label"),
    )


class SnapshotResponse(BaseModel):
    """A BOQ snapshot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    name: str
    created_at: datetime
    created_by: UUID | None = None


class SnapshotDetail(SnapshotResponse):
    """Full snapshot including data payload."""

    snapshot_data: dict[str, Any] = Field(default_factory=dict)


# ── Sustainability / CO2 schemas ─────────────────────────────────────────────


class CostBreakdownCategory(BaseModel):
    """A single cost category in the breakdown (e.g. material, labor).

    v3 §10 - ``amount`` is money; ``percentage`` stays float (ratio).
    """

    type: str
    amount: Decimal = Decimal("0")
    percentage: float
    item_count: int

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CostBreakdownMarkup(BaseModel):
    """A markup line in the cost breakdown.

    v3 §10 - ``amount`` is money; ``percentage`` stays float (ratio).
    """

    name: str
    percentage: float
    amount: Decimal = Decimal("0")

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CostBreakdownResource(BaseModel):
    """A top resource by cost in the breakdown.

    v3 §10 - ``total_cost`` is money.
    """

    name: str
    type: str
    total_cost: Decimal = Decimal("0")
    positions_count: int

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CostBreakdownResponse(BaseModel):
    """Full cost breakdown response for a BOQ.

    v3 §10 - money emitted as Decimal-as-string.
    """

    boq_id: str
    grand_total: Decimal = Decimal("0")
    direct_cost: Decimal = Decimal("0")
    categories: list[CostBreakdownCategory] = Field(default_factory=list)
    markups: list[CostBreakdownMarkup] = Field(default_factory=list)
    top_resources: list[CostBreakdownResource] = Field(default_factory=list)

    @field_serializer("grand_total", "direct_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Resource Summary schemas ─────────────────────────────────────────────────


class ResourcePositionRef(BaseModel):
    """Pointer back to one BOQ position+resource slot that contributed to an
    aggregated ``ResourceSummaryItem``. The frontend uses this list to fan
    re-pick calls out to every occurrence of an abstract resource without
    needing a dedicated bulk endpoint."""

    position_id: str
    resource_idx: int


class ResourceSummaryItem(BaseModel):
    """A single aggregated resource across all positions in a BOQ.

    Variant fields (``available_variants`` etc.) are populated only when at
    least one underlying ``position.metadata.resources[idx]`` carries the
    cached CWICR variant catalog. They mirror the per-row variant pill on
    the BOQ grid so the same picker can swap variants from this aggregated
    view; ``current_variant_label`` is set when every contributing position
    agrees on the same pick (otherwise ``"__mixed__"`` so the UI can flag
    the conflict)."""

    name: str
    type: str
    unit: str
    total_quantity: float  # measurement, not money
    # v3 §10 - avg_unit_rate / total_cost are money: Decimal-as-string.
    avg_unit_rate: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    positions_used: int

    # Variant surface - null when the resource has no abstract-resource
    # catalog cached on any contributing position.
    available_variants: list[dict[str, Any]] | None = None
    variant_stats: dict[str, Any] | None = None
    current_variant_label: str | None = None
    variant_default: str | None = None
    currency: str | None = None
    # CWICR resource_code - first non-empty value seen across contributing
    # rows. Used by the frontend to dedupe variant pickers when two summary
    # rows share an abstract-resource catalog (CWICR ships some rates with
    # multiple human-readable component names that resolve to the same
    # ``resource_code`` and therefore the same variant catalog).
    resource_code: str | None = None
    position_refs: list[ResourcePositionRef] = Field(default_factory=list)

    # Issue #106 - Pareto / ABC analysis. ``abc_percentage`` is the share
    # this resource takes of the total summed cost across the response
    # (``sum(item.total_cost for item in resources)``), expressed as 0–100.
    # ``abc_class`` is the conventional A/B/C bucket using the standard
    # 80/15/5 cumulative thresholds - A = top items that together make up
    # ~80 % of cost, B = next ~15 %, C = bottom ~5 %. Both fields are
    # populated server-side after rows are sorted by descending cost so
    # the frontend just renders without re-summing.
    abc_percentage: float = 0.0
    abc_class: str | None = None  # "A" | "B" | "C"

    @field_serializer("avg_unit_rate", "total_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ResourceTypeSummary(BaseModel):
    """Summary statistics for a single resource type.

    v3 §10 - ``total_cost`` is money; Decimal-as-string in JSON.
    """

    count: int
    total_cost: Decimal = Decimal("0")

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ResourceSummaryResponse(BaseModel):
    """Full resource summary for a BOQ - aggregated across all positions.

    v3 §10 - ``grand_total`` is money; Decimal-as-string in JSON.
    """

    total_resources: int
    by_type: dict[str, ResourceTypeSummary] = Field(default_factory=dict)
    resources: list[ResourceSummaryItem] = Field(default_factory=list)
    # Issue #106 - sum of every ``resource.total_cost`` in this response.
    # The frontend uses it to render the ABC dashboard's "Total" column
    # without recomputing, and to validate that the per-row percentages
    # sum to 100 (rounding tolerance ≤ 0.01).
    grand_total: Decimal = Decimal("0")

    @field_serializer("grand_total", when_used="json")
    def _ser_grand_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ResourceCodeMatch(BaseModel):
    """A single existing resource that already uses a given code.

    Issue #133. The reusable *definition* (name / type / unit / unit_rate /
    currency) plus where it was first found, so the BOQ editor can offer
    "insert the existing resource" vs "create a new one with another code".
    Quantity is intentionally NOT part of the definition - it is always
    per-instance (mirrors the #127 position-reuse contract).

    v3 §10 - ``unit_rate`` is money; Decimal-as-string in JSON.
    """

    code: str
    name: str = ""
    type: str = ""
    unit: str = ""
    unit_rate: Decimal = Decimal("0")
    currency: str = ""
    # Provenance - surfaced verbatim to the user in the collision prompt.
    position_id: str = ""
    position_ordinal: str = ""
    position_description: str = ""

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ResourceCodeLookupResponse(BaseModel):
    """Result of a project-wide resource-code lookup (Issue #133)."""

    found: bool = False
    code: str = ""
    match: ResourceCodeMatch | None = None


class CO2MaterialBreakdown(BaseModel):
    """CO2 breakdown for a single material category."""

    material: str
    category: str = ""
    quantity: float
    unit: str
    co2_kg: float
    percentage: float
    positions_count: int = 0


class PositionCO2Detail(BaseModel):
    """CO2 data for a single BOQ position."""

    position_id: str
    ordinal: str
    description: str
    quantity: float
    unit: str
    epd_id: str | None = None
    epd_name: str | None = None
    gwp_per_unit: float = 0.0
    gwp_total: float = 0.0
    category: str = ""
    source: str = "none"  # "enriched" | "auto-detected" | "none"


class SustainabilityResponse(BaseModel):
    """Sustainability / CO2 analysis result for a BOQ."""

    total_co2_kg: float
    total_co2_tons: float
    breakdown: list[CO2MaterialBreakdown] = Field(default_factory=list)
    benchmark_per_m2: float | None = None
    rating: str = ""
    rating_label: str = ""
    project_area_m2: float | None = None
    positions_analyzed: int = 0
    positions_matched: int = 0
    lifecycle_stages: str = "A1-A3"
    data_quality: str = "estimated"  # "enriched" | "estimated" | "mixed"
    positions_detail: list[PositionCO2Detail] = Field(default_factory=list)
    eu_cpr_compliance: str = ""  # "excellent" | "good" | "acceptable" | "non-compliant" | ""
    eu_cpr_gwp_per_m2_year: float | None = None


class CO2EnrichResponse(BaseModel):
    """Response from the CO2 enrichment endpoint."""

    enriched: int = 0
    skipped: int = 0
    total: int = 0


class CO2AssignRequest(BaseModel):
    """Request to manually assign an EPD material to a position."""

    epd_id: str = Field(..., min_length=1, max_length=100)


# ── AACE Estimate Classification schemas ────────────────────────────────────


class EstimateClassificationMetrics(BaseModel):
    """Raw metrics used to determine the AACE estimate class."""

    total_positions: int = 0
    positions_with_rates: int = 0
    positions_with_resources: int = 0
    positions_with_classification: int = 0
    rate_completeness_pct: float = 0.0
    resource_completeness_pct: float = 0.0
    classification_completeness_pct: float = 0.0


class EstimateClassificationResponse(BaseModel):
    """AACE 18R-97 estimate classification result for a BOQ.

    See AACE International Recommended Practice 18R-97 for the full standard.
    Classes range from 5 (least defined) to 1 (most defined).
    """

    estimate_class: int = Field(..., ge=1, le=5, description="AACE class 1-5")
    class_label: str = Field(default="", description="Human-readable label (e.g. 'Screening')")
    accuracy_low: str = Field(default="", description="Lower accuracy bound (e.g. '-50%')")
    accuracy_high: str = Field(default="", description="Upper accuracy bound (e.g. '+100%')")
    definition_level_low: int = Field(default=0, ge=0, le=100, description="Lower definition level %")
    definition_level_high: int = Field(default=0, ge=0, le=100, description="Upper definition level %")
    methodology: str = Field(default="", description="Typical estimation methodology for this class")
    metrics: EstimateClassificationMetrics = Field(default_factory=EstimateClassificationMetrics)


# ── Sensitivity Analysis schemas ────────────────────────────────────────────


class SensitivityItem(BaseModel):
    """A single item in the sensitivity / tornado chart analysis."""

    ordinal: str
    description: str
    total: float
    share_pct: float
    impact_low: float
    impact_high: float


class SensitivityResponse(BaseModel):
    """Sensitivity analysis (tornado chart) result for a BOQ.

    Shows which positions have the biggest impact on the total cost when
    their cost varies by ``variation_pct`` percent.

    v3 §10 - ``base_total`` is money; Decimal-as-string in JSON.
    """

    base_total: Decimal = Decimal("0")
    variation_pct: float = 10.0
    items: list[SensitivityItem] = Field(default_factory=list)

    @field_serializer("base_total", when_used="json")
    def _ser_base_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Monte Carlo Cost Risk Analysis schemas ────────────────────────────────


class CostRiskHistogramBin(BaseModel):
    """A single bin in the Monte Carlo histogram."""

    bin_start: float
    bin_end: float
    count: int


class CostRiskDriver(BaseModel):
    """A position contributing to total cost variance in Monte Carlo simulation."""

    ordinal: str
    description: str
    contribution_pct: float


class CostRiskPercentiles(BaseModel):
    """Percentile values from the Monte Carlo simulation."""

    p10: float
    p25: float
    p50: float
    p75: float
    p80: float
    p90: float


class CostRiskResponse(BaseModel):
    """Monte Carlo cost risk simulation result for a BOQ.

    Runs N iterations of PERT-distributed cost sampling per position,
    collects total costs, and returns percentiles, histogram, contingency,
    and risk drivers (positions contributing most to variance).

    v3 §10 - ``base_total`` and ``recommended_budget`` are money;
    Decimal-as-string in JSON.
    """

    iterations: int
    base_total: Decimal = Decimal("0")
    percentiles: CostRiskPercentiles
    contingency_p80: float
    contingency_pct: float
    recommended_budget: Decimal = Decimal("0")
    histogram: list[CostRiskHistogramBin] = Field(default_factory=list)
    risk_drivers: list[CostRiskDriver] = Field(default_factory=list)

    @field_serializer("base_total", "recommended_budget", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── AI Classification schemas ─────────────────────────────────────────────


class ClassifyRequest(BaseModel):
    """Request body for AI-powered classification code suggestion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=1000)
    unit: str = ""
    # Epic - Brazil (BRL invoice support feedback 2026-05-27): added ``nbr``
    # and ``sinapi`` so estimators on a Brazilian project can ask the
    # classifier for ABNT NBR 12721 cost groups or SINAPI composition codes
    # instead of being silently DIN-276'd by the default.
    project_standard: str = Field(
        default="din276",
        pattern=r"^(din276|nrm|masterformat|nbr|sinapi)$",
    )


class ClassificationSuggestion(BaseModel):
    """A single classification code suggestion with confidence score."""

    standard: str
    code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClassifyResponse(BaseModel):
    """Response containing ranked classification code suggestions."""

    suggestions: list[ClassificationSuggestion] = Field(default_factory=list)


# ── CAD Element Classification schemas ─────────────────────────────────────


class CADElementInput(BaseModel):
    """A single CAD/BIM element for classification mapping."""

    id: str | None = None
    category: str = Field(..., min_length=1, max_length=255)
    classification: dict[str, str] = Field(default_factory=dict)


class ClassifyElementsRequest(BaseModel):
    """Request body for deterministic CAD element classification mapping.

    Takes a list of CAD elements (with Revit/IFC categories) and maps them
    to the requested construction classification standard using lookup tables.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    elements: list[CADElementInput] = Field(..., min_length=1, max_length=50000)
    # Epic - Brazil (2026-05-27): widened to accept ``nbr`` (ABNT NBR 12721)
    # and ``sinapi`` so a CAD/BIM upload on a BR project can map to the
    # Brazilian classification systems instead of defaulting to DIN 276.
    standard: str = Field(
        default="din276",
        pattern=r"^(din276|nrm|masterformat|nbr|sinapi)$",
    )


class ClassifiedElement(BaseModel):
    """A CAD element with classification codes added."""

    id: str | None = None
    category: str
    classification: dict[str, str] = Field(default_factory=dict)
    mapped: bool = False


class ClassifyElementsResponse(BaseModel):
    """Response for CAD element classification mapping."""

    elements: list[ClassifiedElement] = Field(default_factory=list)
    standard: str
    total: int = 0
    mapped_count: int = 0
    unmapped_count: int = 0


# ── AI Rate Suggestion schemas ─────────────────────────────────────────────


class SuggestRateRequest(BaseModel):
    """Request body for AI-powered market rate suggestion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=1000)
    unit: str = ""
    classification: dict[str, Any] = Field(default_factory=dict)
    region: str | None = None


class RateMatch(BaseModel):
    """A single rate match from vector search results.

    v3 §10 - ``rate`` is money; ``score`` stays float (similarity 0.0-1.0).
    """

    code: str
    description: str
    rate: Decimal = Decimal("0")
    region: str
    score: float

    @field_serializer("rate", when_used="json")
    def _ser_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class SuggestRateResponse(BaseModel):
    """Response containing a suggested market rate with supporting matches.

    v3 §10 - ``suggested_rate`` is money; ``confidence`` stays float (ratio).
    """

    suggested_rate: Decimal = Decimal("0")
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "vector_search"
    matches: list[RateMatch] = Field(default_factory=list)

    @field_serializer("suggested_rate", when_used="json")
    def _ser_suggested_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Anomaly Detection schemas ──────────────────────────────────────────────


class PricingAnomaly(BaseModel):
    """A pricing anomaly detected in a BOQ position."""

    position_id: str
    field: str = "unit_rate"
    current_value: float
    market_range: dict[str, float] = Field(
        default_factory=dict,
        description="Market rate percentiles: p25, median, p75",
    )
    severity: str = Field(pattern=r"^(warning|error)$")
    message: str
    suggestion: float


class AnomalyCheckResponse(BaseModel):
    """Response from a BOQ pricing anomaly check."""

    anomalies: list[PricingAnomaly] = Field(default_factory=list)
    positions_checked: int = 0


# ── AI Cost Finder (vector search) ──────────────────────────────────────────


class CostItemSearchRequest(BaseModel):
    """Request body for AI-powered cost item search."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=50)
    limit: int = Field(default=15, ge=1, le=30)
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)


class CostItemSearchResult(BaseModel):
    """A single cost item result from vector search."""

    id: str
    code: str
    description: str
    unit: str
    rate: float
    region: str
    score: float = Field(ge=0.0, le=1.0)
    classification: dict[str, str] = Field(default_factory=dict)
    components: list[dict[str, Any]] = Field(default_factory=list)
    # Empty when the underlying CostItem row has no currency; the
    # frontend renders bare numbers in that case rather than mis-stamping
    # EUR onto a USD/GBP/JPY-currency catalogue row.
    currency: str = ""


class CostItemSearchResponse(BaseModel):
    """Response from AI cost item search."""

    results: list[CostItemSearchResult] = Field(default_factory=list)
    total_found: int = 0
    query_embedding_ms: float = 0.0
    search_ms: float = 0.0


# ── LLM-powered AI features ─────────────────────────────────────────────────


class EnhanceDescriptionRequest(BaseModel):
    """Request to enhance a BOQ position description via LLM."""

    description: str = Field(..., min_length=2, max_length=500)
    unit: str = "m2"
    classification: dict[str, str] = Field(default_factory=dict)
    locale: str = Field(default="en", max_length=10)


class EnhanceDescriptionResponse(BaseModel):
    """Enhanced description with specs and standards."""

    enhanced_description: str
    specifications: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model_used: str = ""
    tokens_used: int = 0


class SuggestPrerequisitesRequest(BaseModel):
    """Request to suggest prerequisite/related positions."""

    description: str = Field(..., min_length=2, max_length=500)
    unit: str = "m2"
    classification: dict[str, str] = Field(default_factory=dict)
    existing_descriptions: list[str] = Field(default_factory=list)
    locale: str = Field(default="en", max_length=10)


class PrerequisiteItem(BaseModel):
    """A single suggested prerequisite/companion position.

    v3 §10 - ``typical_rate_eur`` is money; Decimal-as-string in JSON.
    """

    description: str
    unit: str
    typical_rate_eur: Decimal = Decimal("0")
    relationship: str = "companion"  # prerequisite | companion | successor
    reason: str = ""

    @field_serializer("typical_rate_eur", when_used="json")
    def _ser_typical_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class SuggestPrerequisitesResponse(BaseModel):
    """List of suggested prerequisite positions."""

    suggestions: list[PrerequisiteItem] = Field(default_factory=list)
    model_used: str = ""
    tokens_used: int = 0


class CheckScopeRequest(BaseModel):
    """Request to check BOQ scope completeness.

    Region / currency default to empty so the LLM scope analysis runs
    without DACH-biased trade packages (Bauhauptgewerbe / Ausbaugewerbe
    only make sense in German practice). The AI prompt is responsible
    for picking region-appropriate trade lists when these are populated.
    """

    project_type: str = "general"  # residential, commercial, industrial, infrastructure
    region: str = ""
    currency: str = ""
    locale: str = Field(default="en", max_length=10)


class ScopeMissingItem(BaseModel):
    """A single missing scope item.

    v3 §10 - ``estimated_rate`` is money; Decimal-as-string in JSON.
    """

    description: str
    category: str = ""
    priority: str = "medium"  # high | medium | low
    reason: str = ""
    estimated_rate: Decimal = Decimal("0")
    unit: str = "lsum"

    @field_serializer("estimated_rate", when_used="json")
    def _ser_estimated_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CheckScopeResponse(BaseModel):
    """Scope completeness analysis result."""

    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_items: list[ScopeMissingItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    model_used: str = ""
    tokens_used: int = 0


class BOQStatisticsResponse(BaseModel):
    """Aggregated statistics for a BOQ.

    v3 §10 - ``direct_cost`` / ``grand_total`` / ``avg_unit_rate`` are
    money; emitted as Decimal-as-string. Percentage fields stay float.
    """

    boq_id: str
    boq_name: str
    status: str
    position_count: int = 0
    section_count: int = 0
    direct_cost: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")
    avg_unit_rate: Decimal = Decimal("0")
    completion_pct: float = Field(
        default=0.0,
        description="Percentage of positions with both quantity > 0 and unit_rate > 0",
    )
    unit_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Count of positions per unit type (m2, m3, kg, etc.)",
    )
    source_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Count of positions per source (manual, template, gaeb_import, etc.)",
    )
    classification_coverage_pct: float = Field(
        default=0.0,
        description="Percentage of positions with at least one classification code",
    )
    created_at: datetime
    updated_at: datetime

    @field_serializer("direct_cost", "grand_total", "avg_unit_rate", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class EscalateRateRequest(BaseModel):
    """Request to escalate a rate to current prices.

    Currency / region default to empty so the AI prompt pipes blank
    strings into the LLM template - interpreted as "no constraint
    specified". Hardcoding EUR + DACH steered every escalation toward
    BKI (the German construction cost index), even on US/UK projects
    where ENR / BCIS would be the right index.
    """

    description: str = Field(..., min_length=2, max_length=500)
    unit: str = "m2"
    rate: float = Field(..., gt=0)
    currency: str = ""
    base_year: int = Field(default=2023, ge=2000, le=2030)
    target_year: int = Field(default=2026, ge=2000, le=2035)
    region: str = ""
    locale: str = Field(default="en", max_length=10)


class EscalationFactors(BaseModel):
    """Breakdown of escalation factors.

    v3 §10 - ``labor_cost_change`` is money (annual labour cost delta);
    Decimal-as-string in JSON. ``material_inflation`` and
    ``regional_adjustment`` stay float (they are pure ratios/percentages).
    """

    material_inflation: float = 0.0
    labor_cost_change: Decimal = Decimal("0")
    regional_adjustment: float = 0.0

    @field_serializer("labor_cost_change", when_used="json")
    def _ser_labor_cost_change(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class EscalateRateResponse(BaseModel):
    """Rate escalation result.

    v3 §10 - ``original_rate`` and ``escalated_rate`` are money;
    Decimal-as-string in JSON.
    """

    original_rate: Decimal = Decimal("0")
    escalated_rate: Decimal = Decimal("0")
    escalation_percent: float
    factors: EscalationFactors = Field(default_factory=EscalationFactors)
    confidence: str = "medium"  # high | medium | low
    reasoning: str = ""
    model_used: str = ""
    tokens_used: int = 0

    @field_serializer("original_rate", "escalated_rate", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


class LineItemResponse(BaseModel):
    """A single line item in the cost-drivers Pareto widget.

    v3 §10 - ``unit_rate`` and ``total_cost`` are money; Decimal-as-string
    in JSON.
    """

    position_id: str
    description: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_rate: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")

    @field_serializer("unit_rate", "total_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)

    share_of_total: float = Field(0.0, description="Share of the aggregate project total - 0.0 to 1.0")


class CostRollupItem(BaseModel):
    """One row in the classification-grouped cost rollup."""

    code: str = ""
    label: str = ""
    total: float = 0.0
    position_count: int = 0


class AnomalyResponse(BaseModel):
    """Single anomaly flag on a BOQ position.

    Anomaly detection for v1.9.1 is pure statistics (z-score on unit_rate
    within the same classification group, neighbour-median jump detection,
    and simple missing-field checks). ML-based detection is deferred to
    v1.9.2 - see RFC 25.
    """

    position_id: str
    ordinal: str = ""
    description: str = ""
    type: str = Field(..., description="outlier | jump | format")
    severity: str = Field("warning", description="info | warning | error")
    detail: str = ""
    value: float | None = None
    reference: float | None = None


# ── Feature 1: model→BOQ quantity-link schemas ────────────────────────────────

# The canonical aggregation modes a link may apply across its bound
# elements. Kept as a Literal so a typo is a 422, not a silent "sum".
QuantityAggregation = Literal["sum", "max", "min", "count", "first"]


class QuantityLinkCreate(BaseModel):
    """Bind a BOQ position numeric field to one or more BIM elements.

    The link is an *extraction rule*, never a cached value. Creating it
    does NOT mutate the position quantity - call the refresh + confirm
    endpoints to pull and (human-)apply values.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    model_id: UUID
    element_stable_ids: list[str] = Field(..., min_length=1)
    quantity_field: str = Field(..., min_length=1, max_length=64)
    target_field: Literal["quantity"] = "quantity"
    aggregation: QuantityAggregation = "sum"

    @field_validator("element_stable_ids")
    @classmethod
    def _dedupe_non_empty(cls, v: list[str]) -> list[str]:
        """Strip blanks and duplicates while preserving first-seen order."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in v:
            s = str(raw).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        if not out:
            raise ValueError("element_stable_ids must contain at least one id")
        return out


class QuantityLinkResponse(BaseModel):
    """A persisted quantity link returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    position_id: UUID
    boq_id: UUID
    model_id: UUID
    element_stable_ids: list[str]
    quantity_field: str
    target_field: str
    aggregation: str
    status: str
    source_model_version: str | None = None
    last_applied_quantity: str | None = None
    last_pulled_at: str | None = None
    last_applied_at: str | None = None
    created_at: datetime
    updated_at: datetime


class QuantityLinkRefreshRow(BaseModel):
    """Per-position review row produced by the refresh endpoint.

    ``new_quantity`` is what the bound elements compute *now* (post the
    latest model version). ``old_quantity`` is the position's current
    stored value. ``delta`` = new − old. Nothing is written until the
    confirm endpoint is called for the chosen links (the architecture guide §7).
    """

    link_id: UUID
    position_id: UUID
    ordinal: str
    description: str
    quantity_field: str
    target_field: str
    aggregation: str
    unit: str
    old_quantity: str
    new_quantity: str
    delta: str
    changed: bool
    status: str
    contributing_elements: list[str]
    missing_element_ids: list[str]
    message: str = ""


class QuantityLinkRefreshResponse(BaseModel):
    """Result of probing every link in a BOQ against the latest model."""

    boq_id: UUID
    checked: int
    stale: int
    rows: list[QuantityLinkRefreshRow]


class QuantityLinkApplyRequest(BaseModel):
    """Confirm payload - explicit list of link ids to apply (human gate)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    link_ids: list[UUID] = Field(..., min_length=1)


class QuantityLinkApplyResultRow(BaseModel):
    """Outcome of applying one re-pulled quantity to its position."""

    link_id: UUID
    position_id: UUID
    ordinal: str
    applied: bool
    old_quantity: str
    new_quantity: str
    message: str = ""


class QuantityLinkApplyResponse(BaseModel):
    """Aggregate result of a confirm/apply call."""

    boq_id: UUID
    applied: int
    skipped: int
    results: list[QuantityLinkApplyResultRow]


# ── Feature 2: estimate baseline / line-level compare schemas ─────────────────

# How a position pairs across the two BOQs and what (if anything) moved.
CompareChangeType = Literal["added", "removed", "qty_changed", "rate_changed", "changed", "unchanged"]


class ComparePositionRow(BaseModel):
    """One classified line in a BOQ-to-BOQ comparison.

    Money/quantity fields are emitted as plain decimal strings (same
    contract as :class:`PositionResponse`) so large totals round-trip
    exactly and stay locale-neutral. ``*_base`` totals are the position
    totals rebased into the project base currency via the existing FX
    table so a multi-currency estimate compares apples to apples.
    """

    change_type: CompareChangeType
    match_key: str
    reference_code: str | None = None
    ordinal: str
    description: str
    unit: str

    old_quantity: str | None = None
    new_quantity: str | None = None
    old_unit_rate: str | None = None
    new_unit_rate: str | None = None
    old_total: str | None = None
    new_total: str | None = None
    old_total_base: str | None = None
    new_total_base: str | None = None
    currency: str = ""
    total_delta_base: str = "0"


class CompareSummary(BaseModel):
    """Roll-up counts + base-currency money deltas for a comparison."""

    base_currency: str = ""
    added: int = 0
    removed: int = 0
    qty_changed: int = 0
    rate_changed: int = 0
    changed: int = 0
    unchanged: int = 0
    old_direct_cost_base: str = "0"
    new_direct_cost_base: str = "0"
    direct_cost_delta_base: str = "0"


class BOQCompareResponse(BaseModel):
    """Side-by-side comparison of two BOQs (pure read, no mutation)."""

    base_boq_id: UUID
    other_boq_id: UUID
    base_boq_name: str
    other_boq_name: str
    summary: CompareSummary
    rows: list[ComparePositionRow]
