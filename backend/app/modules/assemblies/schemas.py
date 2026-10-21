# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assembly Pydantic schemas - request/response models.

Defines create, update, and response schemas for assemblies and components.
Numeric values are stored as strings in the database for SQLite
compatibility. v3 §10 money fields (``unit_cost``, ``unit_rate``,
``grand_total``) are emitted as Decimal-as-string in JSON;
``factor`` / ``quantity`` / ``total_rate`` / ``bid_factor`` stay as
``float`` because they are dimensionless multipliers / quantities.
"""

import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py::_serialise_money - money
# fields are stored / accepted as ``Decimal`` but emitted as plain decimal
# *strings* in JSON so totals stay exact and locale-neutral.
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


# ── Component schemas ────────────────────────────────────────────────────────


# Upper bound for any single component numeric (factor / quantity /
# unit_cost / bid_factor). 1e12 is far beyond any real estimating value
# (a trillion units / a trillion-currency unit rate) yet keeps every
# pairwise/triple product finite in float and Decimal, so a component
# total can never silently overflow to ``inf`` and serialise as ``null``.
_NUM_MAX: float = 1e12


def _sanitise_regional_factors(raw: Any) -> dict[str, Any]:
    """Coerce a payload-supplied ``regional_factors`` dict to safe values.

    The column is JSON so the Pydantic ``dict[str, Any]`` shape itself
    cannot reject ``{"berlin": "Infinity"}`` / ``{"x": -5}`` / nested
    dicts - but those values get multiplied straight into the BOQ
    position's ``unit_rate`` at apply-to-boq time (NEW-ASM-105 /
    ASM-007). Drop any non-finite, negative, or non-numeric entry at
    the schema boundary rather than letting it persist and corrupt a
    downstream rollup.

    A ``None`` input is normalised to ``{}`` so the caller never has to
    juggle a ``regional_factors is None`` branch.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, val in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        # Reject booleans (which are an int subclass) and nested
        # containers - a factor must be a single number.
        if isinstance(val, bool) or isinstance(val, (dict, list)):
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(num) or num < 0 or num > _NUM_MAX:
            continue
        cleaned[key.strip()] = num
    return cleaned


# Allowed resource_type values. Kept as a Literal-ish string so the DB
# storage stays a simple varchar (FE/BE share a string contract; we don't
# want a Postgres ENUM that needs a migration every time we add a kind).
RESOURCE_TYPES: tuple[str, ...] = (
    "material",
    "labor",
    "equipment",
    "operator",
    "subcontractor",
    "overhead",
)


# ── Parametric assembly parameters (Issue #365) ──────────────────────────────


