# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Carbon & Sustainability Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── EPD Record ────────────────────────────────────────────────────────────


class EPDRecordCreate(BaseModel):
    """Create an EPD record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_catalog_item_id: UUID | None = None
    epd_format: str | None = Field(default=None, max_length=16)
    epd_id: str = Field(..., min_length=1, max_length=120)
    source: str = Field(
        default="custom",
        pattern=r"^(oekobaudat|ice|ec3|epd_international|custom)$",
    )
    material_class: str = Field(..., min_length=1, max_length=80)
    product_name: str = Field(..., min_length=1, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=255)
    region: str = Field(default="", max_length=8)
    declared_unit: str = Field(default="kg", max_length=20)
    gwp_a1a3: Decimal = Field(default=Decimal("0"))
    gwp_a4: Decimal | None = None
    gwp_a5: Decimal | None = None
    gwp_b_total: Decimal | None = None
    gwp_c_total: Decimal | None = None
    gwp_d_credits: Decimal | None = None
    validity_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EPDRecordUpdate(BaseModel):
    """Partial update of an EPD record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_catalog_item_id: UUID | None = None
    epd_format: str | None = Field(default=None, max_length=16)
    source: str | None = Field(
        default=None,
        pattern=r"^(oekobaudat|ice|ec3|epd_international|custom)$",
    )
    material_class: str | None = Field(default=None, max_length=80)
    product_name: str | None = Field(default=None, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=8)
    declared_unit: str | None = Field(default=None, max_length=20)
    gwp_a1a3: Decimal | None = None
    gwp_a4: Decimal | None = None
    gwp_a5: Decimal | None = None
    gwp_b_total: Decimal | None = None
    gwp_c_total: Decimal | None = None
    gwp_d_credits: Decimal | None = None
    validity_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] | None = None


class EPDRecordResponse(BaseModel):
    """EPD record returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    supplier_catalog_item_id: UUID | None = None
    epd_format: str | None = None
    id: UUID
    epd_id: str
    source: str
    material_class: str
    product_name: str
    manufacturer: str | None = None
    region: str
    declared_unit: str
    gwp_a1a3: Decimal
    gwp_a4: Decimal | None = None
    gwp_a5: Decimal | None = None
    gwp_b_total: Decimal | None = None
    gwp_c_total: Decimal | None = None
    gwp_d_credits: Decimal | None = None
    validity_until: date | None = None
    document_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Material Carbon Factor ────────────────────────────────────────────────


class MaterialCarbonFactorCreate(BaseModel):
    """Create a material carbon factor."""

    factor_set: str | None = Field(default=None, max_length=80)
    factor_set_year: int | None = Field(default=None, ge=1990, le=2100)
    cost_item_id: UUID | None = None
    epd_id: UUID | None = None
    manual_override_factor: Decimal | None = None
    unit_for_factor: str = Field(default="kg", max_length=20)
    region: str = Field(default="", max_length=8)
    last_reviewed_at: date | None = None
    confidence: str = Field(default="medium", pattern=r"^(high|medium|low)$")
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaterialCarbonFactorUpdate(BaseModel):
    """Partial update of a material carbon factor."""

    factor_set: str | None = Field(default=None, max_length=80)
    factor_set_year: int | None = Field(default=None, ge=1990, le=2100)
    cost_item_id: UUID | None = None
    epd_id: UUID | None = None
    manual_override_factor: Decimal | None = None
    unit_for_factor: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=8)
    last_reviewed_at: date | None = None
    confidence: str | None = Field(default=None, pattern=r"^(high|medium|low)$")
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class MaterialCarbonFactorResponse(BaseModel):
    """Material carbon factor returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    factor_set: str | None = None
    factor_set_year: int | None = None
    id: UUID
    cost_item_id: UUID | None = None
    epd_id: UUID | None = None
    manual_override_factor: Decimal | None = None
    unit_for_factor: str
    region: str
    last_reviewed_at: date | None = None
    confidence: str
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Carbon Inventory ─────────────────────────────────────────────────────


