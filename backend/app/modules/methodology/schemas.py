# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Estimating-methodology Pydantic schemas - request / response models.

Covers the methodology template itself, its analytical dimensions (and their
values), funding sources, the cascade spec / steps, and the compute-estimate
request / response. Money and rates are stored / accepted as ``Decimal`` but
emitted as plain decimal strings in JSON, mirroring
:mod:`app.modules.boq.schemas` so neither SQLite Numeric precision loss nor JS
``Number`` digit loss can ever apply.

No ``extra='forbid'`` here - the sibling modules (boq, risk) do not set it, and
the methodology JSON blobs (hierarchy levels, dimension scheme, step metadata)
are intentionally open for forward-compatible extension.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ── Controlled vocabularies (single source of truth) ───────────────────────

# Where a methodology originates. Mirrors Methodology.scope.
SCOPE_VALUES: tuple[str, ...] = ("builtin", "project", "pack")
_SCOPE_PATTERN = r"^(?:builtin|project|pack)$"

# Cascade step kinds - kept in sync with cascade.KIND_PERCENTAGE / KIND_FIXED /
# KIND_GROSS_UP. "gross_up" is a rate levied on the total that already contains
# it, which is how Brazilian BDI carries PIS, COFINS and ISS.
STEP_KINDS: tuple[str, ...] = ("percentage", "fixed", "gross_up")
_STEP_KIND_PATTERN = r"^(?:percentage|fixed|gross_up)$"

# Dimension kinds - kept in sync with AnalyticDimension.kind.
DIMENSION_KINDS: tuple[str, ...] = ("flat", "tree")
_DIMENSION_KIND_PATTERN = r"^(?:flat|tree)$"


# ── Money / rate serialisation helper ──────────────────────────────────────
# Identical contract to backend/app/modules/boq/schemas.py: a Decimal in, a
# plain decimal string out (never scientific notation), with a safe "0" for
# non-finite / unparseable values so one bad row never breaks a response.
def _serialise_money(v: Decimal | str | None) -> str | None:
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


# ── Cascade step ────────────────────────────────────────────────────────────