class AssemblyParameter(BaseModel):
    """One named parameter that drives an assembly's component quantities.

    Three kinds:

    * ``input``      - a value the estimator enters (with a stored default).
    * ``constant``   - a fixed value baked into the template.
    * ``calculated`` - a formula over the other parameters (evaluated by the
      shared #347 allow-listed-AST + Decimal engine).

    ``value`` is Decimal-in / Decimal-as-string out (money-neutral but stored
    exactly so ``0.1 + 0.2`` stays exact). Cross-parameter checks (unique
    names, resolvable references, no cycles) are the parameter graph's job and
    run in the service layer via ``parametric.validate_parameter_graph``; this
    model only enforces the per-parameter shape.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=64)
    kind: Literal["input", "calculated", "constant"] = "input"
    value: Decimal | None = Field(default=None, le=_NUM_MAX, ge=-_NUM_MAX)
    formula: str | None = Field(default=None, max_length=512)
    unit: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=255)

    @field_validator("value", mode="after")
    @classmethod
    def _reject_non_finite(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("parameter value must be finite (no NaN / Infinity)")
        return v

    @model_validator(mode="after")
    def _check_kind_requirements(self) -> "AssemblyParameter":
        # input / constant carry a concrete numeric value; calculated carries a
        # non-empty formula instead. Mirrors the parametric engine's contract.
        if self.kind in ("input", "constant"):
            if self.value is None:
                raise ValueError(f"a {self.kind} parameter needs a numeric value")
        elif self.kind == "calculated" and not (self.formula and self.formula.strip()):
            raise ValueError("a calculated parameter needs a formula")
        return self

    @field_serializer("value", when_used="json")
    def _ser_value(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class ComponentCreate(BaseModel):
    """Create a new assembly component.

    Accepts ``name`` as an alias for ``description`` and ``unit_rate`` as an
    alias for ``unit_cost`` so that the AI-generate preview payload can be
    forwarded directly without field remapping on the frontend.

    ``resource_type`` is now a first-class column (v2940). Free-form
    extended fields (waste_pct for materials, crew_size/hours/burden_pct
    for labor, fuel_cost/rental_days for equipment) live in ``metadata``
    so we don't lock the schema to one industry's vocabulary, but the
    service layer reads them when computing the typed total.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # ``_NUM_MAX`` bounds factor / quantity / unit_cost so their product
    # can never overflow to float ``inf`` (1e12 ** 3 = 1e36, finite in
    # both float and Decimal). ``allow_inf_nan=False`` makes Pydantic
    # reject the raw ``NaN`` / ``Infinity`` JSON literals Starlette's
    # json.loads otherwise accepts - a clean 422 instead of a silently
    # null-serialised total (ASM-002 / ASM-003). ``ge=0.0`` enforces the
    # domain rule that a recipe factor / quantity cannot be negative
    # (ASM-004); 0 stays legal for a disabled / optional line.
    cost_item_id: UUID | None = None
    catalog_resource_id: UUID | None = None
    description: str = Field(default="", max_length=500)
    name: str | None = Field(default=None, max_length=500, exclude=True)
    factor: float = Field(default=1.0, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    quantity: float = Field(default=1.0, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    # Parametric quantity (Issue #365): an arithmetic formula over the parent
    # assembly's parameters. When set it drives the component quantity at
    # apply/preview time; NULL keeps the static ``quantity`` above.
    quantity_formula: str | None = Field(default=None, max_length=512)
    unit: str = Field(..., min_length=1, max_length=20)
    # v3 §10 - money is Decimal-in / Decimal-as-string out.
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, le=_NUM_MAX)
    unit_rate: Decimal | None = Field(default=None, ge=0, le=_NUM_MAX, exclude=True)
    resource_type: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None

    @field_validator("unit_cost", "unit_rate", mode="after")
    @classmethod
    def _reject_non_finite_money(cls, v: Decimal | None) -> Decimal | None:
        # Decimal can be NaN/Infinity; we explicitly reject so the
        # downstream apply-to-boq arithmetic stays defensible.
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("money value must be finite (no NaN / Infinity)")
        return v

    def get_description(self) -> str:
        """Return description, falling back to name if description is empty."""
        return self.description or self.name or ""

    def get_unit_cost(self) -> Decimal:
        """Return unit_cost, falling back to unit_rate if unit_cost is zero."""
        if self.unit_cost > 0:
            return self.unit_cost
        return self.unit_rate if self.unit_rate is not None else Decimal("0")


class ComponentUpdate(BaseModel):
    """Partial update for an assembly component."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_item_id: UUID | None = None
    catalog_resource_id: UUID | None = None
    description: str | None = Field(default=None, max_length=500)
    factor: float | None = Field(default=None, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    quantity: float | None = Field(default=None, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    # Issue #365 - a formula over the assembly's parameters. Send an empty
    # string to clear it back to the static quantity.
    quantity_formula: str | None = Field(default=None, max_length=512)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    unit_cost: Decimal | None = Field(default=None, ge=0, le=_NUM_MAX)
    resource_type: str | None = Field(default=None, max_length=20)
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("unit_cost", mode="after")
    @classmethod
    def _reject_non_finite_money(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("unit_cost must be finite (no NaN / Infinity)")
        return v


class ComponentResponse(BaseModel):
    """Component returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    assembly_id: UUID
    cost_item_id: UUID | None
    catalog_resource_id: UUID | None = None
    description: str
    resource_type: str | None = None
    factor: float
    quantity: float
    # Issue #365 - the per-component quantity formula (NULL for a static line).
    quantity_formula: str | None = None
    unit: str
    unit_cost: Decimal = Decimal("0")
    # Decimal (not float) so JSON serialises an exact string like "90.0"
    # rather than 89.9999... - money/quantity totals must never be float
    # in the response payload (R7 deep-improve).
    total: Decimal = Decimal("0")
    sort_order: int
    # FastAPI defaults `response_model_by_alias=True`, so if we aliased
    # this to "metadata_" the wire payload would carry the trailing
    # underscore - which we don't want. The ORM column is `metadata_`
    # (Python keyword conflict on Base), but it's renamed at the
    # response builder.
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_serializer("unit_cost", when_used="json")
    def _ser_unit_cost(self, v: Decimal) -> str | None:
        return _serialise_money(v)

    @field_serializer("total", when_used="json")
    def _ser_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Assembly schemas ─────────────────────────────────────────────────────────


class AssemblyCreate(BaseModel):
    """Create a new assembly."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    unit: str = Field(..., min_length=1, max_length=20)
    category: str = ""
    classification: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(default="EUR", max_length=10)
    # Bound bid_factor exactly like ComponentCreate.factor (ASM-002 /
    # NEW-ASM-101): ``allow_inf_nan=False`` rejects the raw NaN /
    # Infinity JSON literals Starlette's json.loads otherwise accepts,
    # ``ge=0`` forbids a negative markup, ``le=_NUM_MAX`` keeps
    # ``subtotal * bid_factor`` finite in float and Decimal so
    # total_rate can never serialise as null / Infinity.
    bid_factor: float = Field(default=1.0, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    regional_factors: dict[str, Any] = Field(default_factory=dict)
    # Issue #365 - ordered parameter definitions (empty = non-parametric).
    parameters: list[AssemblyParameter] = Field(default_factory=list, max_length=200)
    is_template: bool = True
    project_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("regional_factors", mode="before")
    @classmethod
    def _clean_regional_factors(cls, v: Any) -> dict[str, Any]:
        # NEW-ASM-107 - strip non-finite / negative / non-numeric
        # entries so a poisoned factor can't reach apply-to-boq.
        return _sanitise_regional_factors(v)


class AssemblyUpdate(BaseModel):
    """Partial update for an assembly."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    category: str | None = None
    classification: dict[str, Any] | None = None
    currency: str | None = Field(default=None, max_length=10)
    # Same bounds as AssemblyCreate.bid_factor (ASM-002 / NEW-ASM-101) -
    # an UPDATE must not be a back door for a non-finite / negative
    # markup that would poison the recalculated total_rate.
    bid_factor: float | None = Field(default=None, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    regional_factors: dict[str, Any] | None = None
    # Issue #365 - when present, REPLACES the whole parameter set (the graph is
    # re-validated in the service before it is persisted).
    parameters: list[AssemblyParameter] | None = None
    is_template: bool | None = None
    project_id: UUID | None = None
    is_active: bool | None = None
    # Merged into the stored metadata key by key (a key sent as ``null`` is
    # removed); it never replaces the whole object, so tags and import markers
    # survive a PATCH of another key.
    metadata: dict[str, Any] | None = None
    # When given, replaces ``metadata.tags``. Normalised on write: stripped,
    # lowercased, de-duplicated, empty entries dropped.
    tags: list[str] | None = Field(default=None, max_length=100)

    @field_validator("regional_factors", mode="before")
    @classmethod
    def _clean_regional_factors(cls, v: Any) -> Any:
        # NEW-ASM-107 - UPDATE must not be a back door for a poisoned
        # regional factor either. ``None`` is preserved so
        # ``exclude_unset=True`` semantics still work (i.e. an absent
        # field stays absent, not coerced to {}).
        if v is None:
            return None
        return _sanitise_regional_factors(v)


class AssemblyResponse(BaseModel):
    """Assembly returned from the API.

    Contract note (ASM-005): ``total_rate`` is the **unfactored base
    rate** - ``sum(component totals) * bid_factor`` only. It deliberately
    does NOT bake in any ``regional_factors`` entry, because an assembly
    holds many region coefficients at once and there is no single
    "current" region at the catalog level. The regional premium is
    applied at ``POST /{id}/apply-to-boq`` time against the chosen
    ``region``. Consumers that need a region-adjusted figure must
    multiply ``total_rate`` by ``regional_factors[region]`` themselves.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    name: str
    description: str
    unit: str
    category: str
    classification: dict[str, Any]
    total_rate: float
    currency: str
    bid_factor: float
    regional_factors: dict[str, Any]
    # Issue #365 - the recipe's parameter definitions (empty = non-parametric).
    parameters: list[AssemblyParameter] = Field(default_factory=list)
    is_template: bool
    project_id: UUID | None
    owner_id: UUID | None
    is_active: bool
    component_count: int = 0
    usage_count: int = 0
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ── Paginated response ──────────────────────────────────────────────────────


class AssemblySearchResponse(BaseModel):
    """Paginated assembly search result."""

    items: list[AssemblyResponse]
    total: int
    limit: int
    offset: int


# ── Composite schemas ────────────────────────────────────────────────────────


class AssemblyWithComponents(AssemblyResponse):
    """Assembly with all its components and computed total."""

    components: list[ComponentResponse] = Field(default_factory=list)
    computed_total: float = 0.0


# ── Action schemas ───────────────────────────────────────────────────────────


class ApplyToBOQRequest(BaseModel):
    """Request body for applying an assembly to a BOQ as a new position.

    Cross-currency behaviour (Issue #128): an assembly priced in a
    currency other than the target project's base is converted via the
    project's ``fx_rates`` when a matching rate exists; otherwise it is
    applied un-converted and the created position carries a non-blocking
    ``currency_mismatch`` flag in its metadata (the value stays in the
    assembly's own currency, which is recorded alongside it). The apply
    is never hard-refused - the old 409 trapped the user with no UI
    escape hatch, so there is no opt-in flag to set.
    """

    boq_id: UUID
    quantity: float = Field(..., gt=0.0, le=_NUM_MAX, allow_inf_nan=False)
    ordinal: str = Field(default="", max_length=50, description="Position ordinal; auto-generated if empty")
    region: str | None = Field(default=None, description="Region key for regional factor lookup")
    # Issue #365 - values for the assembly's ``input`` parameters (by name).
    # Empty = use each parameter's stored default. Component ``quantity_formula``
    # lines are then computed against the resolved parameter values.
    parameter_values: dict[str, float] = Field(default_factory=dict)


# ── Parametric validation & expand preview (Issue #365) ──────────────────────


class ParameterValidationResponse(BaseModel):
    """Result of validating an assembly's parameter graph.

    ``ok`` is True only when the graph has no structural problems (unique
    names, resolvable references, no cycles) AND resolves cleanly at the
    stored defaults. ``errors`` is the flat list of structured problems
    (``{scope, name, code, message}``) and ``resolved`` maps each parameter
    name to its Decimal-as-string value at the defaults.
    """

    ok: bool
    errors: list[dict[str, str]] = Field(default_factory=list)
    resolved: dict[str, str] = Field(default_factory=dict)


class ExpandPreviewRequest(BaseModel):
    """Request body for previewing an assembly expansion at given inputs."""

    parameter_values: dict[str, float] = Field(default_factory=dict)


class ExpandLine(BaseModel):
    """One expanded component line: its static vs formula-computed quantity.

    Money / quantity fields are Decimal-as-string (the module's money rule).
    ``static_quantity`` is the "before" (the stored per-unit quantity);
    ``computed_quantity`` is the "after" (the formula result at the supplied
    parameter values, or the static quantity when the line has no formula).
    """

    component_id: str | None = None
    description: str = ""
    unit: str = ""
    resource_type: str | None = None
    static_quantity: str = "0"
    computed_quantity: str = "0"
    unit_cost: str = "0"
    total: str = "0"


class ExpandPreviewResponse(BaseModel):
    """Server-authoritative expansion preview (Decimal-exact)."""

    resolved_parameters: dict[str, str] = Field(default_factory=dict)
    lines: list[ExpandLine] = Field(default_factory=list)
    total_rate: str = "0"
    errors: list[dict[str, str]] = Field(default_factory=list)


class CloneAssemblyRequest(BaseModel):
    """Request body for cloning an assembly."""

    new_code: str | None = Field(default=None, min_length=1, max_length=100)
    project_id: UUID | None = None


class ReorderComponentsRequest(BaseModel):
    """Request body for reordering components within an assembly."""

    component_ids: list[UUID] = Field(..., min_length=1, description="Ordered list of component IDs")


class AssemblyExport(BaseModel):
    """Full assembly export format for sharing/importing."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(..., min_length=1, max_length=20)
    category: str = Field(default="", max_length=100)
    classification: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(default="EUR", max_length=10)
    bid_factor: float = Field(default=1.0, ge=0.0, le=1e6, allow_inf_nan=False)
    regional_factors: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=100)
    # Issue #365 - carried through the export/import round-trip so a
    # parametric recipe stays parametric (validated on import).
    parameters: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    components: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class AssemblyImportRequest(BaseModel):
    """Request body for importing an assembly from JSON."""

    model_config = ConfigDict(extra="ignore")

    assembly: AssemblyExport


class AssemblyImportResponse(AssemblyResponse):
    """Imported assembly plus one warning per component imported unlinked."""

    warnings: list[str] = Field(default_factory=list)


# ── Assembly Library templates (v3.13.0 - Slice 1) ───────────────────────────


class AssemblyTemplateComponent(BaseModel):
    """One component inside a canonical assembly template.

    Catalogue-agnostic: the apply endpoint resolves ``cost_match_query``
    against the project's bound cost catalogue at runtime instead of
    storing a hard-coded ``cost_item_id``.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    cost_match_query: str = Field(..., min_length=1, max_length=500)
    factor: float = Field(default=1.0, ge=0.0, le=_NUM_MAX, allow_inf_nan=False)
    unit: str = Field(..., min_length=1, max_length=20)
    role: str = Field(default="material", max_length=20)
    description: str = Field(default="", max_length=500)


class AssemblyTemplateResponse(BaseModel):
    """An Assembly Library template row as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    name_translations: dict[str, str] = Field(default_factory=dict)
    category: str
    unit: str
    components: list[dict[str, Any]] = Field(default_factory=list)
    classification: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    is_builtin: bool = True
    component_count: int = 0
    created_at: datetime
    updated_at: datetime


class AssemblyTemplateSearchResponse(BaseModel):
    """Paginated search result for the Assembly Library."""

    items: list[AssemblyTemplateResponse]
    total: int
    limit: int
    offset: int


class ApplyTemplateRequest(BaseModel):
    """Request body for applying an Assembly Library template to a project."""

    model_config = ConfigDict(extra="ignore")

    project_id: UUID
    boq_position_id: UUID | None = None
    quantity: float = Field(default=1.0, gt=0.0, le=_NUM_MAX, allow_inf_nan=False)
    region: str | None = Field(default=None, max_length=64)
    language: str | None = Field(
        default=None,
        max_length=8,
        description="ISO-639-1 language hint for the cost match (en/de/ru/...)",
    )


class AppliedComponent(BaseModel):
    """A single component resolved against the project's cost catalogue.

    v3 §10 - ``unit_rate`` is money; Decimal-as-string in JSON. ``total``
    stays float here because the apply-template endpoint is a preview
    (the persisted line totals are written via the BOQ service which is
    already Decimal-correct).

    ``currency`` names the money ``unit_rate`` and ``total`` are in - the
    matched catalogue item's own code, which is not necessarily the response's
    target currency. Without it a row's figures were read under whatever code
    the response carried, which is how a component in one currency was shown
    as though it were in another.
    """

    description: str
    cost_match_query: str
    matched_cost_item_id: UUID | None = None
    matched_description: str = ""
    matched_code: str = ""
    factor: float = 0.0
    scaled_quantity: float = 0.0
    unit: str
    unit_rate: Decimal = Decimal("0")
    total: float = 0.0
    currency: str = ""
    converted_to_target: bool = False
    role: str = "material"
    match_confidence: float = 0.0
    match_channel: str = "lexical"

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CurrencySubtotal(BaseModel):
    """One currency's share of an apply preview, never mixed with another's.

    ``is_target`` marks the bucket holding the response's target currency -
    every component that could be converted lands there. Any other bucket is a
    residual: components the platform could not price into the target, kept in
    their own money so they are visible rather than folded into a number they
    do not belong to.
    """

    currency: str = ""
    amount: Decimal = Decimal("0")
    component_count: int = 0
    is_target: bool = False

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ApplyTemplateResponse(BaseModel):
    """Draft assembly returned by the apply endpoint.

    The draft is NOT persisted - the FE shows it for user review and a
    later POST creates the actual Assembly (or a BOQ position). That
    "preview-then-confirm" contract matches the existing
    ``/assemblies/ai-generate`` endpoint and the platform's
    human-confirms-AI rule.

    Money rule: a single scalar in this response never holds more than one
    currency. ``totals_by_currency`` is the authoritative figure and always
    carries the full picture. ``grand_total`` and ``total_rate`` are a
    convenience for the ordinary single-currency case and are ``None`` whenever
    the preview spans more than one currency - refusing to name a total is the
    only honest answer when part of it could not be priced into the target, and
    it is the answer that stays correct in a consumer which has not been taught
    about the breakdown yet.
    """

    template_id: UUID
    template_name: str
    project_id: UUID
    boq_position_id: UUID | None
    quantity: float
    unit: str
    currency: str = ""
    components: list[AppliedComponent] = Field(default_factory=list)
    totals_by_currency: list[CurrencySubtotal] = Field(default_factory=list)
    total_rate: float | None = None
    grand_total: Decimal | None = None
    unresolved_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_serializer("grand_total", when_used="json")
    def _ser_grand_total(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)