class CarbonInventoryCreate(BaseModel):
    """Create a carbon inventory."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="Baseline inventory", max_length=255)
    scope: str = Field(
        default="cradle_to_gate",
        pattern=r"^(cradle_to_gate|cradle_to_grave|operational)$",
    )
    as_of_date: date | None = None
    status: str = Field(
        default="draft",
        pattern=r"^(draft|baseline|current|archived)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CarbonInventoryUpdate(BaseModel):
    """Partial update of an inventory."""

    name: str | None = Field(default=None, max_length=255)
    scope: str | None = Field(
        default=None,
        pattern=r"^(cradle_to_gate|cradle_to_grave|operational)$",
    )
    as_of_date: date | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|baseline|current|archived)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class CarbonInventoryResponse(BaseModel):
    """Carbon inventory returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    scope: str
    as_of_date: date | None = None
    status: str
    totals: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Embodied Carbon Entry ─────────────────────────────────────────────────


class EmbodiedCarbonEntryCreate(BaseModel):
    """Create an embodied-carbon entry."""

    data_quality: str = Field(default="calculated", pattern=r"^(measured|calculated|estimated)$")
    inventory_id: UUID
    element_ref: str | None = Field(default=None, max_length=255)
    element_id: UUID | None = None
    description: str = Field(default="", max_length=10000)
    quantity: Decimal = Field(default=Decimal("0"))
    unit: str = Field(default="kg", max_length=20)
    factor_id: UUID | None = None
    factor_value_used: Decimal = Field(default=Decimal("0"))
    carbon_kg: Decimal = Field(default=Decimal("0"))
    stage: str = Field(default="a1a3", pattern=r"^(a1a3|a4|a5|b|c|d)$")
    source: str = Field(default="manual", pattern=r"^(manual|auto_enriched|boq_derived)$")
    match_confidence: str | None = Field(default=None, pattern=r"^(high|medium|low)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbodiedCarbonEntryUpdate(BaseModel):
    """Partial update of an embodied-carbon entry."""

    data_quality: str | None = Field(default=None, pattern=r"^(measured|calculated|estimated)$")
    element_ref: str | None = Field(default=None, max_length=255)
    element_id: UUID | None = None
    description: str | None = Field(default=None, max_length=10000)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=20)
    factor_id: UUID | None = None
    factor_value_used: Decimal | None = None
    carbon_kg: Decimal | None = None
    stage: str | None = Field(default=None, pattern=r"^(a1a3|a4|a5|b|c|d)$")
    source: str | None = Field(default=None, pattern=r"^(manual|auto_enriched|boq_derived)$")
    match_confidence: str | None = Field(default=None, pattern=r"^(high|medium|low)$")
    metadata: dict[str, Any] | None = None


