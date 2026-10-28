# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic request/response schemas for the conceptual (ROM) estimate module.

A ROM (rough order-of-magnitude) estimate is the day-one starting point of a
project: from just the building type, the gross floor area, a quality level and
a region it returns a headline total, a six-element cost breakdown and an honest
accuracy band. The detailed estimating flow later refines it.

Monetary and ratio values follow the platform contract: they are Decimal in
Python and are emitted as plain decimal *strings* in JSON so large totals
round-trip without binary-float drift and stay locale-neutral. The
``_serialise_money`` helper below mirrors the same helper in the BOQ and 5D
Cost Model modules (each module keeps its own copy so it stays self-contained).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ── Decimal-as-string serialisation (mirrors boq / costmodel schemas) ────────
def _serialise_money(v: Decimal | None) -> str | None:
    """Render a Decimal as a plain decimal string for JSON, guarding non-finite.

    Args:
        v: The Decimal value (or ``None``).

    Returns:
        The value formatted with :func:`format` (``"f"``), ``"0"`` for a
        non-finite/unparseable value, or ``None`` when ``v`` is ``None``.
    """
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


# ── Request ──────────────────────────────────────────────────────────────────


class RomEstimateRequest(BaseModel):
    """Minimal input for an instant conceptual estimate.

    ``gross_floor_area`` may be supplied in any supported metric or imperial
    unit via ``gfa_unit``; it is converted to canonical m2 internally so the
    cost per m2 benchmark is comparable across projects. ``currency`` is an
    optional display label carried through to the result (the model stays
    currency-agnostic). ``name`` is only used when the estimate is saved.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    building_type: str = Field(..., max_length=60, description="Building-type key, e.g. 'office'.")
    gross_floor_area: Decimal = Field(..., gt=0, description="Gross floor area in 'gfa_unit'.")
    quality: str = Field(default="standard", max_length=40, description="Quality-level key.")
    region: str = Field(default="global", max_length=60, description="Region key (worldwide default 'global').")
    gfa_unit: str = Field(default="m2", max_length=20, description="Unit of 'gross_floor_area', e.g. m2 or ft2.")
    currency: str = Field(default="", max_length=10, description="Optional ISO currency label carried to the result.")
    name: str = Field(default="", max_length=255, description="Optional label used when the estimate is saved.")
    base_rate_per_m2_override: Decimal | None = Field(
        default=None,
        description=(
            "Optional base cost per m2, expressed in 'currency', that replaces the "
            "neutral reference basis so the headline total is anchored to the "
            "estimator's own rate. Quality and regional factors still apply on top. "
            "A missing or non-positive value keeps the building-type reference basis."
        ),
    )

    @field_serializer("gross_floor_area", "base_rate_per_m2_override", when_used="json")
    def _ser_qty(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class RomCreateBoqRequest(RomEstimateRequest):
    """Input to save a ROM estimate as the project baseline and seed a BOQ from it.

    Inherits every estimate input (building type, gross floor area, quality,
    region, unit, currency and the optional base-rate override) and adds the
    name for the bill of quantities that is created. The estimate is persisted
    as the conceptual baseline and a provisional BOQ is generated with one
    elemental section and one concept-rate line item per element.
    """

    boq_name: str = Field(default="", max_length=255, description="Optional name for the BOQ that is created.")


class RomCreateBoqResponse(BaseModel):
    """Result of seeding a provisional BOQ from a conceptual (ROM) estimate."""

    boq_id: str = Field(description="Id of the newly created bill of quantities.")
    estimate_id: str = Field(default="", description="Id of the conceptual baseline estimate that was saved.")
    sections_created: int = Field(description="Number of elemental sections created in the BOQ.")
    positions_created: int = Field(description="Number of provisional concept-rate positions created.")


# ── Result parts ─────────────────────────────────────────────────────────────


class RomElementBreakdown(BaseModel):
    """One elemental line of the breakdown (stable ``key`` for i18n)."""

    key: str = Field(description="Stable element key, e.g. 'services'.")
    label: str = Field(description="Default human label, e.g. 'Building services (MEP)'.")
    cost_share_pct: Decimal = Field(description="Share of the total for this element, as a percentage.")
    rate_per_m2: Decimal = Field(description="Quality- and region-adjusted cost per m2 for this element.")
    amount: Decimal = Field(description="Element total money (breakdown amounts sum to the headline total).")

    @field_serializer("cost_share_pct", "rate_per_m2", "amount", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class RomAccuracyBand(BaseModel):
    """Honest accuracy band around the point estimate.

    A ROM estimate is an order-of-magnitude figure; the band states how far the
    true cost may realistically fall from the point total. The band widens when
    no regional cost data is applied (region left at the worldwide default).
    """

    estimate_class: str = Field(description="Estimate class key, e.g. 'order_of_magnitude'.")
    estimate_class_label: str = Field(description="Default human label for the estimate class.")
    low_pct: Decimal = Field(description="Lower bound as a signed percentage of the total (e.g. -25).")
    high_pct: Decimal = Field(description="Upper bound as a signed percentage of the total (e.g. +40).")
    low_amount: Decimal = Field(description="Lower-bound money (total adjusted by low_pct).")
    high_amount: Decimal = Field(description="Upper-bound money (total adjusted by high_pct).")
    localized: bool = Field(description="True when a non-default region factor was applied.")
    note: str = Field(default="", description="Plain-language explanation of the band.")

    @field_serializer("low_pct", "high_pct", "low_amount", "high_amount", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class RomEstimateResult(BaseModel):
    """A full conceptual estimate: total, elemental breakdown and accuracy band."""

    building_type: str
    building_type_label: str
    quality: str
    quality_label: str
    region: str
    region_label: str
    currency: str = ""
    gross_floor_area: Decimal = Decimal("0")
    gfa_unit: str = "m2"
    gfa_canonical_m2: Decimal = Decimal("0")
    quality_factor: Decimal = Decimal("1")
    regional_factor: Decimal = Decimal("1")
    cost_per_m2: Decimal = Decimal("0")
    subtotal_base: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    accuracy: RomAccuracyBand
    elements: list[RomElementBreakdown] = Field(default_factory=list)
    notes: str = ""

    @field_serializer(
        "gross_floor_area",
        "gfa_canonical_m2",
        "quality_factor",
        "regional_factor",
        "cost_per_m2",
        "subtotal_base",
        "total",
        when_used="json",
    )
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Reference metadata (for populating UI dropdowns / help) ──────────────────


class RomBuildingTypeOption(BaseModel):
    """A selectable building type with its indicative base rate and band."""

    key: str
    label: str
    base_rate_per_m2: Decimal
    accuracy_low_pct: Decimal
    accuracy_high_pct: Decimal

    @field_serializer("base_rate_per_m2", "accuracy_low_pct", "accuracy_high_pct", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class RomFactorOption(BaseModel):
    """A selectable quality level or region with its multiplier."""

    key: str
    label: str
    factor: Decimal

    @field_serializer("factor", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class RomElementOption(BaseModel):
    """One of the six elemental categories (stable key + default label)."""

    key: str
    label: str


class RomReferenceResponse(BaseModel):
    """Everything the UI needs to build the conceptual-estimate form."""

    building_types: list[RomBuildingTypeOption]
    quality_levels: list[RomFactorOption]
    regions: list[RomFactorOption]
    elements: list[RomElementOption]
    default_quality: str = "standard"
    default_region: str = "global"
    reference_basis_note: str = ""


# ── Saved record (persistence) ───────────────────────────────────────────────


class RomEstimateRecord(BaseModel):
    """A ROM estimate persisted against a project."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str = ""
    building_type: str
    building_type_label: str
    quality: str
    region: str
    currency: str = ""
    gross_floor_area: Decimal = Decimal("0")
    gfa_unit: str = "m2"
    cost_per_m2: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    estimate_class: str = ""
    accuracy_low_pct: Decimal = Decimal("0")
    accuracy_high_pct: Decimal = Decimal("0")
    accuracy_low_amount: Decimal = Decimal("0")
    accuracy_high_amount: Decimal = Decimal("0")
    elements: list[RomElementBreakdown] = Field(default_factory=list)
    created_at: datetime | None = None
    created_by: UUID | None = None

    @field_serializer(
        "gross_floor_area",
        "cost_per_m2",
        "total",
        "accuracy_low_pct",
        "accuracy_high_pct",
        "accuracy_low_amount",
        "accuracy_high_amount",
        when_used="json",
    )
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Reconciliation (concept vs live detailed BOQ) ────────────────────────────