class MarkupStepSchema(BaseModel):
    """One ordered markup step in a methodology cascade.

    ``base`` lists the tokens this step applies to - each a leaf base key, a
    composite name, or the key of an EARLIER step. ``rate`` is a percentage
    (used when ``kind == 'percentage'``); ``amount`` is a fixed value (used when
    ``kind == 'fixed'``). Both are emitted as decimal strings.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(default="", max_length=255)
    category: str = Field(default="other", max_length=40)
    kind: str = Field(default="percentage", pattern=_STEP_KIND_PATTERN)
    rate: Decimal = Field(default=Decimal("0"))
    amount: Decimal = Field(default=Decimal("0"))
    base: list[str] = Field(default_factory=list)

    @field_serializer("rate", "amount", when_used="json")
    def _ser_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Analytical dimensions ───────────────────────────────────────────────────


class DimensionValueCreate(BaseModel):
    """Create one value within an analytical dimension."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=255)
    parent_code: str | None = Field(default=None, max_length=80)
    sort_order: int = Field(default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DimensionValueResponse(BaseModel):
    """A dimension value returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    dimension_id: UUID
    parent_id: UUID | None = None
    code: str
    label: str
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


class DimensionCreate(BaseModel):
    """Create an analytical dimension under a project (and/or methodology)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    methodology_slug: str | None = Field(default=None, max_length=80)
    key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(default="flat", pattern=_DIMENSION_KIND_PATTERN)
    is_required: bool = False
    sort_order: int = Field(default=0)
    values: list[DimensionValueCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DimensionResponse(BaseModel):
    """An analytical dimension returned from the API, with its values."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    methodology_slug: str | None = None
    key: str
    label: str
    kind: str = "flat"
    is_required: bool = False
    sort_order: int = 0
    values: list[DimensionValueResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


# ── Funding sources ──────────────────────────────────────────────────────────


class FundingSourceCreate(BaseModel):
    """Create a funding-source master entry for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    sort_order: int = Field(default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FundingSourceUpdate(BaseModel):
    """Partial update for a funding source."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class FundingSourceResponse(BaseModel):
    """A funding source returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    code: str
    name: str
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


# ── Methodology ──────────────────────────────────────────────────────────────


class MethodologyBase(BaseModel):
    """Fields shared by create / update / response for a methodology."""

    # ``populate_by_name`` lets create/update bodies keep using the field name
    # ``metadata`` while the response reads the ORM attribute through the
    # ``metadata_`` alias below. The column is ``metadata`` but SQLAlchemy
    # reserves the ``metadata`` attribute for its registry, so the model maps it
    # to ``metadata_``; without the alias, ``from_attributes`` read the
    # SQLAlchemy ``MetaData`` object and every methodology get/create/update
    # 500'd on serialization.
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    country_code: str | None = Field(default=None, max_length=8)
    industry: str | None = Field(default=None, max_length=64)
    currency: str = Field(default="", max_length=8)
    decimals: int = Field(default=2, ge=0, le=8)
    hierarchy_levels: list[dict[str, Any]] = Field(default_factory=list)
    dimension_scheme: list[dict[str, Any]] = Field(default_factory=list)
    column_preset: str | None = Field(default=None, max_length=64)
    base_mapping: dict[str, list[str]] = Field(default_factory=dict)
    composites: dict[str, list[str]] = Field(default_factory=dict)
    cascade_steps: list[MarkupStepSchema] = Field(default_factory=list)
    # A catalogue fact about a country, not the rate this methodology charges.
    # Nothing prices from it. The ``tax`` step inside ``cascade_steps`` is what
    # computes, and a project that states its own rate replaces that step, so
    # read ``effective_vat`` on the response for the figure actually applied.
    vat_rate: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")

    @field_serializer("vat_rate", when_used="json")
    def _ser_vat(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class MethodologyCreate(MethodologyBase):
    """Create a project-scoped methodology.

    ``project_id`` is required: a methodology created through the API is always
    a project-local clone (``scope='project'``). Built-ins and packs are seeded
    by the platform, never minted through this endpoint.
    """

    project_id: UUID
    # Optional caller-supplied slug; the service generates a unique one (scoped
    # by project) when omitted so two projects can both hold a "my-method".
    slug: str | None = Field(default=None, min_length=1, max_length=80)


class MethodologyUpdate(BaseModel):
    """Partial update for a methodology (project-scoped, editable only)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    country_code: str | None = Field(default=None, max_length=8)
    industry: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, max_length=8)
    decimals: int | None = Field(default=None, ge=0, le=8)
    hierarchy_levels: list[dict[str, Any]] | None = None
    dimension_scheme: list[dict[str, Any]] | None = None
    column_preset: str | None = Field(default=None, max_length=64)
    base_mapping: dict[str, list[str]] | None = None
    composites: dict[str, list[str]] | None = None
    cascade_steps: list[MarkupStepSchema] | None = None
    vat_rate: Decimal | None = None
    metadata: dict[str, Any] | None = None

    @field_serializer("vat_rate", when_used="json")
    def _ser_vat(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class EffectiveVat(BaseModel):
    """The consumption-tax rate this methodology is priced at, and where it came from.

    The stored cascade is not always the cascade that prices. When a project
    states a ``default_vat_rate`` and the stack carries exactly one tax line,
    the computation substitutes the project's rate, because VAT is a property
    of the transaction rather than of the method and one bill asked two ways
    cannot cost two amounts. Everything downstream of the computation reports
    the substituted figure honestly; without this block the read side would
    not, and a screen showing nought would belong to a bill costed at 25.

    It names the source as well as the rate so a reader can be told why, not
    merely that. The comparison against the stored figure is made here rather
    than by each caller: the rule for when a single project rate may stand in
    for a stack is stated once, in
    :meth:`~app.modules.methodology.service.MethodologyService._single_tax_index`,
    and a screen that recomputed it would be free to drift from the engine.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # The rate that will actually be applied, or None when the stack carries no
    # single tax line and so no one figure can be named for it.
    rate: Decimal | None = None
    # ``project`` when the project's own rate is substituted, ``methodology``
    # when the stack's own tax line stands, ``none`` when there is no single
    # tax line to speak about. Never guess a fourth meaning from a null rate.
    source: Literal["project", "methodology", "none"] = "none"
    # What the stored cascade says, so a reader can be shown both figures
    # without fetching the steps and reasoning about them again.
    stored_rate: Decimal | None = None
    # True only when the priced rate and the stored rate genuinely differ. A
    # project whose rate equals the template's is not an override worth
    # announcing, which is why this is a comparison and not `source ==
    # "project"`.
    differs_from_stored: bool = False

    @field_serializer("rate", "stored_rate", when_used="json")
    def _ser_rates(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class MethodologyResponse(MethodologyBase):
    """A methodology returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    slug: str
    scope: str = "builtin"
    project_id: UUID | None = None
    is_builtin: bool = False
    is_editable: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Populated on the reads that know which project is asking. Absent means
    # the question was not asked on this endpoint, never that no VAT applies:
    # the list rows carry no cascade at all, so there is nothing for a rate to
    # qualify there.
    effective_vat: EffectiveVat | None = None


class MethodologyListItem(BaseModel):
    """Compact methodology row for list endpoints."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    slug: str
    scope: str
    project_id: UUID | None = None
    country_code: str | None = None
    industry: str | None = None
    name: str
    currency: str = ""
    is_builtin: bool = False
    is_editable: bool = True


class TemplateListItem(BaseModel):
    """A built-in template descriptor (catalogue listing, not yet installed)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str
    name: str
    description: str = ""
    country_code: str | None = None
    industry: str | None = None
    currency: str = ""
    step_count: int = 0


class InstallTemplateRequest(BaseModel):
    """Install a built-in template into a project as a project-scoped clone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    template_slug: str = Field(..., min_length=1, max_length=80)
    # When True (default) re-installing an already-installed template returns
    # the existing clone untouched; when False a fresh suffixed clone is made.
    idempotent: bool = True
    # When True, also activate the methodology on the project after install.
    set_active: bool = False


# ── Compute estimate ─────────────────────────────────────────────────────────


class ResourceTotals(BaseModel):
    """Money summed per resource type for one scope (a whole BOQ or a node).

    The keys are resource-type strings (e.g. ``labor`` / ``material`` /
    ``machinery`` / ``equipment`` / ``subcontractor``); the methodology's
    ``base_mapping`` maps these onto the cascade's leaf base tokens. Values are
    Decimal money in the methodology currency (never blended across
    currencies).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # Free-form resource-type -> amount. Kept permissive (any string key) so a
    # template can introduce new resource types without a schema change.
    totals: dict[str, Decimal] = Field(default_factory=dict)


class ComputeEstimateRequest(BaseModel):
    """Request to compute a cascade for a project under a chosen methodology.

    Exactly one source of resource totals is used, in priority order:
      1. ``resource_totals`` if given (caller-supplied, already aggregated).
      2. Otherwise the service aggregates the project's BOQ resources itself.

    ``methodology_slug`` overrides the project's active methodology for a
    what-if computation; when omitted the project's active methodology (or the
    international default) is used.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    methodology_slug: str | None = Field(default=None, max_length=80)
    boq_id: UUID | None = None
    resource_totals: dict[str, Decimal] | None = None


class StepResultSchema(BaseModel):
    """The computed outcome of one cascade step."""

    model_config = ConfigDict(str_strip_whitespace=True)

    key: str
    label: str
    category: str
    kind: str
    rate: Decimal = Decimal("0")
    base_amount: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    running_total: Decimal = Decimal("0")

    @field_serializer("rate", "base_amount", "amount", "running_total", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ComputeEstimateResponse(BaseModel):
    """The full result of computing a methodology cascade for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    methodology_slug: str
    currency: str = ""
    decimals: int = 2
    bases: dict[str, Decimal] = Field(default_factory=dict)
    composites: dict[str, Decimal] = Field(default_factory=dict)
    steps: list[StepResultSchema] = Field(default_factory=list)
    direct_total: Decimal = Decimal("0")
    markup_total: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")

    @field_serializer("bases", "composites", when_used="json")
    def _ser_amount_map(self, v: dict[str, Decimal]) -> dict[str, str]:
        return {k: (_serialise_money(amt) or "0") for k, amt in v.items()}

    @field_serializer("direct_total", "markup_total", "grand_total", when_used="json")
    def _ser_totals(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# Re-export the literal helpers some callers may want for validation.
ScopeLiteral = Literal["builtin", "project", "pack"]