class EmbodiedCarbonEntryResponse(BaseModel):
    """Embodied entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    data_quality: str = "calculated"
    id: UUID
    inventory_id: UUID
    element_ref: str | None = None
    element_id: UUID | None = None
    description: str
    quantity: Decimal
    unit: str
    factor_id: UUID | None = None
    factor_value_used: Decimal
    carbon_kg: Decimal
    stage: str
    source: str = "manual"
    match_confidence: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EmbodiedBulkCreate(BaseModel):
    """Bulk create payload."""

    entries: list[EmbodiedCarbonEntryCreate] = Field(default_factory=list)


# ── Scope 1 / 2 / 3 ───────────────────────────────────────────────────────


class Scope1EntryCreate(BaseModel):
    """Create a scope-1 (direct) emission entry."""

    data_quality: str = Field(default="calculated", pattern=r"^(measured|calculated|estimated)$")
    inventory_id: UUID
    period_start: date
    period_end: date
    fuel_type: str = Field(
        default="diesel",
        pattern=r"^(diesel|petrol|lpg|natural_gas|other)$",
    )
    litres_or_m3: Decimal = Field(default=Decimal("0"))
    emission_factor_kg_co2e_per_unit: Decimal = Field(default=Decimal("0"))
    total_co2e_kg: Decimal | None = None
    source: str = Field(
        default="manual",
        pattern=r"^(equipment_telematics|fuel_log|manual)$",
    )
    source_ref: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope1EntryUpdate(BaseModel):
    """Partial update of a scope-1 entry."""

    data_quality: str | None = Field(default=None, pattern=r"^(measured|calculated|estimated)$")
    period_start: date | None = None
    period_end: date | None = None
    fuel_type: str | None = Field(
        default=None,
        pattern=r"^(diesel|petrol|lpg|natural_gas|other)$",
    )
    litres_or_m3: Decimal | None = None
    emission_factor_kg_co2e_per_unit: Decimal | None = None
    total_co2e_kg: Decimal | None = None
    source: str | None = Field(
        default=None,
        pattern=r"^(equipment_telematics|fuel_log|manual)$",
    )
    source_ref: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class Scope1EntryResponse(BaseModel):
    """Scope-1 entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    data_quality: str = "calculated"
    id: UUID
    inventory_id: UUID
    period_start: date
    period_end: date
    fuel_type: str
    litres_or_m3: Decimal
    emission_factor_kg_co2e_per_unit: Decimal
    total_co2e_kg: Decimal
    source: str
    source_ref: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class Scope2EntryCreate(BaseModel):
    """Create a scope-2 (purchased-energy) emission entry."""

    data_quality: str = Field(default="calculated", pattern=r"^(measured|calculated|estimated)$")
    inventory_id: UUID
    period_start: date
    period_end: date
    energy_type: str = Field(
        default="grid_electricity",
        pattern=r"^(grid_electricity|district_heating|cooling)$",
    )
    kwh: Decimal = Field(default=Decimal("0"))
    emission_factor_kg_co2e_per_kwh: Decimal = Field(default=Decimal("0"))
    market_or_location: str = Field(default="location", pattern=r"^(market|location)$")
    total_co2e_kg: Decimal | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope2EntryUpdate(BaseModel):
    """Partial update of a scope-2 entry."""

    data_quality: str | None = Field(default=None, pattern=r"^(measured|calculated|estimated)$")
    period_start: date | None = None
    period_end: date | None = None
    energy_type: str | None = Field(
        default=None,
        pattern=r"^(grid_electricity|district_heating|cooling)$",
    )
    kwh: Decimal | None = None
    emission_factor_kg_co2e_per_kwh: Decimal | None = None
    market_or_location: str | None = Field(default=None, pattern=r"^(market|location)$")
    total_co2e_kg: Decimal | None = None
    supplier_name: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class Scope2EntryResponse(BaseModel):
    """Scope-2 entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    data_quality: str = "calculated"
    id: UUID
    inventory_id: UUID
    period_start: date
    period_end: date
    energy_type: str
    kwh: Decimal
    emission_factor_kg_co2e_per_kwh: Decimal
    market_or_location: str
    total_co2e_kg: Decimal
    supplier_name: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class Scope3EntryCreate(BaseModel):
    """Create a scope-3 (other) emission entry."""

    data_quality: str = Field(default="calculated", pattern=r"^(measured|calculated|estimated)$")
    inventory_id: UUID
    period_start: date
    period_end: date
    category: str = Field(
        default="transport_upstream",
        pattern=r"^(transport_upstream|transport_downstream|waste|business_travel|other)$",
    )
    description: str = Field(default="", max_length=10000)
    activity_data: Decimal = Field(default=Decimal("0"))
    activity_unit: str = Field(default="tkm", max_length=40)
    emission_factor: Decimal = Field(default=Decimal("0"))
    total_co2e_kg: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope3EntryUpdate(BaseModel):
    """Partial update of a scope-3 entry."""

    data_quality: str | None = Field(default=None, pattern=r"^(measured|calculated|estimated)$")
    period_start: date | None = None
    period_end: date | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(transport_upstream|transport_downstream|waste|business_travel|other)$",
    )
    description: str | None = Field(default=None, max_length=10000)
    activity_data: Decimal | None = None
    activity_unit: str | None = Field(default=None, max_length=40)
    emission_factor: Decimal | None = None
    total_co2e_kg: Decimal | None = None
    metadata: dict[str, Any] | None = None


class Scope3EntryResponse(BaseModel):
    """Scope-3 entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    data_quality: str = "calculated"
    id: UUID
    inventory_id: UUID
    period_start: date
    period_end: date
    category: str
    description: str
    activity_data: Decimal
    activity_unit: str
    emission_factor: Decimal
    total_co2e_kg: Decimal
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Targets ──────────────────────────────────────────────────────────────