class RomReconciliation(BaseModel):
    """Read-side reconciliation of the conceptual total against the live BOQ.

    Compares the project's most-recent saved conceptual (ROM) total to the sum of
    its detailed BOQ grand totals (converted to the project base currency by the
    BOQ module's FX-aware rollup) and reports the drift, so the concept number
    stays a live benchmark through design development. This is classic
    design-development cost control: does the detailed design still track the
    number the whole project was approved on?

    Money and percentage values follow the platform contract: Decimal in Python,
    emitted as plain decimal strings in JSON. ``conceptual_total`` /
    ``variance_amount`` / ``variance_pct`` are ``null`` when there is no usable
    conceptual baseline to compare against (``status`` is then ``no_baseline``).
    """

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    status: str = Field(description="Reconciliation band: no_baseline | on_track | over | under.")
    conceptual_total: Decimal | None = Field(
        default=None, description="Most-recent saved conceptual total, or null when none is stored."
    )
    detailed_total: Decimal = Field(
        default=Decimal("0"), description="Sum of the project's BOQ grand totals in the base currency."
    )
    variance_amount: Decimal | None = Field(
        default=None, description="detailed_total - conceptual_total, or null with no baseline."
    )
    variance_pct: Decimal | None = Field(
        default=None, description="Variance as a signed percent of the conceptual total, or null."
    )
    tolerance_pct: Decimal = Field(
        default=Decimal("10"), description="On-track tolerance band (absolute percent) used for the status."
    )
    currency: str = Field(default="", description="Currency the reconciliation is expressed in (BOQ base currency).")
    conceptual_currency: str = Field(default="", description="Currency label stored on the conceptual estimate.")
    currency_mismatch: bool = Field(
        default=False, description="True when the two currencies differ, so the comparison mixes currencies."
    )
    boq_count: int = Field(default=0, description="Number of BOQs summed into the detailed total.")
    conceptual_estimate_id: UUID | None = Field(
        default=None, description="Id of the baseline conceptual estimate, or null."
    )
    conceptual_name: str = Field(default="", description="Name of the baseline conceptual estimate.")
    conceptual_created_at: datetime | None = Field(
        default=None, description="When the baseline conceptual estimate was saved."
    )

    @field_serializer(
        "conceptual_total",
        "detailed_total",
        "variance_amount",
        "variance_pct",
        "tolerance_pct",
        when_used="json",
    )
    def _ser(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)