class CarbonTargetCreate(BaseModel):
    """Create a carbon-reduction target."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    target_type: str = Field(
        default="absolute",
        pattern=r"^(intensity_per_m2|intensity_per_unit|absolute)$",
    )
    baseline_value: Decimal = Field(default=Decimal("0"))
    target_value: Decimal = Field(default=Decimal("0"))
    baseline_year: int = Field(default=2020, ge=1990, le=2100)
    target_year: int = Field(default=2030, ge=1990, le=2100)
    scope_set: list[str] = Field(default_factory=list)
    status: str = Field(
        default="active",
        pattern=r"^(active|met|missed|abandoned)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CarbonTargetUpdate(BaseModel):
    """Partial update of a target."""

    name: str | None = Field(default=None, max_length=255)
    target_type: str | None = Field(
        default=None,
        pattern=r"^(intensity_per_m2|intensity_per_unit|absolute)$",
    )
    baseline_value: Decimal | None = None
    target_value: Decimal | None = None
    baseline_year: int | None = Field(default=None, ge=1990, le=2100)
    target_year: int | None = Field(default=None, ge=1990, le=2100)
    scope_set: list[str] | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(active|met|missed|abandoned)$",
    )
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class CarbonTargetResponse(BaseModel):
    """Target returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    target_type: str
    baseline_value: Decimal
    target_value: Decimal
    baseline_year: int
    target_year: int
    scope_set: list[str] = Field(default_factory=list)
    status: str
    notes: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class TargetProgressResponse(BaseModel):
    """Progress snapshot for a target."""

    target_id: UUID
    current_value: Decimal
    baseline_value: Decimal
    target_value: Decimal
    progress_pct: float
    met: bool
    as_of_date: date | None = None


# ── Sustainability Report ────────────────────────────────────────────────


class SustainabilityReportCreate(BaseModel):
    """Create a sustainability report record (manual)."""

    project_id: UUID
    inventory_id: UUID | None = None
    period_start: date
    period_end: date
    framework: str = Field(
        default="ghg_protocol",
        pattern=r"^(ghg_protocol|gri|issb|custom)$",
    )
    totals: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SustainabilityReportUpdate(BaseModel):
    """Partial update of a sustainability report."""

    inventory_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    framework: str | None = Field(
        default=None,
        pattern=r"^(ghg_protocol|gri|issb|custom)$",
    )
    totals: dict[str, Any] | None = None
    narrative: str | None = None
    metadata: dict[str, Any] | None = None


class SustainabilityReportResponse(BaseModel):
    """Sustainability report returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    inventory_id: UUID | None = None
    period_start: date
    period_end: date
    framework: str
    totals: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    generated_at: date | None = None
    generated_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class SustainabilityReportPayload(BaseModel):
    """Request to generate a sustainability report."""

    project_id: UUID
    inventory_id: UUID | None = None
    period_start: date
    period_end: date
    framework: str = Field(
        default="ghg_protocol",
        pattern=r"^(ghg_protocol|gri|issb|custom)$",
    )
    project_area_m2: Decimal | None = None
    narrative: str | None = None


# ── Computed views ───────────────────────────────────────────────────────


class InventoryTotalsResponse(BaseModel):
    """Fresh totals for an inventory.

    Every carbon figure below is in ``unit`` (kgCO2e). ``basis`` is a
    plain-language, line-by-line explanation of how ``total`` was built, so the
    number is auditable without opening the code.
    """

    inventory_id: UUID
    unit: str = Field(default="kgCO2e")
    embodied_a1a3: Decimal = Field(default=Decimal("0"))
    embodied_a4: Decimal = Field(default=Decimal("0"))
    embodied_a5: Decimal = Field(default=Decimal("0"))
    embodied_a1a5: Decimal = Field(default=Decimal("0"))
    embodied_b: Decimal = Field(default=Decimal("0"))
    embodied_c: Decimal = Field(default=Decimal("0"))
    embodied_d: Decimal = Field(default=Decimal("0"))
    # B6 use-phase operational carbon (6D Phase 2), already folded into
    # embodied_b (the full EN 15978 B stage) and into total.
    b6_operational: Decimal = Field(default=Decimal("0"))
    scope1: Decimal = Field(default=Decimal("0"))
    scope2: Decimal = Field(default=Decimal("0"))
    scope3: Decimal = Field(default=Decimal("0"))
    operational: Decimal = Field(default=Decimal("0"))
    end_of_life: Decimal = Field(default=Decimal("0"))
    total: Decimal = Field(default=Decimal("0"))
    basis: list[str] = Field(default_factory=list)


class AlternativeMaterialOption(BaseModel):
    """A single alternative-material option."""

    factor_id: UUID
    factor_value: Decimal
    carbon_kg: Decimal
    savings_kg: Decimal
    savings_pct: float
    confidence: str


class AlternativeComparisonResponse(BaseModel):
    """Alternative-materials comparison for one embodied entry."""

    entry_id: UUID
    current_factor_value: Decimal
    current_carbon_kg: Decimal
    options: list[AlternativeMaterialOption] = Field(default_factory=list)


class CarbonDashboardResponse(BaseModel):
    """Project carbon dashboard payload."""

    project_id: UUID
    total_embodied_kg: Decimal = Field(default=Decimal("0"))
    total_operational_kg: Decimal = Field(default=Decimal("0"))
    total_kg: Decimal = Field(default=Decimal("0"))
    inventory_count: int = 0
    target_count: int = 0
    targets_met: int = 0
    targets_missed: int = 0
    intensity_per_m2: Decimal | None = None
    latest_report_id: UUID | None = None


# ── 6D Phase 2: operational carbon (B6 use-phase) ─────────────────────────


class OperationalCarbonComputeRequest(BaseModel):
    """Request to compute B6 operational carbon for an inventory's BIM.

    The grid factor (in kgCO2e per kWh) is resolved most-trustworthy first: an
    explicit ``grid_factor_kg_co2e_per_kwh`` override, else the built-in country
    / year catalogue, else the average of the inventory's Scope-2 entries, else
    the IEA world-average intensity when a country outside the catalogue is
    named (flagged as a low-confidence global default). Per-asset lines come
    from elements carrying an energy signal (annual energy, or a rated power x
    run hours). A single modelled whole-building line is added only when both
    ``gross_floor_area_m2`` and ``modelled_intensity_kwh_per_m2_year`` are
    supplied.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    model_id: UUID | None = None
    grid_country: str = Field(default="", max_length=8)
    grid_year: int = Field(default=2023, ge=2000, le=2100)
    grid_factor_kg_co2e_per_kwh: Decimal | None = Field(default=None, ge=0)
    study_period_years: int = Field(default=60, ge=1, le=200)
    end_use: str = Field(default="regulated", pattern=r"^(regulated|unregulated|mixed)$")
    gross_floor_area_m2: Decimal | None = Field(default=None, ge=0)
    modelled_intensity_kwh_per_m2_year: Decimal | None = Field(default=None, ge=0)


class OperationalCarbonEntryResponse(BaseModel):
    """Operational-carbon (B6) entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inventory_id: UUID
    element_id: UUID | None = None
    element_ref: str | None = None
    system: str
    description: str
    end_use: str
    energy_source: str
    annual_energy_kwh: Decimal
    grid_country: str
    grid_year: int | None = None
    grid_factor_kg_co2e_per_kwh: Decimal
    study_period_years: int
    annual_carbon_kg: Decimal
    carbon_kg: Decimal
    stage: str
    source: str
    match_confidence: str | None = None
    status: str
    assumptions: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class OperationalCarbonComputeResponse(BaseModel):
    """Result of an operational-carbon compute run (dry-run or persisted)."""

    inventory_id: UUID
    model_id: UUID | None = None
    dry_run: bool
    study_period_years: int
    grid_factor_kg_co2e_per_kwh: Decimal
    grid_factor_source: str
    created: int = 0
    skipped_existing: int = 0
    skipped_no_energy: int = 0
    total_b6_carbon_kg: Decimal = Field(default=Decimal("0"))
    entries: list[dict[str, Any]] = Field(default_factory=list)


# ── 6D Phase 2: whole-life cost (ISO 15686-5) ─────────────────────────────


class LCCLineInput(BaseModel):
    """A single explicit whole-life cost line (non-BIM manual entry)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=80)
    capex: Decimal = Field(default=Decimal("0"), ge=0)
    annual_opex: Decimal | None = Field(default=None, ge=0)
    replacement_cost: Decimal | None = Field(default=None, ge=0)
    service_life_years: int | None = Field(default=None, ge=1, le=200)
    eol_cost: Decimal | None = Field(default=None, ge=0)


class LifeCycleCostComputeRequest(BaseModel):
    """Request to compute ISO 15686-5 whole-life cost for an inventory.

    Per-element lines are derived from the project's BIM asset register (service
    life and any cost fields on ``asset_info``, with modelled fallbacks). Any
    explicit ``lines`` are costed too (additive; useful without BIM cost data).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    model_id: UUID | None = None
    discount_rate: Decimal = Field(default=Decimal("0.035"), ge=0, le=1)
    study_period_years: int = Field(default=60, ge=1, le=200)
    currency: str = Field(default="EUR", max_length=8)
    default_capex: Decimal | None = Field(default=None, ge=0)
    opex_rate_pct: Decimal = Field(default=Decimal("2.0"), ge=0, le=100)
    eol_rate_pct: Decimal = Field(default=Decimal("10.0"), ge=0, le=100)
    default_service_life_years: int = Field(default=30, ge=1, le=200)
    lines: list[LCCLineInput] = Field(default_factory=list)


class LifeCycleCostEntryResponse(BaseModel):
    """Whole-life cost entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inventory_id: UUID
    element_id: UUID | None = None
    element_ref: str | None = None
    description: str
    category: str
    currency: str
    capex: Decimal
    annual_opex: Decimal
    replacement_cost: Decimal
    service_life_years: int
    eol_cost: Decimal
    discount_rate: Decimal
    study_period_years: int
    capex_pv: Decimal
    opex_pv: Decimal
    replacement_pv: Decimal
    replacement_count: int
    eol_pv: Decimal
    whole_life_cost: Decimal
    source: str
    confidence: str | None = None
    status: str
    assumptions: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class LifeCycleCostComputeResponse(BaseModel):
    """Result of a whole-life cost compute run (dry-run or persisted)."""

    inventory_id: UUID
    model_id: UUID | None = None
    dry_run: bool
    currency: str
    discount_rate: Decimal
    study_period_years: int
    created: int = 0
    skipped_existing: int = 0
    skipped_no_cost: int = 0
    total_whole_life_cost: Decimal = Field(default=Decimal("0"))
    entries: list[dict[str, Any]] = Field(default_factory=list)


# ── 6D Phase 2: combined whole-life rollup (carbon + cost side by side) ────


class WholeLifeCarbonBreakdown(BaseModel):
    """EN 15978 whole-life carbon A-B-C-D breakdown (kgCO2e)."""

    a1a3: Decimal = Field(default=Decimal("0"))
    a4: Decimal = Field(default=Decimal("0"))
    a5: Decimal = Field(default=Decimal("0"))
    a1a5: Decimal = Field(default=Decimal("0"))
    b_embodied: Decimal = Field(default=Decimal("0"))
    b6_operational: Decimal = Field(default=Decimal("0"))
    b_total: Decimal = Field(default=Decimal("0"))
    c_end_of_life: Decimal = Field(default=Decimal("0"))
    d_beyond: Decimal = Field(default=Decimal("0"))
    whole_life_total: Decimal = Field(default=Decimal("0"))


class WholeLifeCostBreakdown(BaseModel):
    """ISO 15686-5 whole-life cost breakdown (present values)."""

    currency: str = "EUR"
    capex: Decimal = Field(default=Decimal("0"))
    opex_pv: Decimal = Field(default=Decimal("0"))
    replacement_pv: Decimal = Field(default=Decimal("0"))
    eol_pv: Decimal = Field(default=Decimal("0"))
    residual_value_pv: Decimal = Field(default=Decimal("0"))
    whole_life_cost: Decimal = Field(default=Decimal("0"))
    entry_count: int = 0


class WholeLifeCoverage(BaseModel):
    """How much of the model is covered by carbon / cost data."""

    bim_element_count: int = 0
    embodied_linked_count: int = 0
    operational_linked_count: int = 0
    lcc_linked_count: int = 0
    embodied_coverage_pct: float = 0.0
    operational_coverage_pct: float = 0.0
    lcc_coverage_pct: float = 0.0


class WholeLifeResponse(BaseModel):
    """Combined 6D whole-life view: carbon and cost side by side."""

    inventory_id: UUID
    study_period_years: int
    carbon: WholeLifeCarbonBreakdown
    cost: WholeLifeCostBreakdown
    coverage: WholeLifeCoverage
    carbon_price_per_tonne: Decimal | None = None
    cost_of_whole_life_carbon: Decimal | None = None
